# 장면 얼굴 합성 기능 통합 명세

작성·구현: 2026-09-28 · 브랜치 `feat/faceswap`

기존 FaceFusion Web Wrapper 기획을 장면의 영상 자산·인증·작업 큐에 통합했다. 아래는 실제 구현 계약이다. 설치 진단은 [로컬 점검](facefusion-local-verification.md), 실행·검증은 [운영 가이드](faceswap.md)를 참고한다.

## 1. 사용 흐름

1. 영상 보관함에서 기존 영상을 열고 **얼굴 합성**을 선택한다.
2. 새 설정을 만들거나 저장된 설정을 선택한다.
3. JPEG/PNG Source 이미지 한 장을 올리고 얼굴 찾기를 실행한 다음 사용할 얼굴을 직접 선택한다.
4. 영상 기준 프레임을 분석하고 교체할 얼굴을 bbox 또는 썸네일에서 선택한다.
5. 빠르게/균형/고품질, 인물 매칭 범위, H.264/HEVC를 설정한다.
6. 기준 프레임이나 다른 프레임의 미리보기를 생성하고 원본/합성 비교 슬라이더로 확인한다.
7. 현재 설정의 성공한 미리보기가 있으면 전체 영상 처리를 시작한다.
8. 기존 작업 화면에서 진행률·취소·재시도·다운로드를 이용한다. 결과를 새 영상으로 등록하면 자막 작업을 이어서 만들 수 있다.

설정 저장·얼굴 분석은 전체 영상 처리를 시작하지 않는다. 얼굴 합성 경로는 LLM 공급자를 초기화하지 않으며 전사·번역 API를 호출하지 않는다. 모바일에서는 동일 화면을 단일 열로 제공한다.

## 2. 구성과 기존 프로젝트 호환

- Web: `FaceSwapDialog.tsx`, `faceswap.css`. 기존 `VideoWorkspace`에 진입 버튼을 제공한다.
- API: `faceswap_routes.py`. 기존 인증·CSRF·소유권·용량·파일 잠금을 재사용한다.
- 저장소: `video_service/faceswap.py`. 편집 설정과 실행 스냅샷을 분리한다.
- Worker: 기존 Dispatcher에서 공급자 초기화 전에 faceswap 실행기로 분기한다.
- Adapter: `faceswap/runner.py`는 작업 상태·결과 검증, `process.py`는 프로세스 수명, `bridge.py`는 격리 엔진 호출을 담당한다. 엔진 내부 import는 Bridge 안에만 있다.
- 기본 기능은 꺼져 있다. 엔진 없는 기존 API/Worker에서도 기존 작업을 처리한다.

분석·미리보기도 **기존 JobRecord와 공통 FIFO 큐**를 사용한다. 별도 Request 저장소와 스케줄러를 만들지 않는다. `metadata.internal=true`인 짧은 요청은 일반 작업 목록에서 숨기고 합성 설정 화면의 이력에서 관리한다. 최종 render는 일반 작업 목록에 보인다. 기존 workflow-plan API에 faceswap을 추가하지 않고 전용 requests API가 스냅샷 검증 후 Job을 만든다.

## 3. 데이터 계약

### 설정 Session

`session_id`, `asset_id`, `owner_id`, `request_id`, `revision`, `created_at`, `source_file`, `source_sha256`, `settings`를 저장한다. MVP Source는 단일 파일이다.

| settings | 의미 |
| --- | --- |
| reference_frame | FaceFusion 3.5.4 기준 1부터 시작하는 프레임 번호 |
| source_position | 왼쪽→오른쪽 정렬한 Source 얼굴 인덱스. -1은 미선택 |
| face_position | 기준 프레임의 대상 얼굴 인덱스. -1은 미선택 |
| distance | reference 임베딩 매칭 거리 0.05~1.00, 0.05 간격 |
| preset | fast / balanced / quality |
| video_codec | h264 / hevc |

