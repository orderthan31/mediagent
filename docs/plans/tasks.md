# 현재 구현 태스크

## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 현재 상태

2026-10-20/21 사용자가 Windows 목적지의 renewal 배포·SQLite 이관·새 consumer·로컬 GPU/모델과 합성 영상 검증을 승인했다. 아래 기존 격리 수용과 목적지 실제 실행을 구분한다. 기존 Worker·기존 큐 소비, 외부 유료 provider, 공개 ingress·registry publish·VPS 분할은 승인 범위가 아니다.

### Windows 목적지 실행 체크포인트 — 전체 완료 아님

- [x] 원본 1,587파일의 SHA snapshot, SQLite 3개 무결성, private 설정/키·정의·기존 ref/WIP/stash 보존.
- [x] `legacy/unassigned` 관리자 전용 immutable archive importer와 009 migration. 작업42(완료31/실패11, 내부25/사용자17), 인덱스42/14의 독립 namespace, 자산17·정의1·비활성 설정1을 분리한다. dry-run117 → 실제117 → 재실행 추가0을 대조했다. 개인 계정/새 실행 receipt/승인을 합성하지 않았다.
- [x] PG dump를 실제 별도 임시 DB에 restore하고 종류·상태·내부 구분·native jobs0·physical runtime4를 대조했다. 임시 DB만 정리하고 원본 SQLite/미디어·실제 DB/volume은 보존했다.
- [x] 기존 사설 443→loopback5177 경로에 API/web를 교체하고 PG/TLS RabbitMQ/S3를 기동했다. API/CPU/model/GPU는 UID10001·read-only root·역할별 bootstrap mount를 사용한다. 기존 secret bytes는 유지하고 controller 권한/참조 JSON과 새 역할만 추가했다.
- [x] CPU 정규화(`audio_filter=off`, `vad_mode=off`)와 별도 model/GPU v2 MQ를 구현했다. CPU v1에 GPU/model 역할을 끼워 넣지 않았다.
- [x] 실제 Whisper tiny.en CPU int8 전사, OPUS-MT en→de CPU int8 번역, NVIDIA Marblenet CUDA VAD, FaceFusion CUDA swapper/NVENC self-swap과 S3 receipt 재전달을 검증했다. 모델·GPU별 새 attempt의 실제 TLS MQ command/result/confirm/ACK도 별도 수용했다.
- [x] 합성 음성 영상의 분석→추출→전처리→전사→번역→자막→번인→검증을 실제 S3/TLS MQ/격리 PG에서 완료했다. 내려받은 12.6초 영상의 SHA/ffprobe와 실제 브라우저 끝까지 재생(315 frames, decoder error 없음)을 확인했다. 이 작업은 **disposable schema 검증**이지 제품 계정의 완료 작업이 아니다.
- [x] 별도 CPU 6개·model 2개·GPU 2개 consumer와 결과 소비자2개가 목적지의 독립 큐에 각1개 연결됐음을 확인했다. 실제 입력/출력 수용과 단순 connection 수를 구분한다.
- [ ] **실제 최초 관리자 설정/검증 브라우저 로그인 → 제품 원본 등록/저장/실행 → 제품 job/다운로드/플레이어 수용**. 계정이 없어 로그인 우회나 공유/가짜 계정을 만들지 않았다.
- [ ] legacy 자산의 실제 소유권 배정과 활성 workflow 전환. archive를 owner-scoped 자산/실행 작업으로 변환했다고 하지 않는다.
- [ ] 기존 Fernet credential은 비활성 원문/키 보존 상태다. AES-GCM 필드로 암호문 복사나 무료/환경변수 key 대체를 하지 않았다. 재등록/승인된 메모리 내 재암호화는 별도다.
- [ ] FaceFusion의 제품 세션/미리보기 binding·승인 API. 별도 합법적 self-swap RPC fixture 성공을 제품 faceswap workflow 완료로 확대하지 않는다.
- [ ] `decision`, Loop/Fallback은 renewal 실제 실행 미연결. controller-owned select/join/review/if/switch와 독립 consumer를 혼동하지 않는다.
- [ ] 한국어·다른 언어/모델, 일반 얼굴교체 품질, 긴/대용량 작업·lease 갱신·HA·웹의 remote-container 제어는 미수용이다. 현재 전사는 영어, 번역은 영어→독일어 고정 profile이며 전처리 필터는 off만 지원한다.

