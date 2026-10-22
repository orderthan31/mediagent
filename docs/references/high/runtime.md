# 리뉴얼 실행·저장 계약

## 목적

격리 CPU 경로의 실제 책임·재현 진입점과 운영 전환 경계를 관리한다.

## 현재 상태

검증 업로드·불변 workflow/티켓·PostgreSQL 상태·독립 CPU 프로세스·로컬/S3-compatible CAS·검수/승인/취소/복구·WebM과 이중 다운로드를 구현했다. renewal 관리자 경계와 실제 로컬 CPU fleet에 이어 opt-in RabbitMQ adapter·독립 수신기·결과 제어기와 공통 이미지 build graph를 추가했다. SDK/채널 대역과 실제 격리 TLS RabbitMQ 4.2.9·source-pinned MinIO·독립 CPU 두 process·결과 소비 process·PG의 합성 영상 완료/ACK/DLQ/결과 SHA를 구분해 수용했다. 컨테이너 fleet 제어·다중 머신·GPU/provider·운영 전환은 미검증이다.

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
- S3 adapter는 bucket 생성/나열/삭제·서명 URL 발급을 하지 않는다. 신규 배포는 명시 private credential/config 파일을 직접 읽으며 기존 환경변수 이름 CLI는 infrastructure 호환용이다. 별도 operator만 명시 빈 bucket을 초기화한다. 명령/정의/DB에 raw transport credential을 넣지 않는다. 원격 HTTPS(테스트 loopback HTTP 예외), 직접 SHA/byte 검증, 불변 참조를 사용한다.
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
- 기본 API는 agent package/Torch/FaceFusion을 설치하지 않는다. 구형 API 호환 target과 GPU/VAD overlays는 제거했다. API 직접 upload/preview FFmpeg는 남으며 CPU/GPU 선택 이미지는 분리한다. 이미지 빌드·GPU engine 설치·컨테이너 수용은 미실행이다.

### 선택 RabbitMQ 전송과 공통 이미지

- shared의 `amqp` extra는 `pika==1.4.4`만 추가하며 CPU의 `amqp` extra가 S3/AMQP 의존성을 선택한다. 기본 CPU/API 이미지에는 broker SDK를 설치하지 않고 선택 `amqp`/`broker` target에서만 추가한다. CPU 실행 subprocess에는 broker URL·DB·provider 환경을 넘기지 않는다.
- 설정 JSON은 `namespace`, `url_env`, 선택 `allow_loopback`/`ca_file`만 받는다. URL·비밀번호는 별도 명명된 프로세스 환경변수에만 둔다. 명시 vhost·인증·원격 AMQPS/인증서 검증이 필요하고 plaintext AMQP는 명시 허용한 loopback 테스트에만 한정한다. 연결 오류는 고정 코드로 치환하고 CLI의 Pika 진단 로그는 끈다.
- 연결과 namespace 내 역할별 명령/결과/격리 큐 선언을 분리한다. startup/조회에서 연결·queue declare/scan/consume을 하지 않는다. `declare-topology`만 durable classic 큐·direct exchange·DLX를 생성한다. 기존 운영 큐나 namespace를 재사용하지 않는다. classic topology의 장애·HA 보장은 아직 수용하지 않았다.
- API의 명시 `/run`은 승인된 해당 작업의 outbox만 발행한다. 매 요청이 자기 I/O thread의 새 연결을 사용하며 local fleet/executor와 중복 연결하지 않는다. publisher-confirm·mandatory 확인 전에는 outbox를 발행 완료로 표시하지 않고, 실패 후 동일 attempt를 재전달할 수 있다. 만료된 미발행 명령은 거부한다.
- CPU 수신기는 자신의 역할/owner/artifact/설정만 해석하며 별도 private cache의 S3 CLI로 처리한다. 결과 receipt의 확인 발행 뒤 명령 ACK, 결과 제어기의 DB commit·후속 dispatch 뒤 결과 ACK 순서를 유지한다. receipt/inbox가 완료 중복을 재사용하고 결과 불명/poison은 자동 실행하지 않는다.
- Pika I/O는 소유 thread에서만 수행하고 CPU/DB 처리는 작업 thread로 분리해 heartbeat를 계속 처리한다. prefetch는 1이다. SIGTERM은 신규 수신을 취소하고 진행 중 작업·결과 확인/ACK를 마친다. 연결 실패 시 자동 reconnect·작업 retry는 하지 않는다.
- 현재 명령 TTL은 60초, 기존 node lease는 120초다. 결과 큐에는 TTL을 두지 않는다. 긴 큐 대기·장시간 작업의 lease 갱신, cancel의 원격 실행 중단, DLQ 보관/재처리·재연결·HA와 원격 fleet 제어는 별도 잔여다. 취소/이전 generation/lease 만료 결과의 DB 격리는 유지한다.
- root Dockerfile의 `media-base`가 FFmpeg/FFprobe·폰트를 한 번 선언한다. `agents/cpu`와 `agents/gpu`는 named build context로 상속하고 API는 같은 파일의 stage를 상속한다. `docker-bake.hcl`이 build graph를 묶는다. Compose의 base helper는 장기 실행 서비스를 제공하지 않으며 역할별 profile은 독립 실행 단위다.
- `agents/cpu/compose.amqp.yaml`은 선택 network transport 레시피다. 명시 private env file·기존 external network·개별 tmpfs cache만 사용하고 공유 원본 bind mount·고정 container_name·Docker socket·broker service·자동 restart를 추가하지 않는다. 동일 역할의 복제는 Compose 실행 관리자의 책임이며 웹 fleet과 자동 연결하지 않는다. 이미지 빌드·컨테이너 자원 한도 수용은 미실행이다.

