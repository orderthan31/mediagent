# FaceFusion 로컬 CLI 사전 점검

검증일: 2026-09-28. 개발 브랜치: `feat/faceswap`.

이 문서는 구현 전 사전 점검 기록이다. 이후 완료한 실제 인물·다인물·Docker·웹 통합 검증은 [얼굴 합성 실행·검증 가이드](faceswap.md)를 참고한다.

## 결론

Windows 호스트에 설치된 FaceFusion 3.5.4의 CLI, CUDA 추론, 짧은 영상 처리와 NVENC 출력은 정상 동작한다. 실제 인물 교체·다인물 기준 선택·다른 시점 미리보기·장시간 취소는 아직 검증하지 않았다. 이 점검은 통합 기획서 Phase 0의 환경 확인에 해당하며 전체 Phase 0 완료를 의미하지 않는다.

## 실행 환경

| 항목 | 확인값 |
| --- | --- |
| 엔진 | `C:\pinokio\api\facefusion-pinokio.git\facefusion` |
| Python | `C:\pinokio\api\facefusion-pinokio.git\.env\python.exe` |
| Python 버전 | 3.12.13, conda-forge |
| FaceFusion | 3.5.4 |
| 엔진 commit | `a498f3d6182e318fdb0d9ec0f597f1a15b7a559d` |
| ONNX Runtime | 1.24.3 |
| GPU | NVIDIA GeForce RTX 5070 Ti, 16303 MiB |
| NVIDIA 드라이버 | 591.86 |
| ORT 등록 provider | TensorRT / CUDA / CPU |
| 실제 추론 확인 | CUDA. TensorRT 실행은 시험하지 않음 |

Pinokio 제어 서버 `127.0.0.1:42000`은 연결 거부 상태였다. 사용자가 CLI 점검을 요청했으므로 설치된 전용 Python을 직접 실행했다. Pinokio launcher의 `run.js`에는 엔진 `git reset --hard`가 포함되어 있어 launcher는 실행하지 않았다. 엔진 설치·업데이트·소스 변경은 수행하지 않았다.

샌드박스에서는 존재하는 FFmpeg가 실행 가능 파일로 인식되지 않아 CLI가 `ffmpeg is not installed`로 실패했다. 전용 환경 PATH를 사용하고 정상 실행 권한에서 재검사하면 버전/도움말/영상 처리 모두 통과한다. 새로 FFmpeg를 설치해서 해결한 것이 아니다.

## 실제 실행 결과

| 검사 | 결과 |
| --- | --- |
| `facefusion.py --version` | exit 0, `FaceFusion 3.5.4` |
| `facefusion.py headless-run --help` | exit 0 |
| 이번 검사에 필요한 기존 모델 11종 CRC32 | 모두 설치된 `.hash`와 일치 |
| `hyperswap_1a_256.onnx` CUDA session | 첫 provider가 CUDA임을 확인 |
| 합성 배열 입력 추론 | 출력 `(1,3,256,256)`, `(1,1,256,256)`, 모든 값 finite |
| 1초 합성 영상 CLI 처리 | exit 0, 320×240, 5fps, 5 frames |
| `face_debugger` + CUDA | YOLO face 모델 로딩과 프레임 처리 성공 |
| `h264_nvenc` 출력 | MP4 생성, 오디오 복원 성공 |
| FFprobe 결과 검사 | 영상·음성 stream 존재, duration 약 1초 |

전체 영상 CLI 호출은 약 10.56초, FaceFusion 자체 처리 로그는 약 8.77초였다. 모델 warm-up·내용·해상도가 다르므로 실제 얼굴 합성 속도로 해석하지 않는다. 회색 영상과 테스트 tone을 사용했고 사용자 영상을 가공하지 않았다.

`face_debugger` 검사는 얼굴 교체를 수행하지 않는다. 별도 Hyperswap 추론도 합성 배열을 사용하므로, 두 검사가 통과했다고 실제 Source→Target 인물 합성 검증 완료로 간주하지 않는다.

## 3.5.4에서 확인한 구현 제약

- `face_selector.select_faces()`는 기준 얼굴을 `sort_and_filter_faces()`한 뒤 `reference_face_position`으로 선택한다. bbox 응답의 임의 배열 index를 그대로 사용하면 안 된다.
- reference matching은 정규화된 거리와 임계값을 비교하며 작은 임계값이 더 엄격하다. UI 슬라이더 방향을 이에 맞춰야 한다.
- `workflows/image_to_image.py`는 target 이미지에서 reference frame도 만든다. 이미지 CLI만 호출해서 다른 영상 시점의 기준 인물을 지정할 수 있다고 가정하면 안 된다.
- `workflows/image_to_video.py`는 영상의 `reference_frame_number`에서 기준 프레임을 읽는다. Bridge는 이 기준 선택과 미리보기 처리의 일치를 보장해야 한다.
- `face_swapper/core.py`의 Source 추출은 각 Source 이미지의 큰 얼굴부터 선택한다. 사용자가 여러 Source 얼굴 중 하나를 선택하게 하려면 검증된 crop/Bridge 방식으로 입력을 고정해야 한다.
- CLI에는 reference frame/position/distance, face-selector-order, CUDA, NVENC가 있다. `face-tracker-score` 옵션은 현재 도움말에 없다.
- 이번 모델 목록에는 `hyperswap_1a_256`이 있지만 face enhancer 모델은 없었다. Quality preset을 지원 완료로 표시하지 않는다.
- Windows 설치 환경 검증이다. 현재 서비스의 Linux Docker Worker에서 이 Windows Python 경로를 실행할 수는 없다. Docker용 엔진 환경 통합은 별도 단계다.

## 재현

[진단 스크립트](../scripts/check-facefusion.py)는 출력 폴더를 새로 생성하며 기존 폴더를 덮어쓰지 않는다. 현재 설치 버전 3.5.4에 맞춘 진단이고, 모델이 없거나 hash가 다르면 설치/수정 없이 실패한다. 엔진 Python으로 실행해야 한다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\pinokio\api\facefusion-pinokio.git\.env\python.exe' -B -u `
  scripts/check-facefusion.py `
  --engine 'C:\pinokio\api\facefusion-pinokio.git\facefusion' `
  --output 'data/facefusion-diagnostics/new-run'
```

이번 실행 기록: `data/facefusion-diagnostics/20260928-cli/`. `report.json`, 전체 CLI 도움말, CUDA 로그, 처리 로그, FFprobe 결과 및 합성 테스트 영상을 보존했다. `data/`는 Git에서 제외된다.

## 브랜치 기준점

기존 전사 공급자 변경은 `165e600` (`feat(stt): support configurable transcription providers and fallback`)으로 별도 커밋했다. 검증: Python 416개·웹 26개 테스트, ESLint, Prettier 검사, TypeScript/Vite 빌드 통과. Python 설정 파일 테스트와 Vite subprocess는 샌드박스 제한으로 정상 권한 재실행이 필요했다. 유료 공급자 실제 호출 검증을 의미하지 않는다.

다음 구현 순서는 다인물 테스트 입력으로 reference/미리보기 Bridge 검증 → Session/Request 저장 계약 → 기존 Worker/API/UI 통합이다.
