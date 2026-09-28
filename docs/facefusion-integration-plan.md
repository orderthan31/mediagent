# 장면(video-subtitle) 얼굴 합성 기능 통합 기획서

작성일: 2026-09-28

기준: 현재 작업 디렉터리의 실제 코드. 기존 FaceFusion Web Wrapper 기획서를 독립 앱이 아닌 기존 서비스의 추가 기능으로 재설계했다.

문서 상태: **구현 제안**. 현재 FaceFusion 연동은 구현되지 않았으며 설치 버전, CLI, GPU 실행 호환성도 이번 문서 작업에서는 검증하지 않았다.

후속 확인(2026-09-28): Windows 호스트의 FaceFusion 3.5.4 CLI·CUDA 추론·짧은 영상 NVENC 출력을 검증했다. [로컬 점검 결과](facefusion-local-verification.md)를 참고한다. 실제 인물 합성·타 시점 매칭과 Docker 통합은 아직 검증 전이다.

## 1. 목적과 결정 사항

현재 영상 보관함에 **얼굴 합성** 작업을 추가한다. 사용자는 이미 업로드한 영상을 선택하고, Source Face 등록 → 교체 대상 인물 선택 → 미리보기 → 전체 처리 → 다운로드까지 기존 웹 서비스 안에서 진행한다.

- 기존 React/Vite/TypeScript, FastAPI, Media Worker, 파일 저장소를 확장한다.
- 영상은 `VideoAsset`, 처리 실행은 `Job`으로 구분한다. 같은 영상으로 자막 작업과 얼굴 합성 작업을 각각 만들 수 있다.
- FaceFusion은 별도 Python 환경의 외부 엔진으로 관리하고 Worker의 Adapter를 통해 실행한다. Gradio UI를 재사용하거나 포크하지 않는다.
- MVP는 얼굴 합성 단독 작업을 제공한다. 자막까지 한 번에 실행하는 복합 작업은 후속 단계로 둔다.
- FaceFusion 기능을 끄거나 엔진이 없어도 기존 영상·전사·번역·인코딩 기능은 동작해야 한다.

## 2. 현재 프로젝트에서 확인한 구조

오래된 문서에는 업로드 완료가 `QUEUED`가 된다는 설명, Worker 미구현 설명, 상시 TTL 정리 설명 등이 남아 있다. 통합 구현은 아래 코드와 현재 보존 정책을 기준으로 한다.

| 영역 | 실제 구현 | 통합 방향 |
| --- | --- | --- |
| 웹 작업실 | `apps/web/src/VideoWorkspace.tsx` | 영상 상세의 새 작업 선택에 얼굴 합성 추가 |
| 작업 설정 | `apps/web/src/WorkflowDialog.tsx`, `video-api.ts` | 기존 작업 선택을 유지하고 얼굴 합성 전용 설정 화면 연결 |
| 스타일 | React + 일반 CSS, lucide-react | 기존 CSS와 컴포넌트 활용. Tailwind 신규 도입 불필요 |
| 영상 업로드 | `apps/api/app/api/video_upload_routes.py` | `/api/video-uploads`의 청크 업로드·재개·검증 재사용 |
| 영상 자산 | `packages/shared/video_service/assets.py` | `.assets/{asset_id}`의 원본을 읽기 전용으로 참조 |
| 처리 작업 생성 | `apps/api/app/api/workflow_routes.py` | `/api/videos/{asset_id}/jobs` 확장. 기존 작업은 생성 시 `QUEUED` |
| 작업 계획 | `packages/shared/video_service/workflows.py` | `faceswap` 템플릿과 별도 처리 단계 추가 |
| 저장소 | `repository.py`, `models.py`, `locking.py` | 파일 기반 `job.json`, 원자적 저장, OS 파일 잠금 유지 |
| 처리 실행 | `workers/media/media_worker/worker.py` | 기존 Dispatcher에 얼굴 합성 분기 추가 |
| 인증 | `apps/api/app/api/auth_routes.py`, `routes.py` | 세션·CSRF·소유권 검사 재사용 |
| 영상 제공 | `asset_routes.py`, `asset_response.py`, `result_response.py` | Range 응답·다운로드 잠금·결과 허용 목록 재사용 |
| 결과 재사용 | `POST /api/jobs/{job_id}/promote-video` | 합성 결과를 새 영상 자산으로 등록해 후속 자막 작업 가능 |
| 진행률 | 웹의 약 2.5~3초 polling | MVP도 polling 사용. SSE는 후속 선택사항 |
| 배포 | Docker Compose의 web/api/worker, GPU override | 기존 Worker의 선택적 FaceFusion 실행 환경 확장 |