다음은 배포 승인 후 사용하는 진입점이며 현재 운영에 실행하지 않았다.

```sh
# 공통 base 의존성이 포함된 build graph 조회만 수행한다.
docker buildx bake -f docker-bake.hcl --print api cpu cpu-amqp api-broker gpu

# broker 설정은 namespace/url_env만, 실제 값은 별도 private 환경에서 제공한다.
python -m app.broker_server declare-topology --enable-broker --broker-config-env MIDEAGENT_BROKER_CONFIG
mideagent-cpu-amqp --enable-broker --agent analyze --broker-config-env MIDEAGENT_BROKER_CONFIG --object-config-env MIDEAGENT_AGENT_OBJECT_CONFIG
python -m app.broker_server consume-results --enable-broker --broker-config-env MIDEAGENT_BROKER_CONFIG --dsn-env MIDEAGENT_DATABASE_DSN --object-config-env MIDEAGENT_APP_OBJECT_CONFIG
```

API launcher는 `--allow-cpu --object-config-env <app-config> --broker-config-env <broker-config>`를 선택할 수 있다. `--agent-config-env`/`--manage-cpu`와 동시 사용하지 않으며 기존 `--dsn-env`/`--origin`을 명시한다. 브로커는 API startup이 아니라 명시 작업 dispatch 때 연결한다.

### 독립 CPU 진입점

Python 3.12+와 FFmpeg/FFprobe가 필요하다. `packages/shared[postgres,models,objects]`, `apps/api`, `agents/cpu`를 격리 환경에 설치한다. CPU 에이전트 자체는 PostgreSQL 패키지나 API 연결 없이 동작한다.

- `mideagent-analyze`, `mideagent-extract-audio`, `mideagent-generate-subtitle`, `mideagent-encode`, `mideagent-validate-video`: 각 고정 역할의 JSON stdin/stdout 명령. `--input-root`/`--output-root`는 명시 private root다.
- `mideagent-object-agent --agent <role> --owner <owner-id> --config-env <explicit-name>`: 원격 CAS를 사용하는 단일 명령. 설정은 endpoint/bucket/region/prefix/cache_root와 access_key_env/secret_key_env 이름만 포함한다.
- `python -m app.renewal_server --dsn-env <name> --origin http://127.0.0.1:<port> --content-root <root> --allow-cpu`: 로컬 전용 launcher.
- 같은 launcher의 `--manage-cpu`를 명시해야 관리자 상세에서 로컬 CPU fleet을 조작할 수 있다. CPU package를 같은 승인된 환경에 설치해야 하며 이 옵션 없이 조작 가능으로 표시하지 않는다. 실제 운영에 이 명령을 자동 적용하지 않는다.
- S3 실행은 content-root 대신 `--object-config-env <app-config-name> --agent-config-env <agent-config-name>`을 사용한다. 앱과 agent config의 private cache_root를 다르게 지정한다. 이 launcher는 공개 production server가 아니다.
- 구형 혼합 media 패키지·파일 queue·workflow executor·SQLite 계정/설정 API와 일회성 scripts는 제거했다. CPU/GPU는 실제 폴더에 package-dir를 매핑한다. FaceFusion/VAD 엔진 소스와 process-tree·transcript/decision/model-reference 공통 파서는 별도로 보존했다.

