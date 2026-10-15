# 얼굴 합성 실행·검증 가이드

## 운영 배포 확인 (2026-09-29)

운영 `video-subtitle-worker-1`에 FaceFusion 3.9.0과 기존 NeMo 3.0.0 / PyTorch
2.11.0+cu128 환경을 함께 반영했다. `/api/faceswap/capabilities`에서 `ready: true`,
`provider: cuda`, fast/balanced/quality 프리셋을 확인했다. 기본 청크는 600초다.
기존 운영 데이터 경로 `data/user-preview/jobs`, 웹 포트 5177, 유료 전사 활성화와
CUDA VAD / HEVC NVENC 설정을 유지했다.

운영 재배포 시 기존 vad, gpu, host-data, vad-gpu overlay에 **faceswap overlay까지**
포함해야 한다. API·웹만 갱신하거나 faceswap overlay를 빼면 엔진이 없는 Worker가
남아 합성 입력이 비활성화된다. `scripts/start-existing-docker.ps1`은 현재 배포 구성을
그대로 시작하므로 재시작 용도로 사용할 수 있다.

운영 Worker 후보 이미지 `video-subtitle-worker:faceswap-vad`는 검증된 로컬 GPU VAD와
FaceFusion 런타임을 재사용하고 최신 프로젝트 코드를 설치했다. 재사용 빌드 정의는
로컬 `.tools/Dockerfile.faceswap-combined`에 있으며 curl도 포함한다.
일반 신규 빌드는 저장소 Dockerfile과 전체 overlay 조합을 사용한다.
테스트는 운영 파일을 연결하지 않은 컨테이너에서 공개 예제의 얼굴 검출·미리보기·
2개 청크 합성·NVENC 최종 인코딩·선택 인물 유지·결과 자산 등록까지 통과했다.

화면에서 엔진 준비 상태와 사용 순서를 안내한다. 전체 처리 버튼은 새 얼굴과 대상
얼굴을 선택하고 현재 설정의 미리보기를 완료해야 활성화된다.

### FaceFusion 3.9.0 업데이트

공식 안정 릴리스 3.9.0으로 프로젝트의 Docker 엔진을 업데이트했다. 호스트 Pinokio의 3.5.4 설치 및 모델 폴더는 변경하지 않았다. 기존 HyperSwap 모델과 품질·마스크 설정을 재사용하며 새 AlphaFace/HRFFA 모델 선택 UI는 이 업데이트 범위에 포함하지 않는다.

3.9.0의 face_creator, 소스/대상 목록을 받는 얼굴 선택 API, 새 얼굴 캐시 및 영상 reader 생명주기에 대응한다. 프로젝트에 저장된 1 기반 프레임 번호는 엔진 입출력 경계에서 0 기반으로 변환한다. 청크 CLI에도 같은 변환을 적용하고 disk workflow 및 단일 프레임 선택을 명시해 기존 인물 선택과 10분 청크 파이프라인을 유지한다. 엔진 fingerprint가 바뀌므로 기존 세션을 열면 새 미리보기가 필요하다.

공개 샘플에서 첫/중간/마지막 프레임(1/135/270)의 픽셀이 FFmpeg의 해당 원본 프레임과 완전히 일치했다. 1080p 공개 샘플의 반복 미리보기 엔진 처리 시간은 약 0.38초였다. 관련 회귀 테스트 28개와 GPU 다인물·전체 마스크·두 청크 렌더링·선택 인물 유지·자산 등록 통합 검증을 통과했다. 기존 NeMo 3.0.0 / PyTorch 2.11.0+cu128 환경은 유지했다.

운영 후보 태그는 `video-subtitle-worker:faceswap-3.9.0`, 이전 엔진 롤백 태그는 `video-subtitle-worker:faceswap-3.5.4-rollback`이다. 신규 설치는 저장소 Dockerfile의 공식 태그·커밋 고정을 사용한다. 설치된 3.5.4 엔진도 브리지에서 계속 지원한다.

2026-09-28 구현. [통합 명세](facefusion-integration-plan.md)와 함께 읽는다.

## 사용법

