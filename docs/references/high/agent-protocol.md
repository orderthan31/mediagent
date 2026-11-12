# 에이전트 MQ 요청·응답 계약

## 목적

구형 파일 큐·고정 workflow를 대신하는 controller → 역할 큐 → 독립 CPU agent → 결과 controller의 wire 계약이다. 에이전트는 다음 노드나 workflow DB를 해석하지 않는다.

## 정본

- `packages/shared/video_service/agent_protocol.py`: 버전·역할·메시지 상한과 schema 생성기.
- 같은 패키지의 `contracts/agent.command.v1.schema.json`, `agent.result.v1.schema.json`: 배포 패키지에도 포함되는 JSON Schema 2020-12.
- `rabbitmq_transport.validate_command`, `validate_result`, `decode`: 수신 시 실제 검사. schema만으로 표현하지 못하는 key/SHA 일치, 정확한 응답 포트·자료 유형과 요청 digest·attempt 결속을 추가 검사한다.
- 개별 역할의 입출력·옵션은 `node_contracts.py`에서 공유한다. 아래 GPU/model v2는 별도 큐·codec·consumer이며 CPU v1으로 우회하지 않는다.

## 요청

AMQP `type=agent.command.v1`, `content_type=application/json`, `content_encoding=utf-8`. `message_id=attempt_id`, `correlation_id=run_id`, 본문 상한 131072 bytes다.

본문은 정확히 `{version, owner, command}`이며 `version=1`이다. `owner`, `run_id`, `attempt_id`는 소문자 32자리 hex다. command 필드는 다음으로 고정한다.

- `protocol_version`: 정수 1. bool은 허용하지 않는다.
- `run_id`, `attempt_id`, `generation`: 실행·시도·취소 세대를 결속한다. generation은 1 이상 정수다.
- `agent`: `{id, revision}`. revision은 문자열 `"1"`이다.
- `inputs`: 역할별 입력 포트 → `{storage_key, sha256, bytes, type}`.
- `options`: 해당 역할의 허용 enum만 받는다. 모델 키·provider 설정·임의 실행 명령은 받지 않는다.

원격 artifact는 `storage_key=blobs/<sha256>`, 64자리 소문자 SHA-256, `1..268435456` bytes다. owner prefix는 object-store adapter에서 적용한다. 로컬 호스트의 절대 경로·원본 바이트·서명 URL·웹 세션·credential은 메시지에 넣지 않는다.

역할별 요청/응답 포트:

- `analyze`: `video:video` → `metadata:media_metadata`.
- `extract_audio`: `video:video` → `audio:audio`.
- `preprocess_audio` CPU v1: `audio:audio` → `audio:audio`, `timeline:timeline_map`. `audio_filter=off`, `vad_mode=off` 정규화만 실행한다. NVIDIA 선택은 GPU v2다.
- `generate_subtitle`: `transcript:transcript` → `subtitles:subtitle`.
- `encode`: `video:video`, 선택 `subtitles:subtitle` → `video:video`. `subtitle_mode=none`은 자막 입력을 금지하고 burn/soft는 필수로 요구한다.
- `validate_video`: `video:video` → `report:validation_report`.

## 응답

AMQP `type=agent.result.v1`. 요청 본문에 `result` 하나를 추가하며 원래 command를 그대로 돌려준다. 응답은 다음 필드만 허용한다.

- 원래 `protocol_version`, `run_id`, `attempt_id`, `generation`, `agent`.
- `request_sha256`: 정렬된 UTF-8 JSON command의 SHA-256. `cpu_agents.canonical`이 공백 없이 직렬화하며 NaN은 금지한다.
- `status`: `completed` 또는 `failed`.
- `transport`: `s3_subprocess`.
- `outputs`: 완료 시 해당 역할의 정확한 출력 포트와 원격 CAS 참조. 임의 포트·자료 유형·host path는 거부한다.
- `error`: 실패 때만 `{code, retryable}`. code는 길이 제한된 고정 식별자이고 retryable은 bool이다. 실패 outputs는 빈 객체다. raw SDK 예외·stderr·credential 추가 필드는 거부한다.

`completed`는 에이전트 receipt이지 DB 채택 완료나 전체 workflow 완료가 아니다. controller가 현재 owner·lease·attempt·generation·요청 hash를 확인하고 DB transaction을 commit한 뒤 결과 ACK한다. 취소·만료·이전 시도는 격리한다.

## 전달·실행 경계

- publisher confirm은 브로커 수신 확인이며 작업 완료가 아니다.
- 명령 ACK는 CPU 처리·CAS receipt·결과 confirm 뒤, 결과 ACK는 controller DB commit 뒤다.
- prefetch 1, 수동 ACK, SIGTERM 신규 수신 차단 후 drain을 사용한다.
- 완료 receipt는 중복 전달에 재사용한다. 결과 불명 시 자동 재실행하지 않는다.
- 이 계약은 SDK/채널 seam 및 실제 격리 CPU/S3/PG로 검증한다. 실제 RabbitMQ 서버·다중 consumer·GPU 실행·운영 장애 수용과 구분한다.

