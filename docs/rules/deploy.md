# 배포 규칙

## Common

- 푸시가 발생하면 정식 빌드를 수행한다. 빌드 성공 후 [버전 관리 규칙](version.md)에 따라 버전을 확정하고 빌드 산출물을 배포한다.
- 빌드가 실패했거나 크래시가 발생한 경우 해당 산출물은 배포 대상으로 승격하지 않는다.

## Special

### 현재 배포 경계

- Common의 정식 빌드·산출물 배포는 해당 릴리스의 실행 승인이 있는 범위에만 적용한다. 소스 push나 검증용 build를 운영 전환 승인으로 취급하지 않는다.
- 기존 사설 5174 DEV는 별도 담당 범위를 유지한다. 2026-10-20/21 사용자 지시로 Windows 목적지의 기존 제품 배포 하나·필요 PG/TLS broker/S3·renewal consumer·로컬 GPU/모델·합성 영상 검증을 승인했다. 목적지의 기존 5177 loopback/사설 Serve를 재사용하며 다른 목적지·공개 ingress·병행 제품 stack으로 확대하지 않는다.
- 격리 PG와 합성 미디어의 임시 loopback 테스트는 운영 DB·기존 큐·사용자 원본을 사용하지 않는다. 테스트 프로세스와 운영 에이전트를 구분한다.
- 이 목적지의 명시 로컬 GPU/고정 모델·테스트 입력은 승인 범위다. 기존 Worker/기존 큐 소비, 외부 유료 provider·미승인 사용자 원본 처리/삭제·기존 키 교체·공개 범위 확대는 계속 금지한다.
- VPS 분할은 미실행이다. Windows 목적지의 archive 이관/배포 실제 실행과 실사용자 계정·소유권·제품 E2E 미수용을 구분한다. 정확한 source/build·호환성·복구·접근을 확인한다.
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
6. `app.server`는 필수 `database_dsn_file`, `content_root`, `allowed_origins`, `host`, `port`, `secure_cookies`와 선택 `credential_key_file`, `object_config_file`, `broker_config_file`, `engine_broker_config_file`만 허용한다. `--enable-broker`와 object/broker file을 함께 제공해야 API의 명시 CPU dispatch가 켜진다. 추가 engine file은 별도 v2 factory와 DB-pinned 물리 runtime을 사용하며 임의 model_ref/provider fallback을 켜지 않는다. API startup은 migration/큐 declare/consume/작업 scan을 하지 않는다.
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

### 기존 설치 archive 이관과 고정 engine 운영