영상 보관함 → 영상 상세 → **얼굴 합성**에서 설정을 자동으로 준비한다. Source JPEG/PNG를 등록하면 자동 분석하며 얼굴이 하나면 자동 선택한다. 여러 명일 때만 원하는 얼굴을 누른다.

플레이어를 탐색하고 멈추면 현재 커서의 얼굴 분석과 미리보기를 자동 실행한다. 200ms 동안 변경을 모으고 한 번에 하나의 요청만 실행한다. 실행 중 커서를 움직이면 완료 후 마지막 위치를 처리한다. 대상 인물을 선택한 뒤에는 미리보기 요청 하나가 얼굴 검출 결과도 반환하므로 별도 분석 요청을 기다리지 않는다. 선택한 대상의 기준 프레임은 커서를 옮겨도 유지되며, 다른 얼굴을 클릭할 때만 변경한다. 실패한 자동 요청은 무한 재시도하지 않으며 다시 분석/생성 버튼이나 요청 재시도로 복구한다.

### 미리보기 응답 시간

Gradio처럼 전용 Python 프로세스와 CUDA 추론 세션을 재사용한다. 세션 전환 시 얼굴·영상 프레임 캐시는 비우고 모델 가중치는 유지한다. 검출 각도 변경 시 얼굴 캐시를 무효화하며 프레임 캐시도 제한한다. 취소·오류·시간 초과·180초 유휴·워커 종료 시 프로세스 트리를 종료한다. 전체 합성이나 다른 전사/인코딩 작업 시작 전에는 미리보기 엔진을 종료해 GPU 메모리를 반환한다. 기존 FaceFusion 콘텐츠 검사는 매 요청 그대로 수행한다.

API 요청은 워커에 즉시 깨우기 신호를 기록하며, 대기 중 미리보기는 일반 작업보다 먼저 실행한다. 실행 중인 전체 영상 작업을 중단하지는 않는다. 화면은 500ms 간격으로 결과를 확인하고 갱신 중에도 이전 미리보기를 표시한다.

RTX 5070 Ti, Docker, 공개 426×226 예제, 균형(512×512 boost), 동일 프레임 90/135 기준 `scripts/benchmark-faceswap-preview.py` 측정: 일회 Python 실행 9.01초/9.01초 → 모델 재사용 0.704초/0.729초. 최초 사진 분석+대상 분석+미리보기 합계는 26.625초 → 9.310초. 변경 전후 결과 PNG의 SHA-256이 같았다. 이 수치는 엔진 처리 시간이며 화면 조회·대기 시간은 제외한다. 처음 모델을 올리거나 유휴 종료 후 다시 실행할 때는 초기화 시간이 필요하며 해상도·품질에 따라 달라진다.

박스·가림 처리(occlusion)·랜드마크 다각형 영역(area)·부위(region) 마스크, 경계 블러, 상우하좌 여백, 영역/부위 선택과 검출 회전각을 제공한다. `area`는 엔진의 자동 윤곽 다각형이며 자유롭게 점을 찍는 편집기는 아니다. 검출 회전각 0/90/180/270은 화면 회전 대응이며 정면/측면 필터가 아니다. 설치된 3.5.4에는 정면/측면 필터가 없다. 미리보기와 전체 CLI 처리에 같은 옵션을 전달한다. 기존 세션에는 기존 동작을 유지하는 기본값을 보충한다.

미리보기는 현재 결과와 비교 슬라이더만 표시하며 분석 요청 로그와 과거 결과 목록은 표시하지 않는다. 설정을 바꾸거나 엔진을 업데이트하면 새 미리보기가 필요하다. 완료 결과는 기존 다운로드 메뉴 및 **새 원본으로 등록**으로 이어진다. 합성 작업 상세에는 합성 취소/재시도와 결과 영상이 표시된다.

### 운영 저장소 지연 개선 (2026-09-28)

기존 엔진 단독 벤치마크는 API·워커의 전체 저장소 용량 검사 시간을 포함하지 않았다. 운영 92.31 GiB 저장소의 재귀 파일 검사가 10.859초 걸리는 것을 확인했다. 미리보기 접수는 백그라운드 용량 감사와 보수적인 예약 장부를 사용하고 실제 디스크 여유 공간은 즉시 검사한다. 감사가 오래됐거나 없으면 전체 검사로 복귀한다. 전체 영상 렌더링의 용량 검사는 유지한다. 배포 후 같은 저장소의 접수 용량 검사는 0.177초였다.

