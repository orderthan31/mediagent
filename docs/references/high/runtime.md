# 리뉴얼 실행·저장 계약

## 목적

격리 CPU 경로의 실제 책임·재현 진입점과 운영 전환 경계를 관리한다.

## 현재 상태

검증 업로드·불변 workflow/티켓·PostgreSQL 상태·독립 CPU 프로세스·로컬/S3-compatible CAS·검수/승인/취소/복구·WebM과 이중 다운로드를 구현했다. renewal 관리자 경계와 실제 로컬 CPU fleet에 이어 opt-in RabbitMQ adapter·독립 수신기·결과 제어기와 공통 이미지 build graph를 추가했다. SDK/채널 대역과 실제 CPU·S3·PG를 격리 검증했으며 실제 RabbitMQ 서버·컨테이너 제어·MinIO 제품·다중 머신·GPU/provider·운영 전환은 미검증이다.

## 주요 내용

### 실행·데이터 보호

- API는 명시 DB/콘텐츠 저장소만 받는다. DSN fallback·startup migration·queue scan·실모델 import/call이 없다.
- 작업 snapshot과 정의 revision은 불변이며 동의는 현재 입력/설정/검수와 결속한다. 동의 저장·실행 요청·사람 검수 저장/확정을 분리한다.
- DB delivery reservation 뒤 지정 명령 하나만 실행한다. 독립 에이전트에는 DB/전체 workflow/후속 노드/세션을 보내지 않는다.
- S3 attempt marker는 조건부 쓰기(If-None-Match)를 사용한다. 완료 receipt가 없는 중복은 결과 불명으로 막고 자동 재실행하지 않는다. 결과 ack는 애플리케이션 DB commit 뒤에만 호출한다.
- 취소·lease 만료·이전 generation 결과는 격리한다. 복구는 새 draft 자식 작업이며 검증된 완료 결과만 재사용하고 새 실행 승인을 요구한다.
- 미지원 모델·Loop/Fallback·추가 입력 binding은 편집 지원과 구분하여 실행 승인을 닫는다.

### 저장소와 WebM

- 원본 상한 256 MiB, chunk 4 MiB. `ContentStore`는 private local CAS, `S3ContentStore`는 기존 bucket의 명시 prefix/owner/CAS를 사용한다.
- S3 adapter는 bucket 생성/나열/삭제·서명 URL 발급을 하지 않는다. 키는 프로세스의 명시 환경변수 이름으로만 읽으며 명령/정의/DB에 raw credential을 넣지 않는다. 원격 HTTPS(테스트 loopback HTTP 예외), 직접 SHA/byte 검증, 불변 참조를 사용한다.
- private cache는 로컬 작업공간일 뿐 정본이 아니다. 앱/에이전트는 공유 볼륨 없이 별도 cache에서 S3 HTTP로 원본/결과를 교환한다.
- 업로드 원본과 처리 결과 원본은 보존한다. 별도 `webm-vp9-opus-v1` 파생본(VP9/Opus, 최대 1280×720)을 생성하고 원본 SHA와 연결한다. 원본을 WebM으로 바꿔 저장하지 않는다.
- `/api/videos/{id}/stream`은 WebM 재생, `/download`는 업로드 원본이다. `stream?download=true`는 WebM 첨부 다운로드다.
- 작업 산출물 endpoint는 결과 원본이며 `/preview`가 WebM이다. 양쪽 `?download=true`는 해당 파일 첨부 다운로드다. 고정 영상 입력 플레이어도 `/preview`를 사용한다.
- WebM 생성 실패 시 원본은 다운로드 가능하며 실패 상태를 보존한다. GET에서 변환하거나 지원 여부를 모르는 원본으로 플레이어를 자동 fallback하지 않는다. 현재 WebM은 bounded CPU 처리이며 장시간 미디어의 비동기 스케줄링은 잔여다.

### renewal 관리자 경계와 명시 CPU fleet

