# 배포 규칙

## Common

- 푸시가 발생하면 정식 빌드를 수행한다. 빌드 성공 후 [버전 관리 규칙](version.md)에 따라 버전을 확정하고 빌드 산출물을 배포한다.
- 빌드가 실패했거나 크래시가 발생한 경우 해당 산출물은 배포 대상으로 승격하지 않는다.

## Special

### 현재 배포 경계

- Common의 정식 빌드·산출물 배포는 해당 릴리스의 실행 승인이 있는 범위에만 적용한다. 소스 push나 검증용 build를 운영 전환 승인으로 취급하지 않는다.
- 현재 허용된 상시 화면은 기존 사설 5174 DEV 목업이다. 이를 유지하며 API·에이전트·브로커·오브젝트 스토리지의 운영 스택은 별도 승인 없이 시작하거나 외부에 노출하지 않는다.
- 격리 PG와 합성 미디어의 임시 loopback 테스트는 운영 DB·기존 큐·사용자 원본을 사용하지 않는다. 테스트 프로세스와 운영 에이전트를 구분한다.
- GPU·실모델/provider·유료 호출, 기존 큐 소비, 사용자 원본 처리·삭제, 키 변경·공개 범위 확대는 별도 실행 승인 전 금지한다.
- 최종 VPS/5070 Ti 배포 분할과 실제 데이터 이관은 미실행이다. 정식 배포 때에만 정확한 source/build·호환성·백업·롤백과 접근을 검증한다.
- Android/Windows 게임 빌드, Google Drive 경로 및 게임 산출물 보관 규칙은 이 프로젝트에 적용하지 않는다. 제품 릴리스 산출물의 게시 위치가 미확정이면 배포 대기로 남기고 임의 공개하지 않는다.

### 저장소 제공 설치 구성과 권한

- 기본 `docker-compose.yml`은 API/web만 정의하며 provider/model/key 환경변수, 자동 migration, 브로커/worker 기동을 포함하지 않는다. 실제 renewal production frontend는 Docker build에서 `VITE_RENEWAL_BACKEND=1`로 컴파일한다. DEV 목업은 기존 DEV 전용 조건을 유지한다.
- `infra/compose.yaml`은 명시 `infrastructure` profile의 PostgreSQL 17·RabbitMQ 4.2.9 TLS·MinIO S3 구성이다. 버전/이미지 digest를 고정하며 broker/DB/S3/관리 콘솔 host port는 공개하지 않는다. API/web와 별도 Compose project로 운용하고 같은 명시 private network 이름으로 연결한다.
- `compose.transport.yaml`은 root Compose에 병합하는 opt-in API/S3/AMQP overlay다. `operator`는 수동 초기화, `results`는 명시 결과 소비 process다. CPU role은 `agents/cpu/compose.amqp.yaml`의 개별 profile로 선택한다. media-base는 공유 이미지 layer이지 실행 중인 공통 FFmpeg 서비스가 아니다.
- MinIO 바이너리 registry 취득 실패를 임의 mirror로 우회하지 않는다. `infra/objects.Dockerfile`은 공식 source commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`와 builder/runtime digest에서 직접 build한다. source release label과 실제 binary version 출력은 구분한다. AGPL license를 image에 보존하며 운영자는 배포 전 upstream 지원·보안·license 의무를 재검토한다. 이 레시피는 vendor의 최신 binary/support 보증이 아니다.
- 이미지 build·CLI/import와 합성 미디어 격리 수용은 운영 배포 승인이나 GPU 실행 수용을 대신하지 않는다. 실제 데이터가 있는 기존 설치에 fresh-install 초기화 명령을 실행하지 않는다.

### 설정 정본과 private bootstrap

1. 관리자 저장 API → `connection_revisions`/`model_revisions` → `provider_credentials`의 AES-GCM 암호문과 opaque `db:<id>` 참조 → DB resolver → 명시 승인 transport의 모델 요청 순서다. provider/key/model 선택에는 환경변수 fallback이 없다. 테스트는 상충하는 환경값을 넣어 저장한 DB endpoint/model/key가 injected wire에 전달되는지 확인한다.
2. API 키는 관리자 전용 write-only `PUT /api/settings/serving-connections/{id}/credential`에서 저장·교체하거나 `secret: null`로 전체 폐기한다. CSRF와 revision CAS를 요구하며 원문을 응답·목록·workflow/job/broker payload에 넣지 않는다. 브라우저에는 편집 중 메모리에만 보관한다.
3. 키 교체는 새 connection revision을 만든다. 기존 모델/작업의 pinned revision은 자동 교체하지 않는다. 전체 폐기는 해당 connection의 이전 credential도 차단한다. endpoint/provider/protocol 변경은 새 revision에 이전 키를 자동 복사하지 않는다. 모델에서 필요한 새 connection revision을 다시 선택한다.
4. 구형 `env:` credential 참조는 이력 보존만 하고 해석하지 않는다. migration 008은 새 쓰기를 DB ref로 제한하며 기존 이력은 `NOT VALID`로 보존한다. 실제 migration 전 구형 참조/호환성을 분류하고 관리자가 키를 다시 등록한다. 기존 DB가 이관됐다고 자동 판정하지 않는다.
5. 복호화 master key, DSN, broker/S3 endpoint·전송 인증·TLS CA, origin/port/cache 경로는 프로세스를 시작하기 위한 별도 private infrastructure bootstrap이다. master key는 provider API key가 아니며 DB dump와 함께 복구 가능하게 별도 보관한다. 분실/교체하면 기존 암호문을 복호화하지 못한다. 생성기는 기존 디렉터리를 덮어쓰지 않는다.
6. `app.server`는 필수 `database_dsn_file`, `content_root`, `allowed_origins`, `host`, `port`, `secure_cookies`와 선택 `credential_key_file`, `object_config_file`, `broker_config_file`만 허용한다. `--enable-broker`와 object/broker file을 함께 제공해야 API의 명시 CPU dispatch가 켜진다. API startup은 migration/큐 declare/consume/작업 scan을 하지 않는다.
7. broker/objects file은 실제 값을 담는 환경이 아니라 private 파일을 직접 읽는다. 기존 explicit environment-name transport CLI는 호환용 infrastructure interface로만 남는다. 잔여 environment 접근은 test opt-in, DB/전송 bootstrap, subprocess 최소 실행 환경, GPU resource/offline 제어로 분류하며 application provider/model fallback으로 사용하지 않는다.
8. DB resolver의 text wire는 검증됐지만 default 모델 네트워크 실행은 여전히 disabled다. 실제 local/on-prem 또는 provider 통신은 승인된 origin과 address-pinned transport, 능력별 agent adapter 및 실행 승인이 필요하다. Gemini/Anthropic·STT/TTS 등 등록 가능한 메타데이터를 실행 지원으로 표시하지 않는다.

### 신규 빈 설치의 수동 순서 — 운영 전환 명령 아님

다음은 Linux Docker 기준의 신규 빈 설치 절차다. 기존 5070 Ti 설치는 먼저 실제 checkout/HEAD/WIP·DB·volume·private 설정·기존 접근 경로를 확인하고 검증된 백업과 migration/복구 계획을 확보한다. Windows/WSL은 목적지 담당자가 실제 bind mount와 UID/ACL을 확인해 같은 절차를 적용한다. 새 디렉터리/volume을 기존 데이터 이관 완료로 보고하지 않는다.

```sh
# 1. 현재 renewal을 exact SHA로 확인한 뒤 선택 이미지만 build한다.
docker buildx bake -f docker-bake.hcl api-broker cpu-amqp
docker build -f infra/objects.Dockerfile -t mideagent-objects:9e49d5e .