미리보기 해상도는 Gradio와 같은 1024 기본값에 512/768 선택을 제공한다. 원본 인물 식별 좌표를 유지하며 표시 결과만 축소하고 전체 출력 해상도는 바꾸지 않는다. OMP 스레드 설정을 Gradio와 맞추고 FFmpeg 인코더 목록을 반복 조회하던 파서를 재사용한다. 공개 샘플을 1920×1080으로 확대한 입력, 균형 품질·네 종류 마스크에서 엔진 첫 처리 12.231초, 같은 프레임 반복 처리 0.358초였다. 이 수치는 화면 표시까지의 시간은 아니며 첫 모델 로딩과 긴 영상 탐색 시간은 별도로 발생한다.

분석·미리보기 완료 시 같은 소유자·세션·요청 종류의 최신 두 건과 마지막 성공 결과만 보존한다. 진행 중 작업 및 렌더링이 참조하는 미리보기는 보호한다. 사용자 영상과 최종 렌더링 이력은 정리 대상이 아니다. 공개 다인물 예제로 모든 마스크, 두 청크 렌더링, 선택 인물 유지 및 자산 등록 통합 검증을 통과했다.

실제 브라우저의 공개 예제 테스트에서는 사진·대상 자동 선택과 현재 결과만 표시되는 화면을 확인했다. 모델 준비 후 미리보기 해상도를 바꿨을 때 워커 처리 0.38초, 조작부터 새 결과 표시까지 1.103초였다. 작은 공개 예제 측정이므로 장시간 원본의 전체 응답 시간으로 일반화하지 않는다.

## Windows 로컬 Worker

기존 API/Worker Python 환경에 프로젝트 의존성을 설치한다. API의 Pillow 의존성이 추가됐다. FaceFusion 의존성은 별도 전용 Python에 유지한다.

```powershell
python -m pip install -e packages/shared -e apps/api -e workers/media
$env:FACEFUSION_ENABLED = 'true'
$env:FACEFUSION_PATH = 'C:/pinokio/api/facefusion-pinokio.git/facefusion'
$env:FACEFUSION_PYTHON = 'C:/pinokio/api/facefusion-pinokio.git/.env/python.exe'
python -m media_worker.worker
```

API와 Worker의 VIDEO_STORAGE_ROOT는 같아야 한다. 같은 저장소에 기존 Worker가 실행 중이면 해당 Worker의 설정을 갱신하고 재시작한다. Pinokio Gradio 앱 실행은 필요하지 않다. 로컬 검증은 FaceFusion 3.5.4 / ONNX Runtime GPU 1.24.3 / RTX 5070 Ti에서 수행했다.

기본값은 FACEFUSION_ENABLED=false다. Worker가 모델 CRC와 CUDA 실제 추론을 확인한 뒤 capability를 게시한다. 30초 간격 갱신, 120초 이상 heartbeat가 없으면 새 요청을 차단한다. 긴 처리 중에도 heartbeat를 갱신한다. 실패 진단은 저장소의 `.faceswap-probe/*/engine.log` 또는 개별 작업의 `work/faceswap-*/engine.log`에서 확인한다.

## Docker GPU Worker

`docker-compose.faceswap.yml`은 기존 Worker만 선택적으로 확장한다. 기존 API/Web 이미지에는 엔진이 들어가지 않는다. Linux 전용 가상환경에 FaceFusion 3.9.0 commit `6b318a94a64c1e4300e8ed03efbc3151114bc4e6`, ORT GPU 1.24.4 및 CUDA/cuDNN 라이브러리를 설치한다. ORT 1.24.4는 3.9.0 공식 설치기의 CUDA 12 조합이다. OpenCV는 공식 요구사항의 headless 5.0.0.93을 사용한다.

```powershell
$env:FACEFUSION_MODELS_DIR = 'C:/pinokio/api/facefusion-pinokio.git/facefusion/.assets/models'
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.faceswap.yml build
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.faceswap.yml up -d --wait
```