- 일반 사용자 허용 동선은 원본 목록/상세·작업 목록/시작/상세다. 나머지 직접 URL은 차단하고 관리 API는 현재 세션의 관리자 권한을 서버에서 확인한다. 세션 확인/본인 로그아웃은 관리 기능과 구별한다.
- `/api/settings/*`, 계정과 `/api/admin/agents/*`는 관리자용이다. 일반 작업 선택은 별도 `/api/work-entry/{workflows,catalog,inspect,preview,create}`를 사용한다. 관리자 제공 workflow의 출처와 revision은 작업에 불변 저장하며 원본·작업 소유자는 실제 사용자다.
- migration `007_agent_fleet.sql`이 목표 설정/revision·변경 이력·실제 인스턴스와 노드 배정을 저장한다. 운영 DB에 자동 적용하지 않는다.
- `--allow-cpu --manage-cpu`는 private local ContentStore 전용이며 S3/다른 executor와 중복 연결하지 않는다. 서버 시작이나 조회는 프로세스를 켜지 않는다. 관리자 configuration PUT 후 실제 ready handshake를 받은 CPU 프로세스만 준비로 집계한다.
- 종류별 0~8개, 전체 활성/드레인 포함 최대 16개, 인스턴스당 1개로 제한한다. DB 잠금으로 명령을 예약하고 idle 인스턴스의 마지막 배정 시각을 기준으로 분산한다. 중복 controller는 advisory ownership lock으로 차단하며 다른 controller PID를 채택/종료하지 않는다.
- 비활성화·축소는 신규 배정을 막고 이미 예약한 명령을 마친 뒤 종료한다. 자동 작업 검색/소비/재실행은 없다. 자리가 없으면 명시 작업은 대기 상태를 유지하며 후속 명시 호출 또는 향후 scheduler가 필요하다.
- 독립 instance는 private stdin/stdout의 제한 JSON 명령과 owner/CAS 참조만 받는다. DB·웹 세션·provider 키·workflow traversal을 받지 않는다. CPU 결과의 요청 digest와 attempt/generation을 검증한다.
- 연결되지 않은 얼굴교체/모델 실행환경은 미연결로 표시하고 활성화 요청을 거부한다. 실제 얼굴교체 on/off가 구현됐다는 뜻이 아니다. 컨테이너 adapter·health·자원 정책은 별도 잔여다.
- 기본 API는 agent package/Torch/FaceFusion을 설치하지 않는다. `legacy-api`는 기존 paused Compose의 기본 API 호환 target이다. API의 직접 upload/preview FFmpeg는 여전히 남는다. CPU 이미지와 선택 legacy media 이미지 및 CPU Compose profiles는 분리했지만 이미지 빌드·실행은 하지 않았으며 기존 GPU/VAD/얼굴교체 overlay의 API 내 엔진 동작도 호환 수용하지 않았다.

### 선택 RabbitMQ 전송과 공통 이미지

