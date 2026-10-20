# 현재 구현 태스크

## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 현재 상태

CPU/저장소/WebM에 이어 renewal 관리자 권한과 명시 로컬 CPU 인스턴스 운영을 구현·격리 검증했다. 컨테이너·GPU·외부 실행 관리자는 연결하지 않았다. 운영 잔여를 아래에서 관리한다.

RabbitMQ opt-in client·CPU 수신기·결과 제어기와 명시 API dispatch, 공통 media-base stage를 추가했다. SDK/채널 대역과 실제 격리 CPU·S3·PG를 구분해 검증했으며 실제 RabbitMQ 서버·컨테이너 운영은 실행하지 않았다.

## 주요 내용

### 완료 범위

- [x] Common 보존, 미디에이전트 Special, 저장소 정본 및 구형 문서 분리.
- [x] `workers/media/media_worker`를 `agents/media/media_agent`로 실제 이관하고 import·패키지·CLI·Docker·스크립트·테스트 참조를 정리한다.
- [x] `agents/cpu`에 역할 고정 개별 CLI를 제공하고 DB 없는 단일 명령/결과 계약을 연결한다.
- [x] 검증 업로드·불변 workflow/티켓·실행 승인·노드 결과·검수·취소/복구를 opt-in API/화면과 연결한다.
- [x] S3-compatible CAS와 별도 cache 에이전트 연결, 원격 SHA/소유자·중복/불명 결과·취소/복구 및 confirm/ack 순서를 격리 테스트한다.
- [x] 업로드·처리 결과에 별도 WebM을 생성하고 원본/WebM 다운로드, 실제 플레이어 재생·Range·다운로드 SHA를 검증한다.
- [x] 참조 없는 구형 CPU POC 스크립트 네 개를 제거한다. 의존 코드가 있는 legacy 파이프라인은 보존하고 기본 실행을 차단한다.
- [x] 최종 격리 회귀·비밀정보/범위·문서 검사를 수행하고 검증된 소스를 renewal의 일반 커밋으로 공유한다. 아래 기존 부채와 운영 미검증은 분리한다.

### renewal 권한 경계

- [x] 일반 사용자는 원본·작업만 이용하고 나머지 관리 메뉴·직접 URL·renewal 관리 API를 차단한다. workflow·catalog·serving·계정·fleet 관리 API는 서버에서 관리자 권한을 확인한다.
- [x] 일반 계정의 관리 API 403·직접 URL 거부와 원본 업로드→관리자 제공 workflow 선택→작업 생성·승인→CPU 완료를 실제 production bundle 브라우저에서 검증한다. 작업 선택 전용 `/api/work-entry/*`와 불변 관리자 workflow 출처를 분리하고 원본·작업 소유자 격리를 유지한다.

### 에이전트 상세 운영 관리 — 로컬 CPU 구현, 컨테이너 운영 미연결

- [x] 기본 API·CPU 미디어 family·선택 legacy media 이미지 레시피를 분리하고 CPU 역할별 Compose profile을 정적 검증한다. API의 직접 미디어 처리용 FFmpeg는 남으며, 이미지 빌드·배포 완료로 보고하지 않는다.
- [x] 관리자 상세에서 서버 전체 종류별 사용 여부·목표 개수와 실제 private CPU subprocess 기동/종료·인스턴스 PID/상태/처리 수를 연결한다. 미연결 얼굴교체/모델 실행환경은 활성화 성공으로 표시하지 않는다.
- [x] 같은 종류의 두 실제 CPU 프로세스에 복수 작업을 분산한다. 인스턴스당 동시 처리 1개, revision 충돌·다른 controller 중복 기동 차단과 설정 변경 이력을 검증한다.
- [x] 비활성화·축소 시 신규 배정을 막고 예약된 작업의 완료 후 drain/종료한다. 선택 얼굴교체 미사용·CPU 기동/축소/종료와 일반 사용자 전체 작업 동선을 격리 검증한다.
- [ ] web 제어기와 실제 Compose/외부 orchestrator의 인증된 제한 adapter를 연결하고 컨테이너별 배포·기동·자원 한도를 검증한다. 현 로컬 subprocess를 컨테이너 scale이나 다중 호스트로 취급하지 않으며 API에 Docker socket을 제공하지 않는다.
- [ ] 얼굴교체 등 비-CPU 실행환경의 실제 설치/health/활성화·축소 adapter를 연결한다. 현재는 미연결 상태를 정확히 보여주는 범위이며 실제 GPU/provider 호출은 별도 승인 대상이다.