기존 템플릿은 `extract_audio`, `transcribe`, `transcribe_translate`, `translate`, `encode`, `full`이다. `faceswap`은 새 제안이며 아직 존재하지 않는다.

작업 저장소를 SQLite로 전환하지 않는다. 현재 인증용 SQLite와 작업 파일 저장소는 역할이 다르다.

## 3. 사용자 경험

### 기본 흐름

1. 기존 영상 보관함에서 영상을 고른다. 없는 영상은 기존 재개 가능한 업로드로 등록한다.
2. 영상 상세 → 새 작업 → **얼굴 합성**을 선택한다.
3. Source Face 이미지 한 장을 올린다. 여러 얼굴이 검출되면 사용할 얼굴을 명시적으로 선택한다.
4. 영상에서 기준 장면을 선택하고 교체할 얼굴의 번호 또는 썸네일을 누른다.
5. 기준 장면 및 다른 시점에서 원본/합성 미리보기를 비교한다.
6. 합성 품질과 출력 설정을 확인한 뒤 **전체 영상 처리**를 누른다.
7. 기존 작업 목록에서 대기·처리 단계·실패·취소·완료를 확인한다.
8. 결과를 다운로드하거나 **결과를 새 영상으로 등록**해 자막 작업을 시작한다.

업로드·설정·미리보기만으로 전체 영상 처리나 STT/번역 호출이 시작되지 않는다. 얼굴 합성에는 LLM 공급자 설정이나 API 키가 필요하지 않아야 한다.

### 데스크톱과 모바일

- 데스크톱: 영상/프레임과 타임라인, Source Face·대상 얼굴·품질 설정, 하단 미리보기 이력.
- 모바일: 기존 영상 선택 후 Source → 대상 선택 → 미리보기 → 처리 순서. 작은 bbox와 함께 큰 얼굴 썸네일을 제공한다.
- 원본/결과 전환 및 비교 슬라이더를 MVP에 포함한다. 확대 보기는 후속 개선으로 둘 수 있다.
- 엔진 미설치·미지원 상태는 이유와 함께 표시하고 실행 버튼을 비활성화한다.
- 모바일 백그라운드에서 대용량 업로드가 계속된다고 보장하지 않는다. 기존 일시정지·재선택·재개 UX를 따른다.

## 4. 아키텍처

```text
기존 React 영상 작업실
  └─ 기존 FastAPI: 인증 / 영상 자산 / 합성 설정 / 요청 등록 / 상태 / 파일 제공
       └─ 기존 파일 저장소와 공통 실행 큐
            └─ 기존 Media Worker Dispatcher
                 ├─ 기존 자막·번역·인코딩 파이프라인
                 └─ FaceSwap 실행기
                      └─ FaceFusion Adapter
                           └─ 격리된 Python 환경의 FaceFusion subprocess
```

API에서 GPU 추론이나 전체 영상 렌더링을 직접 실행하지 않는다. 프레임 추출·얼굴 검출·미리보기도 Worker 요청으로 처리한다. API는 요청을 영속화하고 즉시 작업 식별자를 반환한다.

신규 파일 배치 제안:

```text
apps/web/src/faceswap/                 # 설정·대상 선택·미리보기 화면
apps/api/app/api/faceswap_routes.py    # 인증된 설정/요청 API
packages/shared/video_service/faceswap.py
                                      # 설정 schema·revision·요청 저장 규칙
workers/media/media_worker/faceswap/
  runner.py                           # 단계 실행·취소·결과 검증
  adapter.py                          # 엔진 호출 경계
  capabilities.py                     # 버전별 지원 기능
  command_builder.py                  # 허용된 CLI 인자 생성
  progress.py                         # 엔진 로그를 공통 진행률로 변환
  bridge.py                           # 필요한 경우 격리 환경에서 실행
```

FaceFusion 저장소와 모델 캐시는 런타임 외부 경로 또는 전용 이미지 레이어로 관리한다. 기존 저장소에 엔진 소스나 모델을 커밋하지 않는다.

## 5. 영상 자산·설정·실행의 구분

### VideoAsset

이미 등록된 원본 영상이다. 합성을 위해 다시 업로드하거나 Job마다 원본을 복사하지 않는다. 기존 `metadata.asset_id`와 `source_asset_id` 관계를 유지한다. 공유 원본은 읽기 전용이며 작업 삭제 시 삭제하지 않는다.

### FaceSwap Session — 신규