기존 작성자의 92/44 등 수용 수치와 이 목적지 회귀/실모델/GPU 수치를 합산하지 않는다. 목적지 실행 자료·실제 image ID·snapshot/dump SHA는 비공개 운영 인계에 보존하며 public 저장소에 키/DB/미디어/개인 운영주소를 넣지 않는다.

RabbitMQ opt-in client·CPU 수신기·결과 제어기와 명시 API dispatch, 공통 media-base stage를 추가했다. SDK/채널 대역 검증에 더해 고유 internal network·tmpfs의 실제 TLS RabbitMQ 4.2.9/MinIO와 독립 CPU 두 process·결과 소비 process·격리 PG를 연결해 합성 영상 완료, confirm/ACK·중복 receipt·DLQ·결과 SHA를 수용했다. 운영 broker/사용자 데이터와 분리한 검증이며 운영 설치 완료는 아니다.

## 주요 내용

### 완료 범위

- [x] Common 보존, 미디에이전트 Special, 저장소 정본 및 구형 문서 분리.
- [x] 구형 media 혼합 패키지·workflow/queue/API를 제거하고 `agents/cpu`·`agents/gpu`를 평탄화한다. 기존 GPU 엔진·공통 파서는 필요한 코드만 분리 보존한다.
- [x] `agents/cpu`에 역할 고정 개별 CLI를 제공하고 DB 없는 단일 명령/결과 계약을 연결한다.
- [x] 검증 업로드·불변 workflow/티켓·실행 승인·노드 결과·검수·취소/복구를 opt-in API/화면과 연결한다.
- [x] S3-compatible CAS와 별도 cache 에이전트 연결, 원격 SHA/소유자·중복/불명 결과·취소/복구 및 confirm/ack 순서를 격리 테스트한다.
- [x] 업로드·처리 결과에 별도 WebM을 생성하고 원본/WebM 다운로드, 실제 플레이어 재생·Range·다운로드 SHA를 검증한다.
- [x] 구형 `scripts/`의 일회성 POC·복구·벤치마크·배포 스크립트와 예전 생성 검증 이미지를 제거한다. 모델 설치는 GPU build 모듈로 이관하며 실제 원본·DB·키·백업은 보존한다.
- [x] 최종 격리 회귀·비밀정보/범위·문서 검사를 수행하고 검증된 소스를 renewal의 일반 커밋으로 공유한다. 아래 기존 부채와 운영 미검증은 분리한다.

### renewal 권한 경계

- [x] 일반 사용자는 원본·작업만 이용하고 나머지 관리 메뉴·직접 URL·renewal 관리 API를 차단한다. workflow·catalog·serving·계정·fleet 관리 API는 서버에서 관리자 권한을 확인한다.
- [x] 일반 계정의 관리 API 403·직접 URL 거부와 원본 업로드→관리자 제공 workflow 선택→작업 생성·승인→CPU 완료를 실제 production bundle 브라우저에서 검증한다. 작업 선택 전용 `/api/work-entry/*`와 불변 관리자 workflow 출처를 분리하고 원본·작업 소유자 격리를 유지한다.

### 에이전트 상세 운영 관리 — 로컬 CPU 구현, 컨테이너 운영 미연결