기존 배포에 추가 override 파일이 있으면 같은 파일들도 함께 지정한다. 같은 Compose 프로젝트·기존 볼륨·포트 설정을 유지한다. 위 up 명령은 운영 컨테이너를 교체하므로 실행 중 작업이 없을 때 적용한다. 이번 개발 검증에서는 운영 컨테이너를 교체하지 않았다.

모델 폴더는 읽기 전용 mount다. 모델은 실행 중 자동 설치하지 않는다. 초기 이미지 빌드 시 엔진·CUDA 패키지를 내려받기 때문에 수 GB 공간과 시간이 필요하다. GPU 접근이 가능한 Docker Desktop/WSL2 또는 NVIDIA Container Toolkit 환경이 필요하다.

필수 모델(.onnx 및 대응 .hash): 2dfan4, arcface_w600k_r50, bisenet_resnet_34, fairface, fan_68_5, hyperswap_1a_256, nsfw_1/2/3, xseg_1, yoloface_8n. 엔진 버전이나 모델이 바뀌면 readiness와 미리보기 일치성을 다시 검증해야 한다.

Linux에서는 Bridge와 최종 CLI 각각 ORT preload를 수행한다. 이 초기화를 빼면 최종 CLI가 CPU로 fallback할 수 있다. 오디오 인코더는 기본 탐지 순서에 맡기지 않고 AAC를 명시한다.

## 자동 검증

```powershell
python -m unittest discover -s tests -v
cd apps/web
npm run lint
npm run format:check
npm test
npm run build
```

최종 Python 426개, 웹 26개 통과. 웹 lint/Prettier/TypeScript/Vite 빌드 통과. 신규 10개 Python 테스트는 소유권, revision, 업로드 검증, 요청 중복, 미리보기 실행 조건, 엔진 비활성/stale, LLM 경로 배제, 취소/복구, 용량/삭제 참조와 실제 프로세스 트리 종료를 검증한다. Windows에서는 Worker를 강제로 종료해도 하위 프로세스가 종료됨을 확인했다.

실제 GPU 테스트 스크립트는 유료 공급자를 호출하지 않고 매번 새로운 `data/facefusion-e2e/<uuid>`를 만든다. 기존 사용자 작업을 읽거나 덮어쓰지 않는다. 공개 FaceFusion 예제 입력은 `data/facefusion-fixtures/source.jpg`, `target.mp4`에 준비한다. 출처는 facefusion/facefusion-assets의 examples-3.0.0 릴리스 source.jpg 및 target-240p.mp4다. 모델·입력 다운로드는 테스트에서 수행하지 않는다.

```powershell
# 위 Windows 엔진 환경변수 설정 후
python scripts/verify-faceswap-e2e.py
python scripts/verify-faceswap-e2e.py --multi
```

`--multi`는 두 인물의 좌우 위치가 중간에 바뀌는 2초 입력을 만든다. 처음 오른쪽 인물을 선택하고 나중 왼쪽으로 옮겨진 동일 인물만 합성되는지 미리보기와 최종 프레임에서 검사한다. 모든 단계의 성공, 오디오·길이·디코딩, 결과 자산 등록까지 확인하고 report.json을 남긴다.

검증 기록:

| 환경 | 검증 | 기록 |
| --- | --- | --- |
| Windows native | 1초 단일 인물 API→분석→미리보기→H.264→자산 등록 | data/facefusion-e2e/ede8f06173644e9eb774c3e3d3cc864a/report.json |
| Windows native | 2초 두 인물 위치 교환/타 시점 선택 유지 | data/facefusion-e2e/dae5d89f0cc04eb199473bdfba7e7588/report.json |
| Docker Linux GPU | 2초 다인물, CUDA/NVENC H.264/AAC, 자산 등록 | data/facefusion-e2e/83c86c4b773d48cc80c3944484fbe5ee/report.json |
| Docker Linux GPU 최종 재검증 | 최종 출력 프레임까지 선택 인물 일치, 독립 config 적용 | data/facefusion-e2e/c07c538fd2d44660b4757e9b9db9fefb/report.json |
| 실제 브라우저 | Source/대상 선택, 고품질 768 미리보기, HEVC 전체 처리 완료 | 위 단일 인물 저장소 Job 6ef3641d690746be9fa6e20aa196924c |
| 모바일 viewport | 390×844 단일 열, 파일 선택/얼굴 탐색/설정 배치 | Codex Browser 확인 |