Source 교체 시 source_position을 초기화한다. 화면에서 기준 프레임을 바꾸면 대상 얼굴 선택도 초기화한다. 수정은 기대 revision을 요구하며 불일치 시 409다.

### 실행 Job

요청의 설정·revision·Source hash·엔진 fingerprint를 고정하고 Source 이미지를 자체 입력 폴더로 복사한다. 이후 Session을 편집하거나 삭제해도 기존 실행/재시도 입력은 변하지 않는다. `metadata.faceswap_operation`은 analyze_source / analyze_reference / preview / render다.

`request_id`는 UUID4이며 사용자 범위에서 같은 요청의 중복 접수를 방지한다. 다른 payload로 재사용하면 409다. 세션당 활성 요청은 최대 3개다. render는 같은 설정 스냅샷의 완료·미만료 preview_job_id를 요구한다. 모델/엔진 fingerprint가 바뀌면 새 미리보기가 필요하다.

## 4. 저장소와 보존

```text
VIDEO_STORAGE_ROOT/
  .assets/{asset_id}/source.<ext>      # 기존 원본, 공유 참조
  .faceswap/{session_id}/
    session.json
    <uuid>.jpg                       # 정규화된 Source와 이전 revision
  .faceswap-capabilities.json         # Worker readiness heartbeat
  .faceswap-probe/{attempt}/          # 초기화 진단 로그
  {job_id}/
    job.json
    input/faceswap.json
    input/source.jpg
    work/faceswap-{attempt}/          # 로그, engine jobs/temp, 임시 결과
    output/*.png                     # 분석/미리보기
    output/final.mp4                  # 최종 render만
```

원본을 Job마다 복사하지 않는다. Source는 최대 10MB·2400만 화소 JPEG/PNG를 디코딩하고 EXIF 회전을 적용해 JPEG로 정규화한다. 파일명과 엔진 인자는 서버가 결정한다.

Session 삭제는 활성 작업이 있으면 409다. 작업 스냅샷은 별도 보관하므로 Session 삭제로 작업 결과가 사라지지 않는다. 영상 삭제는 Session과 Job 참조가 있으면 거부한다. Job 삭제는 기존 삭제·다운로드 잠금을 따른다. PNG는 잠금 안에서 메모리로 읽은 뒤 응답하므로 전송 중 파일 삭제에 영향받지 않는다.

완료·실패·취소 파일을 자동 삭제하지 않는 기존 보존 정책을 유지한다. 정리는 기존 명시적 collect 또는 사용자 삭제로 수행한다. 세션 Source 이력은 세션 삭제까지 보존한다.

## 5. 엔진 일치성과 미리보기

- FaceFusion 3.5.4, hyperswap_1a_256, CUDA, reference selector, left-right 정렬, box mask를 사용한다.
- Source에서 직접 고른 얼굴을 정렬 crop으로 분리하고 얼굴이 하나인지 검증한다. 미리보기와 최종 CLI 모두 같은 crop을 사용한다.
- 기준 프레임과 미리보기 프레임을 엔진의 동일한 reader로 읽는다. 기준 임베딩으로 다른 시점의 같은 인물을 찾는다. 배열 위치를 다른 프레임의 인물 ID로 사용하지 않는다.
- 미리보기는 engine process_frame에 기준 프레임과 대상 프레임을 별도로 전달한다. 이미지 CLI의 자기 자신 reference 동작을 이용하지 않는다.
- 프레임 번호 선택은 정확한 엔진 인덱스를 사용한다. 브라우저 timestamp × 평균 FPS를 정확한 프레임 번호로 가정하지 않는다. VFR의 원본 timestamp 유지·회전 특이 사례는 추가 실영상 검증 범위다.
- 모델 및 엔진 코드·runtime fingerprint를 스냅샷에 포함한다. Pinokio 설정 파일을 상속하지 않고 작업별 빈 설정과 허용된 인자로 실행한다. 엔진 소스/모델을 수정하지 않는다.
- FaceFusion의 콘텐츠 검사와 CLI 검사를 유지한다.