영상에 속하는 편집 가능한 설정 묶음이다. Source 이미지, 기준 프레임, 선택한 얼굴, 미리보기 이력을 보관한다. 설정 저장은 합성 실행과 구분한다.

- `session_id`, `asset_id`, `owner_id`, `revision`, 생성·수정 시각.
- `sources[]`: MVP는 1개만 허용하되 구조는 배열. 여러 Source 인물의 매핑은 후속 기능.
- `reference`: 요청 시각, 실제 프레임 시각/번호, 검출 결과 ID, 선택 얼굴 ID, 엔진 정렬 기준과 position.
- `preset`, 엔진 옵션, 출력 옵션, capability 식별자.
- 수정 요청은 기대 revision을 함께 보내고 충돌 시 409를 반환한다.

### FaceSwap Request — 신규

프레임 분석·Source 분석·미리보기용 짧은 Worker 요청이다. 일반 최종 결과 Job과 구분해 기존 `final.mp4` 다운로드·자막 UI와 섞이지 않게 한다.

- 상태: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Session revision과 입력 스냅샷을 고정한다. 요청 후 편집해도 실행 중 입력은 바뀌지 않는다.
- `request_id`의 멱등성, `queued_at`, 실행 잠금, heartbeat, 재시작 복구를 제공한다.
- 단순 메모리 큐가 아니라 디스크에 기록한다. 이 큐도 공통 Worker가 처리한다.

### 최종 Job

기존 `JobRecord`와 `job.json`을 사용한다. 실행 버튼을 누를 때 설정과 Source 이미지 스냅샷을 Job 입력에 저장한 뒤 `QUEUED`로 공개한다. 결과는 `output/final.mp4`로 통일한다.

제안 metadata 예시(실제 API 구현 전 계약 확정 필요):

```json
{
  "asset_id": "<existing asset id>",
  "source_asset_id": "<existing asset id>",
  "workflow": {
    "version": 2,
    "template": "faceswap",
    "stages": ["analyze", "faceswap", "validate_video"],
    "reused": ["video"],
    "paid_stages": []
  },
  "faceswap": {
    "schema_version": 1,
    "session_id": "<session id>",
    "revision": 3,
    "engine": "facefusion",
    "engine_fingerprint": "<verified version and configuration hash>",
    "sources": [{"source_id": "<source id>", "sha256": "<content hash>"}],
    "reference": {"frame_number": 429, "timestamp": 14.32, "face_id": "<detection id>", "face_position": 0},
    "preset": "balanced"
  }
}
```

숫자는 설명용이며, 시각에서 프레임 번호를 단순 반올림해 계산하는 구현 예시가 아니다.

## 6. 저장 구조와 삭제 규칙

```text
VIDEO_STORAGE_ROOT/
  .assets/{asset_id}/
    asset.json
    source.<ext>                      # 기존 공유 원본
    faceswap/{session_id}/             # 신규 설정 저장소
      session.json
      sources/
      references/
      previews/
      requests/{request_id}/          # request.json, 로그, 개별 작업 공간
  {job_id}/
    job.json                          # 기존 작업 형식
    input/faceswap.json               # 고정 설정 스냅샷
    input/faces/                      # Source 스냅샷
    work/faceswap/                    # 엔진 temp, 로그, 미완성 출력
    output/final.mp4
```

- Session 삭제 전 활성 분석/미리보기 요청과 파일 전송을 검사한다. 참조 중이면 409다.
- 영상 자산 삭제는 기존 Job 참조 검사에 Session 요청 실행·다운로드 잠금 검사도 추가한다.
- 최종 Job은 필요한 Source와 기준 식별 정보를 자체 보관하므로 Session 수정/삭제로 재시도 입력이 바뀌지 않는다.
- Job 삭제는 Job 소유 파일만 제거한다. 영상 원본과 다른 Session/Job 파일은 보존한다.
- 현재 `docs/development-preservation.md` 및 Worker 동작을 따른다. 완료·실패·취소 직후 파일을 자동 삭제하지 않는다.
- TTL 삭제는 별도 정리 배치의 명시적 실행 범위로 확장한다. 원안의 ‘상시 완료 후 3일 자동 삭제’는 적용하지 않는다.
- `.assets` 아래 새 요청은 기존 최상위 orphan 정리의 관리 대상이 아니므로 요청/Session용 복구·정리 경로를 별도로 추가한다.

## 7. 업로드·메타데이터·영상 탐색

Target 영상은 기존 `/api/video-uploads`만 이용한다. offset·SHA-256 재개 검증·청크 실패 롤백·용량 검사·소유권 규칙을 유지한다.