- [x] 기본 API·CPU 미디어 family·선택 GPU 도구 이미지 레시피를 분리하고 CPU 역할별 Compose profile을 정적 검증한다. API의 직접 미디어 처리용 FFmpeg는 남으며, 이미지 빌드·배포 완료로 보고하지 않는다.
- [x] 관리자 상세에서 서버 전체 종류별 사용 여부·목표 개수와 실제 private CPU subprocess 기동/종료·인스턴스 PID/상태/처리 수를 연결한다. 미연결 얼굴교체/모델 실행환경은 활성화 성공으로 표시하지 않는다.
- [x] 같은 종류의 두 실제 CPU 프로세스에 복수 작업을 분산한다. 인스턴스당 동시 처리 1개, revision 충돌·다른 controller 중복 기동 차단과 설정 변경 이력을 검증한다.
- [x] 비활성화·축소 시 신규 배정을 막고 예약된 작업의 완료 후 drain/종료한다. 선택 얼굴교체 미사용·CPU 기동/축소/종료와 일반 사용자 전체 작업 동선을 격리 검증한다.
- [ ] web 제어기와 실제 Compose/외부 orchestrator의 인증된 제한 adapter를 연결하고 컨테이너별 배포·기동·자원 한도를 검증한다. 현 로컬 subprocess를 컨테이너 scale이나 다중 호스트로 취급하지 않으며 API에 Docker socket을 제공하지 않는다.
- [ ] 얼굴교체 등 비-CPU 실행환경의 웹 운영/축소 adapter를 연결한다. 목적지의 수동 Compose 기동·실 GPU 역할 수용과 웹의 observed state/scale 제어를 구분한다.

### 독립 RabbitMQ 전달과 공통 의존성

- [x] Pika를 선택 extra로 분리하고 명시 namespace·환경변수 이름·TLS 설정만 받는 client를 구현한다. import/startup에서 연결·큐 선언·소비를 시작하지 않는다.
- [x] 명령 outbox의 확인 발행, 역할별 수신, 독립 CPU/S3 처리, 결과 DB 채택과 후속 명령 발행을 연결한다. 발행 실패의 동일 attempt 재전달·receipt/inbox 중복 방어·만료된 미발행 명령 거부를 검증한다.
- [x] CPU 작업 중 I/O thread의 heartbeat 처리, prefetch 1, 처리 후 confirm/ACK, SIGTERM drain과 poison/결과 불명 메시지 격리 경로를 구현한다. 채널 대역 검증을 실제 브로커 수용으로 부르지 않는다.
- [x] FFmpeg/FFprobe·폰트를 root media-base 한 stage로 관리하고 API·CPU·선택 GPU 도구가 공유하도록 Compose/Bake build graph를 연결한다. 기본 CPU와 AMQP 선택 이미지를 분리하며 heavy engine을 공통 base에 넣지 않는다.
- [x] CPU 역할별 AMQP profile·별도 private cache·role별 최소 broker 권한과 bootstrap mount를 제공한다. `infra/compose.yaml`에 별도 opt-in broker/PG/S3 설치 구성을 제공하며 startup 자동 초기화·자동 consumer·Docker socket은 없다.
- [x] 실제 격리 TLS broker 인증·역할별 독립 consumer/결과 제어기·후속 노드 전달·중복 명령/DB 결과·ACK 후 unacked=0·poison DLQ를 수용한다.
- [ ] 같은 role의 복수 remote consumer 분산, broker 재시작/네트워크 단절·HA와 장시간 운영을 별도 수용한다. 기존 운영 큐·GPU/provider는 테스트에 연결하지 않는다.
- [ ] 원격 consumer와 웹 fleet의 observed health·enabled/disabled·컨테이너 수 제어를 연결한다. 현재 웹 fleet은 여전히 로컬 CPU subprocess용이며 AMQP 설정을 실제 인스턴스 준비로 표시하지 않는다.
- [ ] 장시간 큐 대기/작업의 lease 갱신·cancel 전달·운영 retry/HA 정책을 수용한다. 현재 짧은 명령 TTL·기존 CPU lease를 일반 분산 scheduler로 보고하지 않는다.

### 소스·설정 정리