| Preset | Pixel boost | 모델 |
| --- | --- | --- |
| 빠르게 | 256×256 | hyperswap_1a_256 |
| 균형 | 512×512 | hyperswap_1a_256 |
| 고품질 | 768×768 | hyperswap_1a_256 |

별도 enhancer 모델은 사용하지 않는다. 품질은 입력·얼굴 크기·장면에 따라 달라진다. H.264/HEVC는 NVENC로 인코딩하고 오디오는 AAC, 볼륨 100을 명시한다. 최종 파일은 duration·오디오 존재·전체 디코딩 검증 후 원자적으로 게시한다.

## 6. 큐, 장애, 용량

기존 저장소 전체 실행 잠금 안에서 작업을 직렬 처리한다. 분석·미리보기도 STT/VAD/인코딩과 같은 큐에서 대기하며 장시간 작업을 선점하지 않는다.

상태는 QUEUED → ANALYZING → FACE_SWAPPING → VALIDATING → COMPLETED다. 실패·취소는 기존 FAILED/CANCELLED, Worker 재시작 복구는 FAILED + interrupted metadata를 사용한다. 재시도는 고정 입력으로 새 attempt를 만든다. 엔진의 processing 로그가 있으면 실제 percent를 표시한다.

Windows Job Object 및 Linux process group으로 CLI/FFmpeg 자손을 함께 종료한다. Linux Bridge에는 부모 종료 신호도 설정한다. 분석/미리보기 timeout 300초, 전체 처리 기본 86400초, 로그 한도 32MB다.

분석/미리보기는 128MB를 예약한다. render는 `duration × max(60, fps) × (width × height × 4 + 4096) + 원본 크기 × 2 + 128MB`로 보수적으로 예약한다. PNG 임시 프레임 때문에 원본 압축 영상보다 훨씬 많은 여유 공간이 필요할 수 있다. 기존 admission lock과 실행 중 용량 검사를 유지한다.

## 7. API

| Method / Path | 기능 |
| --- | --- |
| GET /api/faceswap/capabilities | readiness, fingerprint, preset, provider |
| GET/POST /api/videos/{asset_id}/faceswap-sessions | 설정 목록/생성 |
| GET/PUT/DELETE /api/faceswap/sessions/{session_id} | 설정 조회/갱신/삭제 |
| POST /api/faceswap/sessions/{session_id}/source?revision=N | 이미지 raw body 등록 |
| GET/POST /api/faceswap/sessions/{session_id}/requests | 모든 operation 이력/실행 접수 |
| GET /api/faceswap/jobs/{job_id}/files/{filename} | 소유자·완료·허용 목록 검사한 PNG |
| 기존 /api/jobs/{job_id}, cancel/retry/delete | 상태·취소·재시도·삭제 |
| 기존 /api/jobs/{job_id}/results/final.mp4 | 최종 다운로드/Range 재생 |
| 기존 POST /api/jobs/{job_id}/promote-video | 합성 결과를 새 영상 자산으로 등록 |

소유권 불일치 404, stale revision/중복 충돌 409, 잘못된 입력 422, 용량 부족 507, 엔진 미준비 503을 반환한다.

## 8. 완료 범위와 후속 범위

MVP 범위인 기존 자산 연결, 단일 Source 얼굴 선택, 다인물 기준 선택, 다른 시점 미리보기·비교·이력, preset, 최종 합성, 기존 큐·복구·인증·용량·결과 등록을 구현했다. Windows와 Docker 실제 GPU 검증 및 브라우저 검증 결과는 운영 가이드에 기록한다.

후속 범위: 다중 Source/구간별 합성, 한 Job의 합성+자막 자동 연결, 모델 상주 미리보기, GPU 단계별 병렬 큐, 시간 기반 VFR 탐색, proxy, SSE, 다중 GPU. 장시간·고해상도·회전·다양한 VFR 영상 품질/동기화는 이번 짧은 테스트가 보장하지 않는다.