### 설정·wire 정본

- [MQ request/response 계약](agent-protocol.md)의 versioned schema를 패키지에 포함한다. 결과의 정확한 필드·포트·자료 유형과 request digest/세대/attempt를 runtime에서도 검사하며 raw 진단·추가 credential 필드는 거부한다.
- root Compose의 LLM/provider/model 환경변수 주입은 제거했다. `app.server --bootstrap-file`은 DB 접속 파일·콘텐츠 root·listen·origin/cookie 설정만 받고 startup에서 migrate/worker를 실행하지 않는다. 모델/provider/key 필드는 bootstrap에 허용하지 않는다. private runtime UID 읽기 조건은 루트 README를 따른다.
- 관리자 DB credential/revision resolver→주입 text wire와 레포 opt-in 설치 구성·실제 격리 broker 수용은 구현/검증했다. 실제 model agent/address-pinned network transport, GPU contract/consumer/engine, 원격 fleet·MagicDNS 운영 배포는 남아 있다. [배포 절차](../../rules/deploy.md)의 신규 설치/복구와 실행 승인 경계를 따른다.

### 검증과 남은 부채

- 정리 후 renewal 전체 회귀는 84개 통과(skip 없음), web 단위 44개와 production build도 통과했다. 소스/스키마 계약과 기존 네 브라우저 경로를 포함한다. AMQP는 실제 Pika property/실패 loopback handshake·채널 seam과 실제 CPU/S3/PG 검증이며 실제 RabbitMQ 서버 수용은 아니다. 추가 파일-bootstrap 서버/보존 자막 회귀 8개도 통과했다. 실제 파일 기반 서버 기동·liveness·관리 API의 인증 차단·DSN 비노출을 확인했다.
- 실제 CPU 기동 실패·종료, ready handshake 후 DB 기록 실패의 기존 검증도 유지한다. 변경 Python lint/format, 타입/build, Compose 역할 profile 11개와 Bake graph 정적 구성을 확인했다. Compose/Bake 검사는 이미지 빌드·스택 실행이 아니다.
- 테스트는 명시 disposable PostgreSQL의 임의 schema와 합성 미디어만 사용한다. S3 테스트는 임시 loopback 프로토콜 에뮬레이터이며 종료 후 서버를 닫는다.
- 코덱 지원 Chrome만 사용하는 우회와 구분한다. H.264/AAC 미지원 Chromium에서도 WebM 원본/산출물 재생, 재생 시간 진행·영상 크기, 원본/WebM 실제 다운로드와 SHA를 확인한다. FHD/cover/unfolded는 브라우저 에뮬레이션이지 실기기 수용이 아니다.
- 삭제된 구형 구현 전용 legacy suite는 같은 정리에서 폐기했다. 이전 legacy 27 failures를 해결했다는 뜻이 아니다. 보존한 pure 회귀와 renewal의 실제 CPU/S3/PG·브라우저 회귀를 별도로 실행한다.
- 전체 web lint는 기존 오류 80개, format은 기존 파일 네 개 부채가 있다. 에이전트 목록의 기존 컨벤션 오류 7개를 함께 정리했으며 변경 runtime 화면 lint·web 단위 테스트·타입/build 검사와 분리한다. 검사를 삭제하거나 실행 승인 보호를 낮추지 않는다.
- 실제 제품/다중 머신에서는 최소권한 bucket prefix 정책, 인증/허용 명령 범위, 브로커 topology, 장애/중복/취소 및 성능을 다시 수용해야 한다. 현재 S3 fixture는 IAM/실 MinIO 적합성을 증명하지 않는다.

## 미확정 사항

실제 제품/배포 분할·인증/브로커·GPU/실모델·대용량 비동기 실행은 별도 단계다.

## 관련 문서

- [구조](../../plans/architect.md) · [태스크](../../plans/tasks.md) · [격리 테스트](../../../tests/renewal/README.md) · [배포 경계](../../rules/deploy.md)