Source 이미지는 Session 전용 API로 받는다. 파일명 대신 서버 ID로 저장하고 크기·픽셀 수·실제 이미지 디코딩을 검증한다. MVP는 JPEG/PNG를 대상으로 하고 지원 형식과 제한값을 서버가 제공한다. 입력 얼굴이 없으면 안내하고 자동 실행하지 않는다.

현재 `video_probe.py`는 duration/크기/codec/평균 frame rate/오디오 유무를 제공한다. 정확한 frame count, PTS, 회전 방향, 오디오 codec은 필요한 만큼 확장한다.

프레임 탐색 규칙:

- 원본은 기존 Range stream API로 재생한다.
- 요청 timestamp와 실제 추출 프레임의 PTS·엔진 기준 frame number를 구분해서 저장한다.
- VFR 영상에서 `timestamp × 평균 fps`를 정확한 프레임 번호로 취급하지 않는다.
- 추출기와 FaceFusion의 프레임 해석이 일치하는지 검증한다. 불일치 입력은 명시적으로 제한하고 잘못된 인물 선택 상태로 렌더링하지 않는다.
- 회전 metadata, 표시 크기, letterbox를 반영해 bbox 클릭 좌표를 변환한다.
- 브라우저에서 재생할 수 없는 원본은 요청형 탐색 proxy를 후속 지원할 수 있다. proxy를 만들면 원본과 시간 대응을 검증하고 별도 용량을 예약한다. MVP에서는 서버 프레임 탐색을 대안으로 제공한다.
- 합성 입력은 원본을 유지한다. 원본을 임의로 재인코딩해 대체하지 않는다.

## 8. 얼굴 선택과 엔진 일치성

검출된 모든 얼굴에 bbox·번호·crop 썸네일을 제공한다. 가장 큰 얼굴을 자동 확정하지 않는다.

Frontend의 배열 index를 `reference-face-position`으로 그대로 전달하지 않는다. Adapter가 검출 설정·얼굴 정렬·필터·엔진 버전을 함께 고정하고 선택 ID를 엔진 position으로 변환한다.

얼굴 검출에 엔진 내부 모듈이 필요하면 FaceFusion 전용 환경의 작은 Bridge에서만 import한다. API/공통 모델이 엔진 내부 타입에 의존하지 않게 한다. 반환 형식은 JSON과 파일 ID로 제한한다.

‘인물 매칭 엄격도’는 설치 버전의 거리 임계값 의미를 확인한 뒤 매핑한다. 숫자가 커지면 더 엄격하다고 임의로 가정하지 않는다. 검출 설정이나 엔진 버전이 바뀌면 기존 얼굴 선택을 다시 검증한다.

## 9. 미리보기: 구현 전 검증이 가장 중요한 부분

**기준 인물 프레임과 결과 확인 프레임은 별개다.**

- 기준 프레임: 교체 대상 인물을 정한다.
- 미리보기 프레임: 같은 인물이 다른 시점에서도 올바르게 선택되고 합성되는지 확인한다.

이미지 하나를 CLI target으로 넘기는 것만으로 원본 영상의 기준 인물 정보까지 전달된다고 가정하지 않는다. 다른 시점의 이미지에 기준 프레임 번호나 같은 얼굴 배열 index를 넣는 방식은 채택하지 않는다.

Phase 0에서 아래 순서로 가능성을 확인한다.

1. 설치 버전의 공식 CLI가 기준 인물과 테스트 프레임을 함께 표현할 수 있는지 확인한다.
2. 불가능하면 격리 Bridge로 원본 기준 인물 정보를 만들고 테스트 프레임 매칭과 단일 프레임 처리를 수행한다.
3. 내부 인터페이스 의존 범위를 Adapter에 한정하고 버전/commit을 고정한다.

원안의 ‘CLI 이미지 실행만으로 모든 시점 미리보기 제공’은 검증 전 확정하지 않는다. 타 시점 매칭이 구현되지 않으면 해당 기능을 숨기고 제한을 명시하며, **다중 시점 미리보기를 포함한 최종 MVP 완료로 판정하지 않는다.** 미리보기 때문에 전체 영상을 처리하지 않는다.

미리보기 계약:

- 비동기 요청으로 즉시 202와 요청 ID를 반환하고 polling으로 결과를 받는다.
- 캐시 키는 영상·Source 해시·기준 얼굴·테스트 프레임·옵션·엔진 fingerprint를 포함한다.
- 원본과 결과는 동일한 프레임을 나란히 제공한다. 매칭 실패는 ‘대상 인물 없음’으로 구분한다.
- 과거 revision의 결과는 이력으로 남기되 현재 설정의 결과처럼 표시하지 않는다.
- 현재 설정으로 성공한 미리보기를 확인해야 전체 처리를 허용한다. 전 구간 품질을 보증하는 것으로 표현하지 않는다.
- 동일 설정의 중복 요청은 기존 요청으로 응답한다. 사용자가 빠르게 탐색해도 대기열이 무한히 쌓이지 않도록 Session별 대기 개수를 제한한다.

## 10. 품질·출력·자막 연결

기존 `quality_profile`의 `balanced/high/compact`는 인코딩 설정이다. 합성용 `fast/balanced/quality`는 `faceswap.preset`으로 분리한다. 서로 이름을 바꾸거나 덮어쓰지 않는다.

Preset이 사용하는 모델·enhancer·검출 설정은 Backend capability와 버전별 설정이 관리한다. 실제 처리 차이를 검증하지 않은 fast/balanced를 이름만 다르게 제공하지 않는다. 지원되지 않는 preset은 표시하지 않는다.

MVP의 합성 작업은 자막 없는 영상 결과를 생성한다. `subtitle_mode=none`을 명시하고 기존 STT·번역·자막 생성 단계를 건너뛴다. 기존에 화면에 번인된 자막을 제거하는 기능은 제공하지 않는다.

출력 codec·해상도는 기존 UI 선택과 호환되도록 Adapter에서 검증한다. 지원 불가능한 조합은 접수 전에 안내한다. 엔진이 최종 출력까지 만들면 기존 인코딩 단계를 무조건 다시 실행하지 않는다.

최종 검증은 파일 존재뿐 아니라 video stream, 크기, 재생 가능 여부, 원본과 duration/시간축 대응, 원본 오디오 존재 시 보존 여부를 확인한다. FPS 변경·구간 자르기는 초기 범위에서 제외한다. 오디오 컨테이너 호환 변환이 필요하면 명시적으로 처리하고 A/V sync를 검증한다.

기존 자막과의 연결:

- 합성 결과를 기존 `promote-video`로 새 자산으로 등록한 뒤 새 자막 작업을 실행할 수 있다.
- 현재 자막 artifact는 자산에 종속되므로 원본 자막을 합성 결과 자산에 자동 참조시키지 않는다.
- 기존 자막 재사용은 SRT 다운로드/새 자산 첨부 경로로 가능하다. 자동 복사 UI는 시간축 검증과 provenance 기록을 추가한 후 지원한다.
- `full + faceswap`을 한 Job으로 묶는 기능은 후속 단계다. 도입 시 자막 검토 승인 이후 합성/출력 연결과 이중 인코딩 방지를 별도 설계한다.

## 11. 큐·GPU·진행률

현재 `Worker.tick()`은 저장소 전체 실행 잠금으로 작업을 직렬 처리한다. GPU 전용 잠금만 있는 구조가 아니다.

MVP는 이 구조를 유지하고 분석·미리보기 요청도 같은 Dispatcher의 처리 대상으로 추가한다. 기존 Job과 신규 요청의 `queued_at`을 비교하는 공통 FIFO 스케줄러로 정리한다. 현재 `_tick_serial()`의 전체 Job 순회 방식은 새 요청도 반영하도록 수정한다.

- 동시에 실행하는 미디어 작업은 기본 1개다. FaceFusion 외에도 기존 GPU VAD/NVENC와 충돌하지 않는다.
- 실행 중인 최종 작업은 미리보기로 선점하지 않는다. 미리보기 UI에 대기 상태와 취소 버튼을 제공한다.
- 이 보수적 정책에서는 기존 STT/번역 작업 중에도 미리보기가 기다릴 수 있다. GPU 단계만 따로 잠그는 병렬화는 후속 개선이다.
- 별도 FaceFusion 서비스가 잠금 밖에서 실행되는 구성을 MVP에 혼합하지 않는다.
- 로그 파싱이 가능한 경우에만 단계별 percent를 표시한다. 불가능하면 단계명·경과시간을 표시하고 가짜 진행률을 만들지 않는다.
- 전체 완료는 프로세스 exit 0, 출력 검증, 결과 manifest 게시 이후에만 기록한다.

## 12. 상태·취소·재시작·재시도

최종 Job 상태 제안:

```text
QUEUED → ANALYZING → FACE_SWAPPING(신규) → VALIDATING → COMPLETED
                                          ↘ FAILED / CANCELLED
```

