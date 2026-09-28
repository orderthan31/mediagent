# 얼굴 합성 실행·검증 가이드

2026-09-28 구현. [통합 명세](facefusion-integration-plan.md)와 함께 읽는다.

## 사용법

영상 보관함 → 영상 상세 → **얼굴 합성** → 새 설정 → Source JPEG/PNG 등록 → Source 얼굴 찾기/선택 → 기준 프레임 얼굴 찾기/선택 → 미리보기 → 전체 영상 처리 순서다.

미리보기의 비교 슬라이더와 이전 결과를 확인할 수 있다. 설정을 바꾸거나 엔진을 업데이트하면 새 미리보기가 필요하다. 완료 결과는 기존 다운로드 메뉴 및 **새 원본으로 등록**으로 이어진다. 합성 작업 상세에는 합성 취소/재시도와 결과 영상이 표시된다.

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

`docker-compose.faceswap.yml`은 기존 Worker만 선택적으로 확장한다. 기존 API/Web 이미지에는 엔진이 들어가지 않는다. Linux 전용 가상환경에 FaceFusion 3.5.4 commit `a498f3d6182e318fdb0d9ec0f597f1a15b7a559d`, ORT GPU 1.24.4 및 CUDA/cuDNN 라이브러리를 설치한다. 1.24.3은 사용 중인 Linux Python 3.12에 해당 wheel이 없어 검증된 1.24.4를 사용한다.

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