# 2. 아래 세 값은 운영자가 실제 사설 origin/외부 private 경로/고유 network로 지정한다.
# PUBLIC_ORIGIN은 허용된 정확한 한 origin이며 wildcard나 공개 ingress가 아니다.
export MIDEAGENT_BOOTSTRAP_DIR="$HOME/.local/share/mideagent/bootstrap-private"
export MIDEAGENT_AGENT_NETWORK="mideagent-private-transport"
# export PUBLIC_ORIGIN='operator-approved-exact-origin'
mkdir -p "$HOME/.local/share/mideagent"
chmod 700 "$HOME/.local/share/mideagent"
# parent만 mount하고 신규 생성기를 실행한다. 기존 bootstrap-private가 있으면 실패한다.
docker run --rm --network none --user 0:0   -v "$HOME/.local/share/mideagent:/install" mideagent-api-broker:local   python -m app.bootstrap --directory /install/bootstrap-private --origin "$PUBLIC_ORIGIN"

# 3. 서로 다른 project의 파일 상대경로를 섞지 않는다. 이 시점에 API/consumer는 없다.
docker compose -p mideagent-infra -f infra/compose.yaml --profile infrastructure config --quiet
docker compose -p mideagent-infra -f infra/compose.yaml --profile infrastructure up -d postgres broker objects

# 4. operator 명령은 매번 명시한다. 운영 DB에는 백업/승인 없이 실행하지 않는다.
docker compose -f docker-compose.yml -f compose.transport.yaml run --rm operator   migrate --bootstrap-file /run/bootstrap/api.json --apply-migrations
docker compose -f docker-compose.yml -f compose.transport.yaml run --rm operator   initialize-objects --bootstrap-file /run/bootstrap/api.json --initialize-empty-bucket
docker compose -f docker-compose.yml -f compose.transport.yaml run --rm operator   declare-topology --bootstrap-file /run/bootstrap/api.json --enable-broker