`FACE_SWAPPING` 추가 시 Python enum/ACTIVE_STATUSES, API 응답 타입, 웹 상태 라벨·진행률, 취소·재시도·복구 처리까지 함께 갱신한다. 기존 레코드에 새 필드가 없으면 기존 파이프라인으로 해석한다.

현재 중단 복구는 `FAILED + metadata.interrupted=true` 방식이다. 원안의 별도 `interrupted` 상태를 새로 도입하지 않는다. 신규 짧은 요청도 실제 실행 잠금과 프로세스 종료를 확인한 후 중단 실패로 복구한다. API 재시작만으로 정상 Worker 작업을 실패 처리하지 않는다.

현재 `process.py`는 직접 자식 프로세스 terminate/kill을 제공하지만 전체 자손 종료 보장은 확인되지 않았다. FaceFusion 연동 시 Linux process group과 Windows Job Object 등 실행 환경별 process tree 종료를 구현·검증한다. 취소 표시 및 GPU 잠금 해제는 자손 종료 확인 후 수행한다.

Source/설정/엔진 fingerprint가 같은 경우에만 재시도 입력과 검증된 중간 결과를 재사용한다. 영상 합성은 초기에는 해당 단계 처음부터 다시 실행한다. 미완성 출력은 성공 결과로 게시하지 않고 별도 attempt 경로에 보존한다.

## 13. API 제안

아래 ‘신규’ 경로는 기획용이며 아직 구현되지 않았다. 모든 경로는 기존 인증·CSRF·소유권 규칙을 적용한다.

| 구분 | API | 역할 |
| --- | --- | --- |
| 기존 | `POST/GET /api/video-uploads` 및 chunk/verify/complete | 영상 업로드 |
| 기존 | `GET /api/videos/{asset_id}/stream` | 원본 재생 |
| 신규 | `GET /api/faceswap/capabilities` | Worker가 확인한 엔진 지원 기능과 준비 상태 |
| 신규 | `POST/GET /api/videos/{asset_id}/faceswap-sessions` | 설정 생성/목록 |
| 신규 | `GET/PUT/DELETE /api/videos/{asset_id}/faceswap-sessions/{session_id}` | revision 기반 설정 관리 |
| 신규 | `POST .../faceswap-sessions/{session_id}/sources` | Source 파일 등록 |
| 신규 | `POST .../faceswap-sessions/{session_id}/requests` | `analyze_source`, `analyze_reference`, `preview` 요청 |
| 신규 | `GET .../faceswap-sessions/{session_id}/requests` | 분석·미리보기 이력 |
| 신규 | `GET .../faceswap-sessions/{session_id}/requests/{request_id}` | 상태/검출 결과/미리보기 조회 |
| 신규 | `POST .../requests/{request_id}/cancel` | 대기/실행 요청 취소 |
| 신규 | `GET .../faceswap-sessions/{session_id}/files/{file_id}` | 허용 목록에 등록된 이미지 제공 |
| 확장 | `POST /api/videos/{asset_id}/workflow-plan` | faceswap 계획·입력 검증 |
| 확장 | `POST /api/videos/{asset_id}/jobs` | template=faceswap, Session revision을 고정해 최종 Job 생성 |
| 기존 확장 | `GET /api/jobs/{job_id}`, cancel/retry/delete | 최종 작업 관리 |
| 기존 | `GET /api/jobs/{job_id}/results/final.mp4` | 완료 결과 다운로드 |
| 기존 | `POST /api/jobs/{job_id}/promote-video` | 결과를 새 영상 자산으로 등록 |

생성 멱등성은 사용자 범위 `request_id + 정규화 payload`를 기준으로 한다. 다른 설정으로 같은 ID를 재사용하면 409다. 최종 실행 요청은 같은 revision의 유효한 미리보기와 입력 완전성을 확인한다.

파일 API는 서버 경로를 받지 않는다. Session/Job 소유권과 허용 파일 ID를 확인하고 다운로드 잠금을 전송 종료까지 유지한다. 소유권 불일치는 기존 정책대로 404다. 용량 부족은 507, 지원하지 않는 설정은 422, revision/실행 충돌은 409로 구분한다.

## 14. 엔진 capability와 배포

FaceFusion 설치·버전 확인은 실제 **Worker가 엔진을 실행하는 환경**에서 수행한다. 호스트 설치 경로를 Docker API에서 실행할 수 있다고 가정하지 않는다.

제안 설정: `FACEFUSION_ENABLED`, `FACEFUSION_PYTHON`, `FACEFUSION_PATH`, 엔진 timeout, 모델 캐시 경로, Source 제한, 미리보기 대기 제한. 저장소는 기존 `VIDEO_STORAGE_ROOT`를 사용한다.