- [x] MQ request/result JSON Schema·정확한 역할/포트·옵션·digest·세대·CAS 참조 검사를 정본화한다. 예상 외 응답 필드·credential·raw 진단은 거부한다.
- [x] Compose의 LLM/provider/model 환경변수 주입과 구형 설정 API를 제거한다. root API는 명시 private bootstrap 파일만 읽으며 startup migration/worker는 없다.
- [x] 관리자 모델/connection revision CRUD와 DB encrypted credential 저장·교체·폐기·CAS·복호화 resolver를 연결한다. pinned DB endpoint/model/key가 injected text adapter의 요청에 반영되고 상충/삭제된 환경값으로 fallback하지 않음을 실제 격리 PG에서 검증한다.
- [ ] 일반 등록 모델의 owner-scoped provider/STT/TTS·address-pinned egress transport를 연결·승인한다. 목적지의 고정 offline STT/en→de/GPU engine v2는 별도 구현했으며, 이를 일반 model_ref transport나 외부 provider 수용으로 확대하지 않는다.
- [x] 레포 내 opt-in RabbitMQ/PG/S3 구성, private bootstrap 생성기, 수동 migration/bucket/topology, API/results/CPU 선택 기동과 복구 절차를 제공하고 실제 격리 broker를 수용한다. exact renewal·목적지 운영 경계·GPU 미구현/미검증 범위의 인계 준비를 완료한다. 실제 전달/수신/목적지 실행은 Discord 증적으로 별도 구분한다.

### 인프라 잔여 — GPU 작업으로 분류하지 않음

- [x] source-pinned MinIO를 실제 격리 TLS 서버로 build/기동하고 조건부 쓰기/CAS·attempt receipt·해시 검증을 CPU 왕복에서 확인한다.
- [ ] 운영 S3 IAM 최소권한·소유자 prefix 격리·장애/보관 정책을 수용한다. 개발 bootstrap의 공통 storage credential과 tmpfs 검증을 운영 데이터 보관 완료로 취급하지 않는다.
- [ ] 운영 승인 범위에서 브로커·에이전트 인증과 다중 머신 전달·취소·장애 복구를 연결한다. 기존 큐는 소비하지 않는다.
- [ ] Loop/Fallback의 실행 정책과 추가 입력 binding을 구현한다. 현재 편집만 지원하는 경로는 실행 승인을 차단한다.
- [ ] 장시간/대용량 WebM 파생 생성을 durable 비동기 작업으로 확장한다. 현재 256 MiB/단계별 timeout 한계를 대용량 지원으로 보고하지 않는다.
- [x] API의 legacy import와 단일 파이프라인·legacy Docker target/overlays를 제거한다. 사용자 원본·자막·DB·키·백업은 삭제하지 않는다.
- [ ] 전체 web lint/format 부채를 별도 정비한다. 삭제된 legacy 구현 전용 suite는 함께 폐기했으며 기존 실패를 수정했다고 보고하지 않는다. renewal·독립 CPU·보존 pure 회귀는 유지한다.

### 승인·수용 경계

- [x] 이 Windows 목적지의 배포·archive migration·새 consumer·로컬 GPU/모델·합성 미디어 검증 승인과 실제 실행. 위 체크포인트의 미수용 항목은 남긴다.
- [ ] 외부 유료 provider·실소유자 credential 재활성·미승인 원본 처리·다른 목적지/공개 배포는 별도 승인 필요.
- [ ] 실사용자 최초 관리자·제품 계정 E2E와 legacy 자산 소유권은 위 잔여대로 별도 수용한다.

## 미확정 사항

스토리지 제품·배포 위치, 외부 실행 관리자, drain 제한시간/강제중지와 장애 후 소유권 인계는 [미확정 기획](ideation.md)에서 별도 결정한다. 원본·작업 이외의 관리 기능과 서버 전체 에이전트 제어는 관리자 전용이다. 현 CPU 기본 동작은 강제 종료가 아닌 drain이다.

## 관련 문서

- [구조](architect.md) · [실행 계약](../references/high/runtime.md) · [미확정안](ideation.md)