## 논리 슬롯1의 감사 가능한 대상 교체 (미배포)

019는 기존 control source 열/요청/ACK를 보존하고 계약 버전·후보·계획·교체/이벤트를 추가한다. 이 기능의 native 검사·완료는 새 host 실행 코드가 필요하다. 기존267 호스트/설정을 운영에서 바꾼 것은 아니다.

절차는 다음과 같다. 기존 제품 제어로 신규 배정을 막고 같은 boot 정상 종료0·signed ACK·미해결 제어 없음/발행 guard 자유를 확보한다. 기존 host를 정상 종료해 원래 exclusive lock을 반납한 뒤 정확한 candidate manifest를 준비한다. host 전용 `python -m video_service.target_handover --config-file <기존 host.json> --candidate-file <별도 manifest.json> --operation prepare --enable-handover`가 native inspect/서명을 검증하고 후보ID를 발급한다. manifest는 `agent`, `old`, `new`만 가지며 각 descriptor는 정확한 `container_id`, `image_id`, `labels`, `worker_id`다. 등록 슬롯은 늘리지 않는다.

관리자는 `/api/admin/agents/{agent}/target-handover`에서 준비된 후보와 이력을 읽고, `/preview`에 `candidate_id`, `/decisions`에 `plan_id`, `decision_id`, 10자 이상 `reason`, `acknowledge:true`를 정상 세션/CSRF로 보낸다. API는 임의 container/image/socket을 입력받지 않는다. 호스트는 같은 파일과 `--operation apply --transition-id <decision_id> --enable-handover`로 명시 실행한다. apply에는 기존 exclusive lock과 sender guard가 필요하고 이전/새 정확한 물리 정지·서명·권한·CAS를 다시 확인한다. 실제 전환은 계약 버전 추가·current epoch 갱신·applied 기록을 한 transaction에 반영한다. 이벤트에는 DB session actor/PID와 시각을 남긴다.

재기동할 host는 원래 config와 별도 `--handover-bindings-file`을 사용한다. 바인딩 JSON은 `{agent: 승인된 exact descriptor}`이며 DB에 기록됐다는 이유만으로 자동 채택하지 않는다. desired0을 유지하고 새 target을 자동 시작하지 않는다. 새 등록 상태와 관측을 확인한 뒤 별도의 명시 Start가 필요하다. 중단된 applying은 held로 남고, 오류 해소만으로 자동 재개되지 않는다. held의 해제/새 판단은 이번 범위가 아니다. 기존 Native adapter를 root 권한으로 직접 호출하는 것은 제품 host/요청 권한 경계 밖이며 이 기능이 범용 Docker administrator를 통제한다고 주장하지 않는다.

역할 권한은 새 테이블에도 분리한다. API는 후보/계약/이력 SELECT, 계획·planned 결정 INSERT와 group의 revision/pending_handover 입장 쓰기만 추가한다. 계약/후보 등록·phase 완료/이벤트 직접 쓰기·native 권한을 주지 않는다. 기존 host 전용 역할은 필요한 control/ACK/전송 근거 SELECT와 accounts의 id/role/active만 읽으며, 후보/불변 계약 INSERT와 승인된 transition phase 및 group current-pointer 갱신만 수행한다. events는 보호된 trigger가 append한다. 계정 비밀번호·원본/키/backup 쓰기 권한은 추가하지 않는다. 실제 운영 역할별 GRANT/이미지 설치는 별도 검토·승인 후 수행한다.

검증은 새 교체 경계의 실제 PG와 통제된 native adapter/인증 ASGI, 별도 실제 idle native 컨테이너/CLI·signed ACK 범위다. native 시험의 PG 상태 보고를 운영 MQ/제품 영상 E2E로 확대하지 않는다. 기존 MQ 영상·A/B 여정·#5 복구는 재실행하지 않는다.

## 운영 교체 전 설치 연결 리허설과 조건부 설치 순서

수용 `9ae90c4fe61edd3e2ea83c34fdba2a27aa6bd194`의 설치 이미지에서 별도 API·host LOGIN 역할로 실제 정상 흐름을 확인했다. 이는 SET ROLE로 owner를 가장한 시험이 아니라 각 프로세스/CLI가 서로 다른 전용 DSN으로 접속한 결과다. 관리자 승인 이벤트는 API session, applying/applied는 host session이었다. 두 역할 모두 superuser/createdb/createrole/replication/bypassrls가 아니며 schema CREATE/전체 table GRANT를 주지 않는다.