### 독립 RabbitMQ 전달과 공통 의존성

- [x] Pika를 선택 extra로 분리하고 명시 namespace·환경변수 이름·TLS 설정만 받는 client를 구현한다. import/startup에서 연결·큐 선언·소비를 시작하지 않는다.
- [x] 명령 outbox의 확인 발행, 역할별 수신, 독립 CPU/S3 처리, 결과 DB 채택과 후속 명령 발행을 연결한다. 발행 실패의 동일 attempt 재전달·receipt/inbox 중복 방어·만료된 미발행 명령 거부를 검증한다.
- [x] CPU 작업 중 I/O thread의 heartbeat 처리, prefetch 1, 처리 후 confirm/ACK, SIGTERM drain과 poison/결과 불명 메시지 격리 경로를 구현한다. 채널 대역 검증을 실제 브로커 수용으로 부르지 않는다.
- [x] FFmpeg/FFprobe·폰트를 root media-base 한 stage로 관리하고 API·CPU·선택 legacy media가 공유하도록 Compose/Bake build graph를 연결한다. 기본 CPU와 AMQP 선택 이미지를 분리하며 heavy engine을 공통 base에 넣지 않는다.
- [x] CPU 역할별 AMQP profile·별도 private cache·외부 transport network·자원 한도 레시피를 제공한다. 브로커 service·운영 계정·자동 배포·Docker socket 제어는 추가하지 않는다.
- [ ] 별도 실행 승인 아래 실제 RabbitMQ 버전/인증·복수 consumer 분산·브로커 재시작/네트워크 단절·DLQ 전달을 수용한다. 실제 큐·GPU/provider를 기존 테스트에 연결하지 않는다.
- [ ] 원격 consumer와 웹 fleet의 observed health·enabled/disabled·컨테이너 수 제어를 연결한다. 현재 웹 fleet은 여전히 로컬 CPU subprocess용이며 AMQP 설정을 실제 인스턴스 준비로 표시하지 않는다.
- [ ] 장시간 큐 대기/작업의 lease 갱신·cancel 전달·운영 retry/HA 정책을 수용한다. 현재 짧은 명령 TTL·기존 CPU lease를 일반 분산 scheduler로 보고하지 않는다.

### 인프라 잔여 — GPU 작업으로 분류하지 않음

- [ ] 실제 S3 제품/버전의 조건부 쓰기·최소권한·소유자 prefix 정책·장애/보관 정책을 검증한다. 에뮬레이터를 MinIO 배포 완료로 취급하지 않는다.
- [ ] 운영 승인 범위에서 브로커·에이전트 인증과 다중 머신 전달·취소·장애 복구를 연결한다. 기존 큐는 소비하지 않는다.
- [ ] Loop/Fallback의 실행 정책과 추가 입력 binding을 구현한다. 현재 편집만 지원하는 경로는 실행 승인을 차단한다.
- [ ] 장시간/대용량 WebM 파생 생성을 durable 비동기 작업으로 확장한다. 현재 256 MiB/단계별 timeout 한계를 대용량 지원으로 보고하지 않는다.
- [ ] API의 legacy 호환 의존성을 해소한 뒤 단일 파이프라인을 최종 제거한다. 사용자 원본·자막·DB·키·백업은 삭제하지 않는다.
- [ ] 기존 legacy 테스트 실패와 전체 web lint/format 부채를 별도 정비한다. 안전 승인 조건을 낮춰 테스트를 통과시키지 않는다.

### 별도 실행 승인 필요

- [ ] 실제 GPU/모델/provider와 자격증명 resolver·비용·성능 검증.
- [ ] 운영 DB migration·사용자 데이터 이관·운영 배포와 실기기 수용 검증.

## 미확정 사항

스토리지 제품·배포 위치, 외부 실행 관리자, drain 제한시간/강제중지와 장애 후 소유권 인계는 [미확정 기획](ideation.md)에서 별도 결정한다. 원본·작업 이외의 관리 기능과 서버 전체 에이전트 제어는 관리자 전용이다. 현 CPU 기본 동작은 강제 종료가 아닌 drain이다.

## 관련 문서

- [구조](architect.md) · [실행 계약](../references/high/runtime.md) · [미확정안](ideation.md)