## 명시 고정 offline engine v2

- `engine_protocol.py`, `engine_transport.py`, `engine_service.py`, `engine_object_agent.py`가 model/GPU 경계를 소유한다. CPU media v1 codec/역할 목록을 확장해서 GPU를 받아들이지 않는다.
- AMQP type은 `agent.engine.command.v2`/`agent.engine.result.v2`다. 별도 namespace의 `commands.v2`/`results.v2`/`dead.v2`, 역할별 `<namespace>.<role>.v2` 큐를 사용한다. vhost/인증·TLS를 분리된 역할 계정에 결속한다.
- 외부 envelope는 `{version:1,owner,command[,result]}`다. command는 CPU 형태에 `runtime`을 추가하고 `protocol_version=2`, `agent={id,family,revision}`을 사용한다. revision은 아래 descriptor의 canonical SHA-256이며 임의 host path/명령/credential은 받지 않는다.
- descriptor 필드는 정확히 `{role,family,engine,model_sha256,source_language,target_language}`다. `engine_runtime_revisions`/head의 등록·가용성 CAS를 사용하고 작업 생성 시 pin을 snapshot에 고정한다. claim 및 실제 outbox 발행 직전 current pin/가용성을 재검사한다. 후자는 head shared lock 안에서 확인 발행까지 처리한다. 완료된 모델 결과의 바이트는 후속 호출과 분리 보존한다.
- 이 테이블은 **고정 물리 엔진 식별**이다. 일반 owner-scoped 등록 모델/provider/credential 선택을 대신하는 저장소나 환경 fallback이 아니다. `model_ref`를 무시하고 로컬 모델로 대체하지 않으며 미연결 참조는 승인 차단한다.
- `transcribe`/family=model: `audio`, `timeline` → `transcript`. 명시 tiny.en/CPU int8/영어·16kHz mono PCM16·300초 이하 입력만 지원한다. 실제 전사 구간을 원본 시계로 복원한다.
- `translate`/family=model: `transcript` → `transcript`. 명시 OPUS-MT en→de/CPU int8만 지원하며 구간 시간을 보존한다. 다른 언어나 free/외부 provider로 자동 변경하지 않는다.
- `preprocess_audio`/family=gpu: 명시 `vad_mode=nvidia`, `audio_filter=off`; 실제 Marblenet CUDA → packed WAV/clock. clock v2는 `{version:2,audio_sha256,source_sha256,spans,engine}`이며 GPU 보고서·packed audio hash를 보존한다. 전사 시 audio hash/길이와 clock 단조성을 확인한다. graph의 audio/timeline은 같은 생산자여야 한다.
- `faceswap`/family=gpu: `video`, `session`, `preview` → `video`. 세션·미리보기·영상·설정·engine fingerprint·동일 owner CAS를 결속한다. 실제 CUDA swapper 세션과 별도 전체 render를 실행한다. 현재 짧은 합법적 self-swap fixture RPC를 수용했으며 **제품 FaceSession/preview 생성·승인/binding API는 미제공**이다. 이 RPC를 제품 workflow 완료나 임의 승인으로 확대하지 않는다.
- 응답은 CPU와 같은 identity/request SHA/status/정확한 outputs/error 경계를 갖되 `protocol_version=2`, `transport=s3_engine`이다. CPU의 per-command subprocess와 engine worker 내부 모델 실행을 같은 provenance로 기록하지 않는다. 숫자형 version/generation에 bool/float를 허용하지 않고 추가 응답/credential 필드는 거부한다.
- 모델의 로컬 artifact 경로/별도 FaceFusion interpreter는 role 전용 private locator에만 있다. 입력 메시지의 model pin이 실제 파일 hash/배포 descriptor와 다르면 실행을 거절한다. runtime이 외부 모델을 다운로드하거나 provider/key를 resolve하지 않는다.
- 같은 S3 claim/result receipt·prefetch1·I/O-thread confirm/ACK·SIGTERM drain을 사용한다. 모델/GPU 역할의 실제 새 attempt TLS MQ 수용과 cached receipt 재전달 검증은 구분한다. 다중 host/장시간 lease 갱신·HA·일반 모델/언어/품질 수용은 미완료다.

## 관련 문서

- [실행·저장 계약](runtime.md)
- [격리 검증](../../../tests/renewal/README.md)


## 얼굴 합성 전용 v3 — source 계약 / 운영 활성화 아님