API는 정상 인증을 위해 accounts SELECT와 계정 발급의 지정 INSERT 열, 기존 계정 관리/row lock에 필요한 active/role UPDATE, sessions/login_limits의 필요한 동작, control 자료 SELECT·request/plan/planned decision INSERT 및 group admission 열만 사용한다. host는 accounts의 id/role/active만 읽고, control/ACK/관측과 전송 상태의 지정 읽기·고정 group 등록/관측·journal/서명 evidence·불변 후보/계약 INSERT·승인된 phase/current-pointer의 필요한 쓰기만 사용한다. API의 contract/phase/후보/이력 변조와 host의 password_hash 읽기·계정 변경 권한은 주지 않았다. 구체 table/column 목록과 실제 privilege audit은 리허설 제출 자료에 두며 운영 role에 포괄 권한으로 적용하지 않는다.

기존9ae 설치 연결 리허설의 일반 API는 private content root를 미리 준비해야 했고, 최초 누락 실패를 uid10001/mode0700 tmpfs로 해결했다. 새 유지보수 모드는 미디어/credential/broker initializer를 아예 호출하지 않으므로 content root를 생성하거나 새 공용 입력 route를 열지 않는다. 일반 normal 모드의 content root 조건은 그대로다. API는 private API leaf RO만, host는 config/DSN/key leaf RO·receipts RW와 지정 daemon socket만 가진다. host는 uid10001과 daemon group으로 실행했다. fixture 상태 발행자는 별도이며 PG 보고를 실제 MQ 처리로 확대하지 않는다.

### 명시 유지보수 기동 계약 — 구현·격리 설치 확인, 운영 미승인