- shared의 `amqp` extra는 `pika==1.4.4`만 추가하며 CPU의 `amqp` extra가 S3/AMQP 의존성을 선택한다. 기본 CPU/API 이미지에는 broker SDK를 설치하지 않고 선택 `amqp`/`broker` target에서만 추가한다. CPU 실행 subprocess에는 broker URL·DB·provider 환경을 넘기지 않는다.
- 설정 JSON은 `namespace`, `url_env`, 선택 `allow_loopback`/`ca_file`만 받는다. URL·비밀번호는 별도 명명된 프로세스 환경변수에만 둔다. 명시 vhost·인증·원격 AMQPS/인증서 검증이 필요하고 plaintext AMQP는 명시 허용한 loopback 테스트에만 한정한다. 연결 오류는 고정 코드로 치환하고 CLI의 Pika 진단 로그는 끈다.
- 연결과 namespace 내 역할별 명령/결과/격리 큐 선언을 분리한다. startup/조회에서 연결·queue declare/scan/consume을 하지 않는다. `declare-topology`만 durable classic 큐·direct exchange·DLX를 생성한다. 기존 운영 큐나 namespace를 재사용하지 않는다. classic topology의 장애·HA 보장은 아직 수용하지 않았다.
- API의 명시 `/run`은 승인된 해당 작업의 outbox만 발행한다. 매 요청이 자기 I/O thread의 새 연결을 사용하며 local fleet/executor와 중복 연결하지 않는다. publisher-confirm·mandatory 확인 전에는 outbox를 발행 완료로 표시하지 않고, 실패 후 동일 attempt를 재전달할 수 있다. 만료된 미발행 명령은 거부한다.
- CPU 수신기는 자신의 역할/owner/artifact/설정만 해석하며 별도 private cache의 S3 CLI로 처리한다. 결과 receipt의 확인 발행 뒤 명령 ACK, 결과 제어기의 DB commit·후속 dispatch 뒤 결과 ACK 순서를 유지한다. receipt/inbox가 완료 중복을 재사용하고 결과 불명/poison은 자동 실행하지 않는다.
- Pika I/O는 소유 thread에서만 수행하고 CPU/DB 처리는 작업 thread로 분리해 heartbeat를 계속 처리한다. prefetch는 1이다. SIGTERM은 신규 수신을 취소하고 진행 중 작업·결과 확인/ACK를 마친다. 연결 실패 시 자동 reconnect·작업 retry는 하지 않는다.
- 현재 명령 TTL은 60초, 기존 node lease는 120초다. 결과 큐에는 TTL을 두지 않는다. 긴 큐 대기·장시간 작업의 lease 갱신, cancel의 원격 실행 중단, DLQ 보관/재처리·재연결·HA와 원격 fleet 제어는 별도 잔여다. 취소/이전 generation/lease 만료 결과의 DB 격리는 유지한다.
- root Dockerfile의 `media-base`가 FFmpeg/FFprobe·폰트를 한 번 선언한다. `agents/cpu`와 `agents/media`는 named build context로 상속하고 API는 같은 파일의 stage를 상속한다. `docker-bake.hcl`이 build graph를 묶는다. Compose의 base helper는 장기 실행 서비스를 제공하지 않으며 역할별 profile은 독립 실행 단위다.
- `agents/cpu/compose.amqp.yaml`은 선택 network transport 레시피다. 명시 private env file·기존 external network·개별 tmpfs cache만 사용하고 공유 원본 bind mount·고정 container_name·Docker socket·broker service·자동 restart를 추가하지 않는다. 동일 역할의 복제는 Compose 실행 관리자의 책임이며 웹 fleet과 자동 연결하지 않는다. 이미지 빌드·컨테이너 자원 한도 수용은 미실행이다.

다음은 배포 승인 후 사용하는 진입점이며 현재 운영에 실행하지 않았다.

```sh
# 공통 base 의존성이 포함된 build graph 조회만 수행한다.
docker buildx bake -f docker-bake.hcl --print api cpu cpu-amqp api-broker legacy-media

# broker 설정은 namespace/url_env만, 실제 값은 별도 private 환경에서 제공한다.
python -m app.broker_server declare-topology --enable-broker --broker-config-env MIDEAGENT_BROKER_CONFIG
mideagent-cpu-amqp --enable-broker --agent analyze --broker-config-env MIDEAGENT_BROKER_CONFIG --object-config-env MIDEAGENT_AGENT_OBJECT_CONFIG
python -m app.broker_server consume-results --enable-broker --broker-config-env MIDEAGENT_BROKER_CONFIG --dsn-env MIDEAGENT_DATABASE_DSN --object-config-env MIDEAGENT_APP_OBJECT_CONFIG
```

API launcher는 `--allow-cpu --object-config-env <app-config> --broker-config-env <broker-config>`를 선택할 수 있다. `--agent-config-env`/`--manage-cpu`와 동시 사용하지 않으며 기존 `--dsn-env`/`--origin`을 명시한다. 브로커는 API startup이 아니라 명시 작업 dispatch 때 연결한다.

### 기존 독립 CPU 진입점

Python 3.12+와 FFmpeg/FFprobe가 필요하다. `packages/shared[postgres,models,objects]`, `apps/api`, `agents/cpu`를 격리 환경에 설치한다. CPU 에이전트 자체는 PostgreSQL 패키지나 API 연결 없이 동작한다.