- 로컬: Worker가 별도 venv/conda Python을 argument list 방식으로 실행한다.
- Docker: FaceFusion용 Python 환경이 포함된 선택적 Worker 이미지/override를 제공한다. 기존 web/api 이미지는 불필요한 엔진 의존성을 갖지 않는다.
- Windows 호스트 Python을 Linux 컨테이너에서 직접 실행하는 설계는 사용하지 않는다.
- 기존 GPU override만 추가하면 FaceFusion이 설치되는 것은 아니다. GPU 접근·추론 runtime·모델·FFmpeg를 별도 확인한다.
- LAN/Tailscale 접속은 기존 배포 경로를 확장한다. 기본 Compose 포트가 localhost에 바인딩되어 있으므로 원안의 `0.0.0.0`만으로 접속 가능하다고 쓰지 않는다.

Capability에는 버전/commit, 지원 preset·옵션, 구성된 provider, 실제 시험 성공 여부, 마지막 확인 시각, unavailable 이유를 분리한다. `--help`에 CUDA 옵션이 있다는 사실을 GPU 동작 성공으로 간주하지 않는다. stale한 Worker 상태는 준비 완료로 표시하지 않는다.

## 15. 저장 용량과 보존

FaceFusion이 전체 프레임을 추출하는 방식이라면 압축 원본 크기의 4배보다 훨씬 큰 공간이 필요할 수 있다. 기존 자막 작업의 4배 예약식을 그대로 사용하지 않는다.

- 엔진의 실제 temp 전략을 확인하고 해상도·프레임 수·임시 포맷·결과 크기·모델 캐시를 반영한 보수적 예약식을 정한다.
- 기존 admission lock 및 `remaining_reservations`에 신규 요청 예약도 포함한다. `.assets`의 요청 예약은 현재 코드가 자동 합산하지 않는다.
- 미리보기·스냅샷·모델 저장이 실제 사용량 또는 별도 캐시 볼륨의 여유 공간 검사에 포함되게 한다.
- 실행 중 여유 공간도 검사하고 부족하면 중단 실패로 기록한다. 원본과 기존 결과는 보존한다.
- 거부된 요청, 중단된 파일 게시, 고아 스냅샷에 대한 예약 해제와 복구 규칙을 테스트한다.

## 16. MVP와 후속 범위

**MVP 필수**

- 기존 영상 자산으로 얼굴 합성 작업 생성.
- Source 1장, Source 인물 및 다인물 영상의 Target 인물 명시적 선택.
- 정확한 기준 프레임/얼굴 순서 매핑.
- 기준 장면과 다른 시점의 미리보기, 비교 슬라이더, 이력.
- 실제 지원되는 품질 preset, 엔진 capability, 기능 비활성화 처리.
- 기존 Worker 공통 직렬 큐, polling, 취소, 실패 복구와 재시도.
- 결과 다운로드 및 새 영상으로 등록.
- 인증·소유권·용량·파일 보존 규칙 통합.
- 실제 배포 환경의 GPU 동작 및 다인물 결과 검증.

**후속 기능**

- 한 Job에서 얼굴 합성과 자막 파이프라인 연결.
- 자산 간 자막 artifact의 안전한 재사용 UI.
- 다중 Source/다중 인물 매핑, 구간별 합성.
- 모델 상주 Preview Worker, GPU 단계별 병렬 스케줄링.
- 자동 인물 매칭 점검, 확대 비교, 영상 탐색 proxy 고도화.
- SSE/WebSocket, 다중 GPU, 다른 얼굴 합성 엔진.

## 17. 구현 단계와 완료 기준

| 단계 | 작업 | 완료 기준 |
| --- | --- | --- |
| 0. 호환성 POC | 실제 Worker 환경에서 FaceFusion 버전/도움말/코드 확인, CUDA 테스트, 얼굴 정렬·프레임 매핑·다른 시점 미리보기 조사 | 다인물 짧은 영상에서 선택 인물이 미리보기와 최종 출력에 일치. 엔진 버전과 의존 경계 기록 |
| 1. 계약·저장소 | Session/Request schema, revision, snapshots, capability, 잠금·예약 | 기존 Job 읽기 유지, 동시 편집/멱등성/소유권/입력 게시 검증 |
| 2. 프레임·얼굴 선택 | 기존 영상 player 연결, Source/Reference 분석, bbox/썸네일 | 회전 영상·다인물·얼굴 없음·지원 VFR 사례에서 선택 일치 |
| 3. 미리보기 | 비동기 요청, 공통 FIFO, 비교와 이력, cache key | 다른 시점의 동일 인물 매칭, revision 변경 시 과거 결과 분리, 취소·재시작 복구 |
| 4. 최종 처리 | faceswap 템플릿, 상태·진행률, 실행기, 결과 검증 | STT/번역 호출 없이 결과 생성, A/V sync 확인, 재시도·process tree 종료 검증 |
| 5. 서비스 통합 | 결과 자산 승격, 모바일, Docker GPU, 보존·용량 | 업로드 재사용부터 합성/다운로드/후속 자막 작업까지 실제 환경 E2E |