- `app.server --bootstrap-file … --admission-mode maintenance --enable-control`과 bootstrap의 `admission_policy`가 반드시 일치해야 한다. normal도 `--admission-mode normal`과 `{"mode":"normal"}`을 명시한다. 기존 bootstrap/Compose를 그대로 쓰면 새 HTTP 서버가 기동을 거부하며, 이를 normal fallback으로 해결하지 않는다. background operator/dispatch/result의 설정 소비와 API의 입장 정책은 별개다.
- 유지보수 객체는 정확히 `{"mode":"maintenance","agent_id":"<기존 등록 agent>","slot_id":"<그대로 보존한 32hex worker slot>","handover":false}`다. 단일 capacity/slot 일치를 DB에서 읽기 전용 확인하며 enroll/provision·계약 수정은 하지 않는다. HTTPS origin·Secure cookie, control opt-in을 요구하고 broker 실행 opt-in은 거부한다. 설정 오류/DB preflight 실패는 sanitized error와 exit2, listener 미개방이다.
- `handover:false`는018에서 기동하고019가 필요한 GET/preview/decision을 닫는다. 019가 적용되거나 오류가 해소돼도 자동으로 바뀌지 않으며 같은 설정으로 재시작해도 닫힌다. 별도 승인된019/역할 계획 이후에만 `true`를 명시해 재시작한다. 해당 기동은019의 target table/epoch/pending catalog를 확인하며 미준비면 열지 않는다. migration 실행이나 API 역할의 schema_migrations SELECT/DDL GRANT를 추가하지 않는다.
- 유지보수 허용은 **GET `/healthz`, GET `/api/auth/session`, POST `/api/auth/login`·`logout`, GET `/api/admin/agents/{고정 agent}`, PUT 그 agent의 `/configuration` 중 strict `enabled=false/replicas=0/request_id/revision`**, 명시019 단계의 관리자 target-handover GET/POST preview·decisions뿐이다. 일반/관리자 모두 나머지 업로드/chunk/완료·원본 선언·작업 생성/승인/실행/복구·계정/모델/연결 변경과 미분류 경로·HTTP method는 body 수신/업무 DB·파일·외부 호출 전에503으로 닫는다. `/admin`·GET·OPTIONS 전체 허용은 없고 capabilities/media UI route도 열지 않는다.
- 허용 URL 자체는 인증 우회가 아니다. 기존 로그인·세션·권한/CSRF·origin·Secure cookie와 사유/개정/CAS 검사는 그대로며 Stop0도 기존 등록 slot을 같은 DB row lock 안에서 다시 대조한다. Start/증설/다른 slot과 등록 slot 변경은 차단한다. 최소 조회는 원격 mailbox만 읽고 일반 Fleet/미디어 조회에 필요한 권한을 추가하지 않는다.
- 기존 AuthGate는 auth/session→login으로 접속할 수 있으나 업무 화면은 닫힌 상태다. 이번 인터페이스는 기존 인증과 최소 관리자 API이지 새 유지보수/교체 UI가 아니다. 허용된 GET을 읽기 전용 감사 전역 보장으로 확대하지 않는다. 일반 작업/처리 확인 GET의 case capture 등은 허용 목록에 넣지 않았다.
- 설치본 새 경계20개(실패/오류/skip0, 기존 의존성 경고1)와 내부 TLS peer→실제 app.server 재시작을 확인했다. 이는 공개 ingress 추가 없이 network namespace 안의 시험 peer다. 기존267 host+018에서 실제 isolated target 종료0·signed ACK 뒤,019/명시 phase 전환→같은 HTTPS 세션의 preview/decision→host CLI apply/조회도 연결됐다. 새 target은 created/미시작, desired0이며012는 이 fixture에 없다. 이전47/MQ 영상/A-B는 반복하지 않았다.
- fixture 재현 중 이전 setup.py에 없고 수용된 최종 권한 inventory에는 있는 API의 dispatch 3열 SELECT를 빠뜨려 preview503이 났다. 계획0·transaction rollback을 확인하고 **기존 수용 inventory의 같은3열만** fixture에 복원했다. 새 제품 권한이나 운영 GRANT를 추가한 것이 아니다. 서버 자식 SIGTERM은 실제 -15도 기록하며 종료0으로 꾸미지 않는다. 실제 API container/old267 host/native stop은 각각 종료0이었다. 오프라인 build 시 runtime base에 setuptools backend가 없어 실패한 기록도 보존했고 이전 검증과 같은 pip 격리 build로 로컬 package를 재설치했다.
- 종전9ae 첨부의 lint 정본은 신규0/기존4 그대로다. 이번 변경 경로 lint는 신규0, 해당 경로의 기존2(I001/UP017), NTFS EXE0026건은 별도 환경 진단이며 전체 lint pass가 아니다. 비교는 같은 repo Ruff 설정의 archived baseline과 했다.

같은 별도 운영 복원 DB에서 migration loader가012와019만 적용함을 확인했다. 기존51개 업무 table의 원래 열 값, 기존 migration 행,6개 작업의 snapshot/원 origin fallback, #5 running과 제어/ACK 이력을 대조했다. 복원은 --no-owner/--no-privileges이므로 실제 운영 역할/ACL 적용 검토는 별도다.

### 승인 후에만 사용할 설치 순서