실제 스마트폰 하드웨어 테스트와 장시간 4K/VFR/회전 영상의 동기화·품질 테스트는 수행하지 않았다. 이 기능은 프레임 번호 기준으로 선택하며 시간 기반 정확한 VFR 탐색, 다중 Source, 합성+자막 단일 Job은 후속 범위다.

Linux 컨테이너에서도 신규 테스트 10개 중 9개 통과, Windows 전용 부모 종료 테스트 1개를 skip했다. Linux process group의 취소·timeout 종료는 실제 자손 프로세스로 검증했다. 최종 선택적 Worker 이미지 빌드도 완료했으며 기존 운영 컨테이너는 유지했다.

## 10분 청크 처리 업데이트

전체 합성은 기본 최대 600초의 프레임 구간으로 나뉘어 순차 실행된다. 화면에 현재 청크와 완료 수가 표시된다. 실패/취소 후 재시도하면 입력·엔진·구간계획이 같은 완료 청크를 해시 검증 후 재사용한다. 손상된 청크는 다시 처리한다. 청크를 하나씩 검증한 뒤 추출 PNG를 정리하므로 원본 전체 길이의 PNG를 동시에 보관하지 않는다.

완료된 중간 MP4, 입력 스냅샷, 로그는 보존한다. 재생성 가능한 PNG temp와 joined.mkv만 정리한다. 모든 청크를 연결하고 원본 오디오를 한 번 결합한 뒤, 기존 번인 인코더의 설정으로 최종 인코딩·0 기반 연속 타임스탬프·faststart 처리를 수행한다. 최종 프레임 수가 원본과 다르면 게시하지 않는다.

`FACEFUSION_CHUNK_SECONDS` 기본값은 600, 허용 범위는 1~600이다. 생성 시 API가 Job metadata에 고정하므로 설정을 바꿀 때 API에도 같은 환경변수를 설정한다. 기존 Job은 생성 시 설정으로 재시도한다. 테스트에서는 다음처럼 1초 청크로 경계를 강제해 검증한다.

```powershell
python scripts/verify-faceswap-e2e.py --multi --chunk-seconds 1
```

현재 VFR은 원본과 자막 시간축을 임의로 변경하지 않도록 전체 렌더링 전에 거부한다. CFR 입력을 사용한다. 29.97fps 등 fractional CFR은 지원한다. 고해상도는 10분 청크 하나의 추출 용량도 클 수 있으며 용량 검사는 계속 적용된다. 청크별 엔진 재시작·최종 재인코딩 비용이 추가되므로 처리 속도 향상을 보장하지 않는다.

청크 변경 검증: Python 전체 **433개**, 웹 **26개**, lint/format/build 통과. 신규 청크 테스트 7개는 Windows와 Linux 모두 통과했다. 10분 범위 계산, 무누락/무중복, 실패 후 완료 청크 재사용, 변조 청크 재처리, PNG 정리, 오디오 연결, 무음 29.97fps 전 프레임 PTS 연속성을 확인한다.

실제 Docker GPU에서는 2초 다인물 영상을 1초씩 두 청크로 나눠 처리했다. 두 번째 청크 밖에 있는 첫 프레임의 기준 인물을 유지했고, 합성·연결·최종 인코딩·자산 등록까지 통과했다. 기록: `data/facefusion-e2e/3cca290aa02f4a4caa3f2934488d28d0/report.json`. Windows GPU에서도 동일 두 청크의 렌더링과 최종 인코딩을 완료하고 얼굴 영역이 미리보기와 일치함을 확인했다. 실제 장시간 10분 청크 부하 테스트는 별도 범위다.

Windows 최종 통합 기록: `data/facefusion-e2e/572a56cfb8c14b9489a20941669543c0/report.json`. 오디오 지연 0.4초를 가진 별도 합성 입력으로 시작부 무음 보존과 두 청크 경계의 연속 파형도 검사했다.