- `legacy_archive.build_manifest`는 멈춘 source의 일관 snapshot에서 job/asset/workflow/비활성 settings와 각 SQLite index를 다른 kind/namespace로 만든다. 원본/미디어/정의/키·DB snapshot·파일 hash inventory를 별도 보존한다. index42와 index14를 job56으로 합산하지 않는다.
- `009_legacy_archive.sql`과 `app.legacy_import --bootstrap-file ... --manifest-file ...`는 관리자 전용 `legacy/unassigned` 읽기 전용 이력을 사용한다. 기본은 dry-run, 실제 쓰기는 `--apply`다. 같은 내용 재실행은 추가0, 같은 identity의 다른 내용은 충돌로 멈춘다. 기존 상태를 새 node run/receipt/승인으로 만들지 않는다.
- 기존 workflow 원문/자산 참조를 보존해도 실행 가능으로 자동 승격하거나 가짜/개인 owner에 배정하지 않는다. 실제 소유권 배정·지원 노드 전환·credential 재활성은 별도 결정이다. admin archive 화면도 원본 다운로드/새 실행으로 우회하지 않는다.
- Fernet 암호문을 AES-GCM credential로 복사하지 않는다. 기존 cipher/key는 private snapshot에 보존하고 archive 설정은 비활성으로 둔다. 재등록 또는 승인된 메모리 내 재암호화 전까지 외부/free/env key로 대체하지 않는다.
- PG dump는 별도 신규 임시 DB restore/행·관계 대조를 수행할 수 있다. 실제 source DB/volume에 fresh-install 초기화·restore를 덮어쓰지 않는다. 임시 DB 정리는 자신이 만든 exact 이름에만 한정한다.
- 고정 offline engine은 `engine_runtime_revisions`/head(010)의 물리 descriptor CAS와 private locator를 결속한다. 일반 owner-scoped 등록 모델/connection/credential transport는 여전히 별도다.
- `app.engine_admin provision --directory ... --manifest-file ... --apply`는 검증한 네 역할 manifest를 받아 **새 역할 credential과 참조만 추가**한다. 기존 secret/CA/DSN/master key는 바꾸지 않는다. controller 권한·참조 JSON과 broker definitions의 변경 delta를 read-back하고 private backup에 보존한다. 기존 runtime/locator가 다르면 자동 교체하지 않는다.
- `app.engine_admin register --bootstrap-file ... --manifest-file ... --role ... --expected-revision ... --enable-runtime --apply`는 확인한 물리 descriptor를 DB에 명시 등록한다. manifest는 secret이 아니라 `{descriptor,model_dir[,python]}`이고 descriptor 모델 SHA는 실제 다운로드/설치 파일에서 산출한다. 개인 계정이나 원본 소유자를 생성하는 기능이 아니다.
- Bake target `cpu-local-models`는 CPU offline ASR/MT, `gpu-amqp`는 별도 GPU consumer다. GPU broker는 `GPU_ENGINE_BASE`로 검증된 dependency image를 명시할 수 있다. 구형 image의 SDK layer를 재사용하더라도 entrypoint는 새 `mideagent-gpu-broker`이며 옛 Worker/큐/데이터/PAID 설정을 기동하지 않는다. 기본 GPU 도구 help와 실제 설치/추론은 구분한다.
- `compose.engines.yaml`의 `local-engines`/`gpu-engines` profile은 역할별 bootstrap leaf와 실제 weights만 read-only mount한다. `MIDEAGENT_ASR_MODEL_DIR`, `MIDEAGENT_TRANSLATION_MODEL_DIR`, `MIDEAGENT_FACEFUSION_MODELS_DIR`는 실제 검증된 절대 경로다. weights/caches/private manifests를 Git에 넣지 않는다.
- 역할 CLI는 `--enable-broker --agent ... --broker-config-file ... --object-config-file ... --runtime-config-file ...`가 명시돼야 소비한다. model CLI에 GPU role을 넣을 수 없다. source/모델 hash·UID read·cache write·TLS 인증·role 권한과 실제 command/result/ACK를 각각 확인한다.
- `compose.transport.yaml`의 `engine-results`는 `consume-engine-results` 전용 별도 결과 제어기다. 명시 `declare-topology`가 두 family를 선언하며 startup은 자동 선언하지 않는다. inactive/미설정 모델을 켜거나 기존 큐를 scan하지 않는다.
- Windows는 bootstrap의 `/api` leaf를 mount하고 `compose.windows.yaml`로 loopback5177을 재사용한다. POSIX chmod/chown 성공은 NTFS 기밀성 증명이 아니다. 새 private parent의 NTFS ACL·각 role 실제 UID의 read/write와 다른 role/API secret 미노출을 별도로 확인한다.
- RabbitMQ CLI가 제한된 PID 안에서 `inet_gethost:eagain`으로 실패하면 서비스 건강과 조회 실패를 구분한다. 검사 CLI만 `ERL_FLAGS='+S 1:1 +SDcpu 1 +SDio 1 +A 1'`로 제한해 재조회할 수 있다. 이를 인증 실패나 전 서비스 재시작 사유로 오판하지 않는다.
- 최초 관리자·실사용자 로그인은 별도 수용이다. 계정이 없으면 검증 브라우저에서 실제 사용자가 설정하도록 요청하고 로그인 우회·공유 비밀번호·가짜 owner로 제품 E2E를 통과시키지 않는다. disposable schema의 영상 완료와 제품 계정의 원본/작업/결과 경로를 정확히 구분한다.

### 검증과 중단·복구

- `tests/renewal/test_credentials.py`: 실제 격리 PG의 관리자 write-only/CAS·암호문·wrong key/owner/tamper·폐기·환경 fallback 부재와 DB pinned model→주입 transport를 검증한다. 실제 provider 호출이 아니다.
- `tests/renewal/test_live_broker.py`: Linux Docker에서 `MIDEAGENT_TEST_LIVE_BROKER=1`과 `MIDEAGENT_TEST_DISPOSABLE=1`, 명시 disposable PG가 모두 있을 때만 실행한다. 고유 labeled internal network·tmpfs RabbitMQ/MinIO·별도 CPU 두 process·결과 소비 process·합성 미디어로 TLS/confirm→처리→DB 채택→후속 전달→ACK, 중복 command/receipt, poison DLQ와 결과 SHA를 확인한다. host port는 publish하지 않고 테스트 전용 private bridge로 접근한다. 운영 broker는 탐색하지 않는다.
- 기본 API만 시작해도 consumer가 생긴다고 가정하지 않는다. 선택 profile/명시 `--enable-broker`가 없으면 소비하지 않아야 한다. web fleet의 현재 observed state/replica 제어는 로컬 subprocess용이며 Compose의 실제 scale/원격 health와 자동 동기화하지 않는다.
- 축소/정지는 새 assignment를 막고 in-flight 작업을 drain한 뒤 수행한다. 현재 짧은 command TTL/lease를 장시간 GPU 작업/HA 정책으로 확장하지 않는다. cancellation 전달, lease 갱신, 복수 host 장애·broker 재시작 수용은 별도 잔여다.
- rollback 시 source SHA·실행 image ID·Compose·DSN·DB backup·content/object data·credential master key·broker 정의/상태를 함께 보존한다. migration 후 이전 binary를 새 schema에 무조건 연결하지 않는다. 운영 `down -v`, 자동 큐 purge, 사용자 원본/자막 삭제, 강제 Git reset/clean/force push는 금지한다.
- GPU 도구 image/CLI의 존재·help 성공은 GPU agent 준비가 아니다. 고정 GPU/model v2는 별도 namespace/codec/consumer로 구현했으며 CPU-only v1에 GPU를 넣지 않는다. 목적지의 실제 CUDA VAD·CUDA FaceFusion self-swap·offline STT/MT 수용과 일반 model_ref/provider transport·장시간/품질 미수용을 구분한다. 외부 유료 호출은 이번 승인에 포함되지 않는다.