1. 원본/DB/설정·키/WIP·운영 image/target·Serve 경로와 기존 요청을 보존한다. **012/019보다 먼저 입장 차단을 설치·확인한다.** 기존 HTTP API의 신규 연결을 닫고 종료 전 이미 들어온 요청/transaction을 graceful drain해 정리 여부를 대조한 뒤,018 호환 유지보수 API만 `handover=false`로 기동한다. 오래된 normal API를 겹쳐 남기거나 timeout을 이유로 강제 종료/요청 초기화하지 않는다. 기존 HTTPS·정확한 origin·vault/세션·CSRF·Secure cookie를 그대로 사용하고 liveness의 mode/phase, 관리자 정상 접속·지정 Stop0, 일반/관리자 신규 업무 변경 거부를 확인한다. 누락/불일치/기존 listener 잔존/차단 미확인이면 여기서 중단한다. **이 닫힌018 API 선행 설치만 공용 기능의 API-only 공개와 구분하는 예외**다. 이번에 운영에 설치한 것은 아니다.
2. 정책 적용 이전에 이미 들어온 요청과 결과 수신·DAG 후속 발행은 입장 차단으로 취소/완료/중지되지 않는다. 기존 pending/sending/unknown·outbox/receipt·진행 노드와 각 송신 프로세스를 따로 대조하고 drain한다. 현재 승인된 host267 제어로 지정 encode Stop0를 접수해 새 배정을 막고 진행 작업 처리/ACK·동일 boot 정상 종료0·signed native ACK를 확인한다. #5/미확정 요청은 보존하며 자동 재발행·TTL 변경으로 통과시키지 않는다. 안전 정지/전송이 불명확하면 해당 교체를 보류한다.
3. 결과 수신과 후속 발행 정리가 끝난 뒤 API 외 results/dispatch/engine-results 등 모든 송신 경로와 해당 소비자를 정리한다. 기존 host267은 정상 종료해 원래 exclusive session을 반납한다. 입장 정책이 이 별도 프로세스들을 멈췄다고 간주하지 않는다. 필요한 백업/별도 복원 검토를 완료한 뒤에만 승인된012/019·역할 설치 단계를 진행할 수 있다. 이 작업에서 수용 복원/영상 시험을 다시 반복하지 않았다.
4. 별도 승인된012+019와 이미 검토된 지정 table/column 역할 계획을 적용한다. 앱4·CPU/model/GPU reader·웹의 origin 계약을 함께 맞추고 새 공용 입력을 정상 API만 먼저 노출하지 않는다. encode 후보는 같은 logical worker/역할·정확한 image/labels/mount·restart=no로 생성하되 미시작이다. API는 maintenance 유지와 명시 `handover=true` 재기동만 허용하고,019 catalog/역할 검토가 안 맞으면 미개방 상태로 멈춘다. auth/origin/cookie를 낮추거나 포괄 GRANT·새 ingress로 해결하지 않는다.
5. **호스트 코드 교체:** 새 host 코드를 준비하지만 daemon을 먼저 띄우지 않는다. host.json·DSN/key·ACK leaf를 보존하고 별도 manifest로 host CLI prepare→정상 HTTPS 관리자 preview/승인→같은 host CLI offline apply를 명시 실행한다. 원 host/session·sender가 소유 중이면 거부하며 group은 desired0이다. 중단된 applying은 held, 완료 응답 유실은 같은 기록 조회만 한다.
6. 승인된 exact descriptor만 든 별도 binding으로 새 host 진입점을 기동하고 계약/관측/desired0·새 target 미시작을 확인한다. **유지보수에서는 Start도 차단된다.** coordinated 설치·기존 기록·송신 fence와 복구 경계가 별도로 수용되기 전에는 유지보수/미개방 상태를 유지한다. 정상 접수 재개는 별도 승인 후 explicit normal bootstrap+기동 요구를 함께 바꾼 재기동으로만 하며, 오류 해소나 호스트 기동이 normal/Start를 뜻하지 않는다. 이후 Start 역시 별도 정상 인증/CSRF·개정에 따른 명시 조작이다.

### 중단·복구·롤백 경계

- 후보 준비/계획만으로 전환하거나 시작하지 않는다. applying 전 확인 실패는 거부/held이며 원 target 계약·작업은 그대로다. durable applying 중단은 다음 명시 호출에서도 held로 남고 자동 재시도·재신호·시작으로 이어지지 않는다. held 해제/취소는 수용 기능에 없다.
- pointer+applied transaction은 원자적이다. commit 뒤 응답 유실은 같은 decision의 완료 기록만 읽는다. 바인딩 누락/불일치로 daemon 기동이 막혔다고 DB 계약·원 config를 덮어쓰거나 old host를 다시 자동 채택하지 않는다. 승인된 exact 파일과 새 host 설치를 대조하는 복구만 별도 승인 아래 진행한다.
- 새 공용 작업이 생긴 후 old-reader/옛 owner FK로 단순 복귀하지 않는다. 최신 snapshot/원본/산출물/판단을 지우는 전체 DB 복원·owner 변경 대신 신규 접수/실행 보류와 origin-aware forward repair/별도 승인 복구를 사용한다. 이전 image가 남아 있어도 새 container ID에는 다시 정확한 감사 대상 전환이 필요하다.
- 이전9ae 설치 연결 리허설은 기능 확대 없이 최소권한 정상 연결·실제 entrypoint/binding·한 복원본012+019 확인만 수행했다. 수용된47개·MQ 영상·A/B 여정은 반복하지 않았다. lint 정본은 신규0·기존4이며 전체 lint 통과가 아니다. 운영012/019·host/image/pin·원본17개·#5는 변경하지 않았다.