Phase 0을 통과하기 전에 CLI 옵션·모델명·미리보기 방식과 일정을 확정하지 않는다. 자동 테스트는 mock 엔진으로 비용 없이 실행하고 실제 GPU smoke test를 별도로 구분한다.

필수 회귀 검증:

1. FaceFusion 비활성 상태에서 기존 업로드·전사·번역·자막 검토·인코딩이 유지된다.
2. 합성 작업이 LLM provider 초기화나 유료 API 호출 경로로 진입하지 않는다.
3. 기존 레코드·추가 언어·자막 모드·완료 결과를 정상 조회한다.
4. 다른 계정의 Source/기준 프레임/미리보기/결과에 접근할 수 없다.
5. 기존 작업과 미리보기·합성을 동시에 요청해도 실행 잠금 밖의 GPU 작업이 생기지 않는다.
6. 다운로드 중 삭제, 원본 참조 중 자산 삭제, Session 편집 중 실행 요청의 경합을 처리한다.
7. 엔진 실패·강제 중단·재시작·디스크 부족 시 원본과 기존 결과를 보존한다.
8. 엔진 업데이트 후 얼굴 정렬·타 시점 매칭·1초 이상 영상 출력·오디오 동기화를 다시 검증한다.

## 18. 원안 대비 변경 요약

| 원안 | 변경안 |
| --- | --- |
| 별도 faceswap-web 모노레포 | 현재 장면 프로젝트의 얼굴 합성 기능 |
| 새 React/Tailwind와 FastAPI 구성 | 기존 Web/API/CSS 재사용 |
| Job마다 Target 영상 업로드·복사 | 영상 자산 1회 업로드 후 여러 작업에서 참조 |
| SQLite 작업 DB 신규 도입 | 기존 파일 기반 Job 저장소 유지 |
| API에서 엔진 실행 | 기존 Media Worker의 전용 Adapter에서 실행 |
| FaceFusion 프로세스끼리만 동시 실행 제한 | 기존 VAD/인코딩을 포함한 공통 Worker 직렬 실행 |
| CLI 이미지 처리로 모든 미리보기 해결 | 기준 인물 전달과 타 시점 매칭을 POC로 먼저 검증 |
| SSE 우선 | 기존 polling 우선 |
| 인증은 추후 추가 | 기존 세션·CSRF·소유권 즉시 적용 |
| 완료 후 자동 정리 | 현재 파일 보존 및 별도 정리 배치 정책 유지 |
| 새 interrupted 상태 | 기존 FAILED + interrupted metadata 활용 |
| 합성 영상 다운로드로 종료 | 결과를 자산으로 승격해 기존 자막 작업에 연결 |

## 19. 구현자 지침

이 문서는 설계 변경이며 구현 완료 보고서가 아니다. 기존 작업 디렉터리의 다른 변경을 덮어쓰지 않는다. 실행 환경을 수정하거나 대용량 모델을 설치하기 전에 프로젝트의 실제 실행 구성을 확인한다.

FaceFusion은 지정된 전용 Python에서 `facefusion.py --version`, `facefusion.py headless-run --help` 지원 여부를 실제 확인하고, 해당 버전의 얼굴 정렬·reference selector·preview 처리를 조사한다. 문서의 명령을 지원 확인 없이 제품 코드에 그대로 넣지 않는다.

엔진 호출은 `shell=False`와 인자 배열을 사용하고 사용자 입력 CLI 문자열은 허용하지 않는다. public CLI를 우선하되 꼭 필요한 내부 모듈 의존은 격리 Bridge 한 곳으로 제한한다. 엔진 내부 소스는 수정하지 않는다.

공통 큐에 새 요청을 넣는 것뿐 아니라 Worker의 복구·용량 예약·삭제·파일 전송 잠금까지 통합한다. 현재 단위 테스트 통과와 실제 RTX 5070 Ti 엔진 실행 검증은 별개의 완료 조건으로 기록한다.