- `face_protocol.py`의 `OPERATIONS`와 exact validators가 정본이다. `face_analyze_source`, `face_analyze_reference`, `face_preview`, `face_render`는 각각 기존 FaceFusion CLI의 명시적 동작 하나만 호출한다. runtime role/기존 engine exchange routing은 `faceswap`이며 CPU v1으로 우회하지 않는다. AMQP type은 `agent.engine.command.v3` / `agent.engine.result.v3`, command `protocol_version=3`이다. 다른 role의 v3나 v2 fallback은 거절한다.
- 신규 immutable runtime descriptor에만 `face_protocol: 3`을 추가한다. 기존 descriptor 여섯 필드, 기존 v2 메시지·session-v1·combined preview/render는 그대로다. 기존 `tools/gpu/facefusion.py` 바이트/fingerprint도 보존한다. 새 adapter가 analyze_*용 비활성 CLI parser 인덱스를 채울 뿐 session/선택 결과를 만들지 않는다. 실제 선택은 후보가 하나여도 사용자 입력이 있어야 한다. 이 descriptor 표시는 프로토콜 지원 선언이며 실제 CUDA 실행 성공의 증거가 아니다.
- 신규 `face_workflow_v1` 공개 정의는 얼굴 합성 에이전트 하나와 `photo:image` 입력을 사용한다. 실제 대상 영상은 normal Create의 등록 asset/FK다. 내부 도구는 두 분석 → `face_select` → preview → `face_confirm_preview` → render → `validate_video`다. 두 대기는 application-owned이며 공개 review/tool 노드가 아니다. 최종 publication은 자기 소유 영상/report만 포함한다.
- command의 공통 여덟 필드와 정확한 role별 input ports를 유지하고 `options.context`에 job/snapshot/goal/generation, 사진·영상 asset/custodian/원본 ref, 출력 owner, settings/runtime revision·SHA, 기준 프레임·distance·preset·codec 및 policy id를 결속한다. snapshot SHA는 snapshot 저장 후 command에서 채우므로 자기 참조 digest를 만들지 않는다. preview/render에는 exact server selection과 accepted predecessor command/result를 추가하고 render에는 exact approval을 추가한다.
- `face_analysis` / `face_preview` JSON v1은 operation, context/request digest, run/attempt, 실제 후보 position/bbox/image ref·크기를 포함한다. 영상 분석/preview는 실제 frame/fps/count를 포함하고 preview는 matched_faces와 선택 digest를 추가한다. 이미지/후보는 실제 CLI 출력에서만 채택하며 `approved` 필드가 없다. 구조 JSON 64KiB, 사진/이미지 10MiB·24M pixels, 후보 128개, 대상 영상 30초·1280×720·256MiB를 넘지 않는다. renderer는 별도 preview를 호출하지 않는다.
- `face_session` JSON v2는 context digest, 두 accepted analysis SHA, 사용자 source/target 인덱스, review revision, server acceptance/expiry를 가진다. `face_approval` JSON v1은 context/selection/accepted preview SHA, review id/revision과 server acceptance/expiry를 가진다. 신규 `face_operation_policy`는 네 GPU operation 각각 최대 한 번·각 120초, analysis/session/preview/approval의 1800초 창을 고정한다. 시각은 client가 아니라 SQL accepted completion/DB now에서 얻는다. 이 새 profile 기본값은 기존 세션/유료 LLM 예산에 적용하지 않는다.
- 신뢰 근거는 THIS job/generation의 committed completed node_runs, 정확한 request/result, TicketArtifacts와 confirmed review다. publisher는 off-lock preflight에서 이를 재검증하고 worker는 read-only `read_attempt_result`로 immutable claim/result와 출력 bytes를 비교한다. CAS JSON/SHA만으로 SQL acceptance나 사용자 확인을 인정하지 않는다. worker에는 SQL/승인 키가 없다. 새 face source 경계에서만 frozen origin과 정확히 일치하는 foreign photo를 읽으며 producer image/crop 출력에는 source_owner_id를 허용하지 않는다.
- inspection/plan/GET는 claim/Put/native subprocess를 수행하지 않는다. receipt/manifest staging은 job lock 밖에서 하고, 기존 job → review lock 순서 및 run-frontier/context/CAS revision을 다시 검사한 뒤 SQL에서 채택한다. staging 뒤 취소/충돌은 authority 없는 orphan만 남긴다. 만료·실패·불명·late result는 자동 분석/preview/retry로 해결하지 않는다. 이미 완료된 render는 preview 만료로 소급 변경하지 않는다. 다른 job으로 face receipt를 복구 재사용하지 않는다.
- 현재 설치된 v2 descriptor/host/image를 v3로 간주하지 않는다. 새 runtime revision과 실제 v3 producer/transport binding, 기존 SQL/S3 writer 신뢰·권한 및 실제 GPU/FaceFusion 동작의 운영 확인은 별도 held다. 이번 검증은 synthetic SQL/CAS/child/React fixture이며 제품 분석·preview·render 성공 증거가 아니다.