- `mideagent-analyze`, `mideagent-extract-audio`, `mideagent-generate-subtitle`, `mideagent-encode`, `mideagent-validate-video`: 각 고정 역할의 JSON stdin/stdout 명령. `--input-root`/`--output-root`는 명시 private root다.
- `mideagent-object-agent --agent <role> --owner <owner-id> --config-env <explicit-name>`: 원격 CAS를 사용하는 단일 명령. 설정은 endpoint/bucket/region/prefix/cache_root와 access_key_env/secret_key_env 이름만 포함한다.
- `python -m app.renewal_server --dsn-env <name> --origin http://127.0.0.1:<port> --content-root <root> --allow-cpu`: 로컬 전용 launcher.
- 같은 launcher의 `--manage-cpu`를 명시해야 관리자 상세에서 로컬 CPU fleet을 조작할 수 있다. CPU package를 같은 승인된 환경에 설치해야 하며 이 옵션 없이 조작 가능으로 표시하지 않는다. 실제 운영에 이 명령을 자동 적용하지 않는다.
- S3 실행은 content-root 대신 `--object-config-env <app-config-name> --agent-config-env <agent-config-name>`을 사용한다. 앱과 agent config의 private cache_root를 다르게 지정한다. 이 launcher는 공개 production server가 아니다.
- `agents/media/media_agent`는 기존 API 의존성을 위한 legacy 호환 코드다. CLI는 `--allow-legacy-queue` 없이는 queue/cleanup을 실행하지 않으며 이 플래그의 존재가 현재 운영 실행 승인은 아니다. 기존 WORKER_* 환경변수·과거 DB/protocol 식별자는 데이터 호환성을 위해 임의 변경하지 않는다.

### 검증과 남은 부채

- 전체 renewal 격리 회귀는 72개 통과(AMQP 관련 11개와 기존 네 브라우저 경로, skip 없음), web 단위 테스트는 44개 통과했고 production build도 통과했다. AMQP는 실제 Pika property/실패 loopback handshake, 채널 대역의 confirm/ACK·heartbeat/drain·poison, 실제 합성 CPU/S3/PG의 재전달·결과 채택·다음 단계 dispatch를 검증한 것이며 실제 브로커 수용은 아니다. 존재하지 않는 과거 Chrome 경로로 실패한 브라우저 세 개는 기존 설치 Chromium을 명시해 전체 재검증했다.
- 실제 CPU 기동 실패·종료, ready handshake 후 DB 기록 실패의 기존 검증도 유지한다. 변경 Python lint/format, 타입/build, Compose 역할 profile 11개와 Bake graph 정적 구성을 확인했다. Compose/Bake 검사는 이미지 빌드·스택 실행이 아니다.
- 테스트는 명시 disposable PostgreSQL의 임의 schema와 합성 미디어만 사용한다. S3 테스트는 임시 loopback 프로토콜 에뮬레이터이며 종료 후 서버를 닫는다.
- 코덱 지원 Chrome만 사용하는 우회와 구분한다. H.264/AAC 미지원 Chromium에서도 WebM 원본/산출물 재생, 재생 시간 진행·영상 크기, 원본/WebM 실제 다운로드와 SHA를 확인한다. FHD/cover/unfolded는 브라우저 에뮬레이션이지 실기기 수용이 아니다.
- 현재 legacy suite는 27 failed / 558 passed / 1 skipped이며 직전 exact SHA `ae057f643ebf8bb6c93c1088cfe9ebc4140dfa24`의 기존 검증 결과와 실패 식별자 집합이 동일하다. 그 직전 검증도 `6035f763e896f23cccbaf249a5c13604748f82ff` baseline과 대조했다. 주요 부채는 과거 fixture/실행 승인 계약, provider mock 설정과 download test 호환성이다. 전체 legacy suite는 all-green이 아니다.
- 전체 web lint는 기존 오류 80개, format은 기존 파일 네 개 부채가 있다. 에이전트 목록의 기존 컨벤션 오류 7개를 함께 정리했으며 변경 runtime 화면 lint·web 단위 테스트·타입/build 검사와 분리한다. 검사를 삭제하거나 실행 승인 보호를 낮추지 않는다.
- 실제 제품/다중 머신에서는 최소권한 bucket prefix 정책, 인증/허용 명령 범위, 브로커 topology, 장애/중복/취소 및 성능을 다시 수용해야 한다. 현재 S3 fixture는 IAM/실 MinIO 적합성을 증명하지 않는다.

## 미확정 사항

실제 제품/배포 분할·인증/브로커·GPU/실모델·대용량 비동기 실행은 별도 단계다.

## 관련 문서

- [구조](../../plans/architect.md) · [태스크](../../plans/tasks.md) · [격리 테스트](../../../tests/renewal/README.md) · [배포 경계](../../rules/deploy.md)
