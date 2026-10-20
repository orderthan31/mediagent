# 에이전트 MQ 요청·응답 계약

## 목적

구형 파일 큐·고정 workflow를 대신하는 controller → 역할 큐 → 독립 CPU agent → 결과 controller의 wire 계약이다. 에이전트는 다음 노드나 workflow DB를 해석하지 않는다.

## 정본

- `packages/shared/video_service/agent_protocol.py`: 버전·역할·메시지 상한과 schema 생성기.
- 같은 패키지의 `contracts/agent.command.v1.schema.json`, `agent.result.v1.schema.json`: 배포 패키지에도 포함되는 JSON Schema 2020-12.
- `rabbitmq_transport.validate_command`, `validate_result`, `decode`: 수신 시 실제 검사. schema만으로 표현하지 못하는 key/SHA 일치, 정확한 응답 포트·자료 유형과 요청 digest·attempt 결속을 추가 검사한다.
- 개별 역할의 입출력·옵션은 `node_contracts.py`에서 공유한다. 선택 GPU 엔진은 현재 MQ 소비자 목록에 등록하지 않으며 CPU 큐로 우회하지 않는다.

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

## 관련 문서

- [실행·저장 계약](runtime.md)
- [격리 검증](../../../tests/renewal/README.md)