# 5. migration/readiness/권한을 확인한 뒤 API/web만 시작한다. 이 명령은 GPU가 아니다.
docker compose -f docker-compose.yml -f compose.transport.yaml --profile renewal up -d api web
# 6. 합성 작업의 명시 승인이 있을 때만 결과 수신기와 선택 CPU role을 시작한다.
docker compose -f docker-compose.yml -f compose.transport.yaml --profile results up -d results
docker compose -p mideagent-cpu -f agents/cpu/compose.amqp.yaml --profile encode --profile validate-video up -d encode validate-video
```

- `api`/`operator`/`broker`/`objects`/각 `agent/<role>`의 mount를 분리한다. CPU에는 DB DSN·provider master key·다른 role broker credential·CA private key를 mount하지 않는다. `offline-ca` private key는 어느 runtime에도 mount하지 않는다. 생성된 leaf 인증서는 1년 만료이며 운영자가 만료 전 갱신·재검증한다.
- RabbitMQ는 TLS server 인증과 별도 operator/controller/role 계정을 사용한다. controller는 command 발행/result 소비, 각 CPU는 자기 queue 소비/result 발행 권한만 갖는다. 관리 UI와 AMQP/S3 host publish는 기본 없다. namespace 변경은 definitions/queue topology와 함께 새 격리 범위에서 검토한다.
- 신규 S3 bootstrap은 개발/단일 운영 경계의 공통 storage credential을 사용한다. 운영 다중 tenant/신뢰 분리에는 owner-prefix 최소권한 IAM 계정, 관리 credential 분리·재발급·보관·장애 정책의 별도 수용이 필요하다. CAS 해시/조건부 쓰기를 S3 IAM 격리의 대체로 삼지 않는다.
- 각 image의 실제 UID/GID로 bootstrap read·cache/data write를 확인한다. 현재 고정 RabbitMQ Alpine UID=100, PostgreSQL Alpine UID=70, API/CPU/objects UID=10001이다. 신규 Docker named volume의 초기 소유권도 확인한다. root exec 성공으로 비-root 실행 성공을 대신하지 않는다.
- `/healthz`는 liveness다. API healthcheck는 허용된 Host를 명시한다. PostgreSQL `pg_isready`, 실제 migration 목록, S3 bucket access/조건부 쓰기, TLS broker 인증/queue·consumer readiness는 별도 확인한다. nginx 업로드 한도는 API 256 MiB와 일치시킨다.
- default 인증은 유지한다. 이전 임시 무인증 검토 환경을 새 계정 설정 완료로 간주하거나 운영 설정을 임의 변경하지 않는다. 기존 사설 URL/매핑은 목적지 담당자가 확인 후 보존하며 public ingress나 추가 병행 stack을 만들지 않는다.

### 검증과 중단·복구

- `tests/renewal/test_credentials.py`: 실제 격리 PG의 관리자 write-only/CAS·암호문·wrong key/owner/tamper·폐기·환경 fallback 부재와 DB pinned model→주입 transport를 검증한다. 실제 provider 호출이 아니다.
- `tests/renewal/test_live_broker.py`: Linux Docker에서 `MIDEAGENT_TEST_LIVE_BROKER=1`과 `MIDEAGENT_TEST_DISPOSABLE=1`, 명시 disposable PG가 모두 있을 때만 실행한다. 고유 labeled internal network·tmpfs RabbitMQ/MinIO·별도 CPU 두 process·결과 소비 process·합성 미디어로 TLS/confirm→처리→DB 채택→후속 전달→ACK, 중복 command/receipt, poison DLQ와 결과 SHA를 확인한다. host port는 publish하지 않고 테스트 전용 private bridge로 접근한다. 운영 broker는 탐색하지 않는다.
- 기본 API만 시작해도 consumer가 생긴다고 가정하지 않는다. 선택 profile/명시 `--enable-broker`가 없으면 소비하지 않아야 한다. web fleet의 현재 observed state/replica 제어는 로컬 subprocess용이며 Compose의 실제 scale/원격 health와 자동 동기화하지 않는다.
- 축소/정지는 새 assignment를 막고 in-flight 작업을 drain한 뒤 수행한다. 현재 짧은 command TTL/lease를 장시간 GPU 작업/HA 정책으로 확장하지 않는다. cancellation 전달, lease 갱신, 복수 host 장애·broker 재시작 수용은 별도 잔여다.
- rollback 시 source SHA·실행 image ID·Compose·DSN·DB backup·content/object data·credential master key·broker 정의/상태를 함께 보존한다. migration 후 이전 binary를 새 schema에 무조건 연결하지 않는다. 운영 `down -v`, 자동 큐 purge, 사용자 원본/자막 삭제, 강제 Git reset/clean/force push는 금지한다.
- GPU 도구 image/CLI의 존재·help 성공은 GPU agent 준비가 아니다. 현재 GPU 도구는 AMQP CPU consumer가 아니며 CPU-only protocol에 GPU role을 임의로 넣지 않는다. GPU role contract/consumer adapter와 모델·provider 능력별 실행 경로의 후속 구현/수용, NVIDIA runtime/CUDA·torch/torchaudio/ONNX 조합, 모델 artifact, 엔진 기동/실행/결과를 구분해 보고한다. 실 GPU/provider/유료 호출은 별도 승인 전 금지한다.
