# 현재 구현 태스크

## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 현재 상태

### 수용 소스의 운영 반영 — 단일 인코딩 대상 유지

- API·CPU 결과 수신·인코딩 전송 대기·엔진 결과 수신과 웹은 `c106bf097d6ea0f84af47590e3d6dd837db944f9` 수용본으로 반영했다. 실제 설치 모듈·HTTPS JS/CSS와 정상 인증 조회를 확인했다. 호스트 `26710eb0`와 기존 인코딩 실행기 이미지·ID·`restart=no`는 유지하며 API에 Docker socket을 주지 않는다.
- 운영 DB의 custom 백업을 별도 내부 PG에 복원한 뒤 migration018만 적용했다. 복원된 기존 46개 테이블의 원래 열 값이 동일했고, 원 작업을 바꾸지 않는 확인 기록 조회가 가능했다. 처리·전송 중 작업이 없음을 재확인하고 운영에도 018만 적용했다. 공용 자료함 WIP의 migration012는 포함하지 않았다. 백업·이전 이미지·설정과 롤백 경로는 비공개 운영 자료로 보존한다.
- 실제 관리자 인증으로 작업 처리 확인 API·목록과 제품 PC/390px 화면을 조회했다. #5는 별도 확인 기록의 **처리 여부 확인 필요**로 표시하며 원 작업의 `running`·실행·요청·전송·수신 사실은 그대로다. 준비 계획·관리자 판단·새 복구 작업·예약 해제는 모두 0건이다. 실제 #5의 복구 판단·재발행·초기화는 수행하지 않았다.
- 에이전트 화면은 정상 실행 1개·현재 작업 없음이며 #5 확인 목록으로 연결된다. 변경한 5개 프로그램 외 기존 15개 컨테이너와 기존 자료·설정/키·공용 자료함 WIP를 보존했다. 동일 영상 여정·운영 장애 주입은 반복하지 않았다. 설치 revision/모듈 SHA와 원 자료 대조·화면 증적은 저장소 밖 운영 인계에 보존한다.

### 구현·수용된 경계

- 단일 인코딩 실행기의 제품 시작/안전한 중지, 작업 #4의 실제 진행 작업 완료 후 정상 종료, #6의 144초 이상 DB 대기 후 명시 시작·동일 회차 1회 완료는 앞서 운영 수용됐다. 명령 TTL 60초는 늘리지 않는다. 전송 대기와 실제 처리 관측은 구분한다.
- 전송 전에 별도 트랜잭션으로 시도를 저장하고 전용 PG session guard를 유지한다. 결과 불명은 `unknown`으로 보존하며 재기동 후 자동 재발행하지 않는다. 실제 격리 PG/RabbitMQ 전달 후 저장 실패·프로그램 중단 경계는 `e565a9df`에서 수용·운영 반영됐다.
- 처리 확인은 원 회차에 연결한 별도 영속 case·고정 근거·권한/사유/위험 동의·개정 검사·판단 이력이다. 검증된 종료 근거 없이 수신 기록 부재나 lease 만료만으로 재처리하지 않는다. 정확히 인코딩 노드 1개이고 모델 binding이 없는 작업만 복구 준비 대상으로 허용한다.
- 같은 작업의 모든 회차와 미해결 전송을 확인하고 근거 변경을 이전 계획에 반영한다. 다른 미완료/미확정 회차나 `pending/sending/sent/received/unknown` 전송이 있으면 새 작업 연결·예약 해제를 막는다. 허용 시에도 원 상태를 바꾸지 않는 새 draft만 만들고 그 작업의 별도 계획·동의·실행 승인을 요구한다. 늦은 원 결과는 별도 격리·다운로드로 보존한다.
- 관리자 처리 확인의 기존 격리 PG20·브라우저6·합성 child 완료와 최종 범위 보강 PG20은 각각의 수용 범위다. 제어된 저장소/관측 어댑터 검사를 새 실제 MQ·물리 실행기 복구로 확대하지 않는다. 이번 운영 반영은 인증된 조회·설치·보존 확인이며 운영 복구 실행 시험이 아니다.

### 공용 자료 조회·다운로드 — 소스/격리 설치본 검증 완료, 운영 미반영

- 기존 공용 원본/FK/CAS WIP를 재사용하고 API의 공용 읽기와 화면을 연결했다. 다른 사용자 작업은 읽기 전용이며 계획/동의/실행/취소/복구/검수 변경 권한은 기존 실행 계정과 관리자 도메인의 기준을 유지한다. 모델/connection/credential 설정과 업로드 중인 개인 세션은 공유하지 않는다.
- 원본 업로더와 작업 생성·실행 계정을 구분해 표시한다. 원 자산 owner/SHA/CAS를 바꾸거나 실행자 쪽으로 원본을 복사하지 않는다. 새 작업의 입력에 검증된 source_owner_id를 고정하고 generated asset_owner_id FK로 원 자산에 연결한다. 기존 owner-CAS 참조는 그대로 읽는다. origin 표시는 입력에만 허용하고 결과에 넣는 위조 참조는 거부한다.
- 실제 pip 재설치한 API/CPU 패키지·별도 PG/local CAS에서 A 업로드→B의 원본 재사용/작업 생성/계획·동의·실행 UI→실제 encode/validate 완료→A의 결과 다운로드를 확인했다. 관리자 workflow 정의만 실제 API로 준비했으며 일반 모델/언어 선택 전체 제품 여정으로 확대하지 않는다. 일반 B의 다른 작업 읽기 전용과 관리자/credential 경로403, 비로그인401도 확인했다.
- PC/390px 실제 브라우저 6개 최종 관찰에서 원본/결과 다운로드 SHA·파일명, 실제 재생 종료/디코딩과 업로더/실행 계정 가시성을 확인했다. 두 노드 모두 attempt1/정상 종료, 원 자산1개·원 hash/실제 경로 동일·실행자 원본 복사0이다. S3 호환 참조/독립 subprocess는 별도 emulator 경계이며 새 실제 MQ/물리 실행기 수용이 아니다.
- 신규 설치본 관련 backend12개 통과(실패/오류/skip0, 기존 Starlette/httpx 경고1). 기존 처리 확인 projection이 공유 목록/상세에서 사라지는 회귀를 RED→GREEN으로 막았다. 018 적용 상태에012를 뒤늦게 추가해도 기존 snapshot/owner/원 자산이 보존됨을 별도 PG에서 확인했다. 이 검증은 운영012 적용이 아니다.
- 운영 앱/웹은 c106, 문서 기준점55a8058c이며 운영012·구버전 원본17개 이관·#5 복구·추가 슬롯·배치 이전·유료 호출은 수행하지 않았다. 운영 반영은 PM 검토 뒤 별도 범위다. 특히 새 origin 입력을 읽는 실행단 설치본과 고정 host pin의 호환 검토 없이 API만 앞서 교체하지 않는다.

### 공용 입력 운영 교체 전 호환성 — 검증 완료, 고정 대상 교체 gate 미해소

- 공용 읽기 d4a628a8은 PM 수용·App push 완료다. 운영 앱/웹 c106·호스트26710eb0·기존 실행 이미지6986은 변경하지 않았다.
- 별도 실제 TLS MQ/S3와 clean-source 후보 앱/CPU 이미지에서 기존 입력과 source_owner_id 공용 입력을 각각 encode→validate 완료했다. 두 작업 모두 각 노드 attempt1, 결과 inbox2/S3 receipt·원격 GET SHA/전체 decode 정상이며 최종 queue ready/unacked0이었다. A/B 브라우저 전체는 반복하지 않았다.
- 실제 기존 앱/CPU/model/GPU reader는 새 참조를 거부하고 후보4군은 기존·새 참조를 읽었다. 경로 탈출 origin/digest-key 불일치도 후보에서 거부했다. 모델/GPU는 기존 image layer/환경/entrypoint를 보존한 shared 설치본 읽기·검증이며 모델별 추론·engine-v2 MQ 전체를 다시 수용한 것은 아니다.
- 운영 백업을 별도 PG의 별도 DB에 복원해012만 적용했다. 기존51개 table의 기존 열 값·작업6개·immutable snapshot/원본/#5·제어 group/이력은 동일했다. 이전 c106 앱도012 상태의 기존 snapshot을 읽었지만, 새 공용 입력을 처리할 수 있다는 뜻은 아니다.
- 일괄 호환 범위는 앱4·CPU6·model2·GPU2·웹1의15개 프로그램/후보 image5종이다. 호스트 binary·collector·PG/MQ/S3 binary5개는 유지 가능하나 encode 재생성 시 새 container/image pin과 계약이 필요하다. API만 먼저 바꾸거나 옛 reader를 남기지 않는다.
- **즉시 운영 교체 불가:** 현재 exact container/image/label 검사와 group contract 등록은 새 target을 거부한다. 복원 DB의 같은 slot/다른 contract 등록도 충돌했고 원 group/이력은 보존됐다. 운영 pin을 완화/직접 수정하지 않았으며, 원/신규 target과 기존 요청·ACK·batch를 보존하는 권한/사유/CAS/감사 대상 교체 절차는 별도 설계·검토/승인 gate다.
- 승인 후 교체안은 신규 접수 중단→진행 처리/ACK/drain 정리→송신 앱/소비자 종료→최신 백업·복원 확인/승인된012→후보 준비→위 target 교체 gate→맞는 앱/웹·관측/결과 수신과 명시 시작/fresh ready 확인 순서다. 현재는 그 gate를 넘지 않는다.
- 새 공용 작업이 생긴 뒤에는 옛 앱/reader/FK로 단순 복귀할 수 없다. 합성 DB에서 옛 owner FK 재추가는 거부됐고 probe를 rollback했다. 신규 원본/작업/산출물/판단을 지우는 DB 전체 복원이나 owner 재배정 대신 origin-aware 설치본을 유지한 정지·forward fix/별도 승인 복구가 필요하다.
- 운영012/image/host 지정 변경·원본17개 이관·#5 복구·추가 슬롯·배치 이전·유료 호출은 수행하지 않았다. 원 source와 WIP21·실제 운영 자원 보존/정리 결과는 비공개 호환성 인계에 둔다.

### 남은 제품 범위

- [x] 인증 사용자 공용 원본·작업·결과 읽기/다운로드 API·UI와 격리 설치본 A/B 회귀.
- [ ] 위 공용 읽기 수용본의 운영 반영. 운영012·기존 원본17개 공용 이관은 별도 검토/승인 전까지 수행하지 않는다.
- [ ] 티켓별 manifest/중간·최종 object 배치와 기존 owner-CAS 읽기 호환, 보존 원본17개(29,073,982,271 bytes)의 공용 멱등 이관·대용량 보관/다운로드/재생. 기존 전체 SHA 확인을 반복하지 않으며 목록 등록만으로 완료하지 않는다.
- [ ] 등록 모델의 실제 API 요청·언어/모델 선택·유한 동적 폴백과 Gemini 키 등록 막힘 해결. 로컬 Whisper 시험을 제품 기본으로 대체하지 않는다. 유료 외부 호출은 별도 승인이다.
- [ ] 순수 제품 UI의 모델·언어 선택→티켓→승인→실행→결과와 모든 캔버스의 자동 정렬·연결선 정리·전체 보기.
- [ ] 다른 역할/두 번째 슬롯·실제 여러 컴퓨터 배치·부분 축소와 운영 fault/복구 수용. 현재 한 PC 배치를 최종 구조로 고정하지 않으며 API/DB/저장소/실행기 주소는 독립 설정한다.
- [ ] 실제 #5 처리 여부의 추가 영속 근거와 별도 복구 승인. 개별 TTL 만료는 미확정이며 수신 기록 부재를 종료 증거로 삼지 않는다. 자동 해제·재신호·원 기록 초기화는 금지한다.

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
- [x] 일반 계정의 관리 API 403·직접 URL 거부와 원본 업로드→관리자 제공 workflow 선택→작업 생성·승인→CPU 완료를 실제 production bundle 브라우저에서 검증한다. 작업 선택 전용 `/api/work-entry/*`와 불변 관리자 workflow 출처를 분리한다. 미디어는 인증 사용자에게 공용 읽기를 제공하되 실행 변경/개인 업로드 세션/credential 소유권은 공유하지 않는다.

### 에이전트 상세 운영 관리 — 단일 인코딩 운영 연결, 확장 별도

- [x] 기본 API·CPU 미디어 family·선택 GPU 도구 이미지 레시피를 분리하고 CPU 역할별 Compose profile을 정적 검증한다. API의 직접 미디어 처리용 FFmpeg는 남으며, 이미지 빌드·배포 완료로 보고하지 않는다.
- [x] 관리자 상세에서 서버 전체 종류별 사용 여부·목표 개수와 실제 private CPU subprocess 기동/종료·인스턴스 PID/상태/처리 수를 연결한다. 미연결 얼굴교체/모델 실행환경은 활성화 성공으로 표시하지 않는다.
- [x] 같은 종류의 두 실제 CPU 프로세스에 복수 작업을 분산한다. 인스턴스당 동시 처리 1개, revision 충돌·다른 controller 중복 기동 차단과 설정 변경 이력을 검증한다.
- [x] 비활성화·축소 시 신규 배정을 막고 예약된 작업의 완료 후 drain/종료한다. 선택 얼굴교체 미사용·CPU 기동/축소/종료와 일반 사용자 전체 작업 동선을 격리 검증한다.
- [x] 기존 인코딩 대상 1개의 고정 pin·제한 호스트와 제품 시작/안전한 중지를 운영 연결한다. API에는 Docker socket/임의 대상 조작 권한이 없다.
- [ ] 다른 역할·추가 슬롯/외부 orchestrator의 인증된 제한 adapter와 자원 한도·여러 컴퓨터 제어를 별도 수용한다. 단일 대상 결과를 전체 scale 수용으로 확대하지 않는다.
- [ ] 얼굴교체 등 비-CPU 실행환경의 웹 운영/축소 adapter를 연결한다. 목적지의 수동 Compose 기동·실 GPU 역할 수용과 웹의 observed state/scale 제어를 구분한다.

### 독립 RabbitMQ 전달과 공통 의존성

- [x] Pika를 선택 extra로 분리하고 명시 namespace·환경변수 이름·TLS 설정만 받는 client를 구현한다. import/startup에서 연결·큐 선언·소비를 시작하지 않는다.
- [x] 명령 outbox의 확인 발행, 역할별 수신, 독립 CPU/S3 처리, 결과 DB 채택과 후속 명령 발행을 연결한다. 발행 실패의 동일 attempt 재전달·receipt/inbox 중복 방어·만료된 미발행 명령 거부를 검증한다.
- [x] CPU 작업 중 I/O thread의 heartbeat 처리, prefetch 1, 처리 후 confirm/ACK, SIGTERM drain과 poison/결과 불명 메시지 격리 경로를 구현한다. 채널 대역 검증을 실제 브로커 수용으로 부르지 않는다.
- [x] FFmpeg/FFprobe·폰트를 root media-base 한 stage로 관리하고 API·CPU·선택 GPU 도구가 공유하도록 Compose/Bake build graph를 연결한다. 기본 CPU와 AMQP 선택 이미지를 분리하며 heavy engine을 공통 base에 넣지 않는다.
- [x] CPU 역할별 AMQP profile·별도 private cache·role별 최소 broker 권한과 bootstrap mount를 제공한다. `infra/compose.yaml`에 별도 opt-in broker/PG/S3 설치 구성을 제공하며 startup 자동 초기화·자동 consumer·Docker socket은 없다.
- [x] 실제 격리 TLS broker 인증·역할별 독립 consumer/결과 제어기·후속 노드 전달·중복 명령/DB 결과·ACK 후 unacked=0·poison DLQ를 수용한다.
- [ ] 같은 role의 복수 remote consumer 분산, broker 재시작/네트워크 단절·HA와 장시간 운영을 별도 수용한다. 기존 운영 큐·GPU/provider는 테스트에 연결하지 않는다.
- [x] 상태 전용 collector/PG의 실제 worker 관측과 단일 인코딩 제어를 제품에 연결한다. 관측 수용과 다른 역할·다중 슬롯 제어 수용은 구분한다.
- [x] 단일 인코딩 DB 대기·명시 시작과 영속 전송 시도/미확정 자동 재발행 방지를 수용한다.
- [x] 별도 관리자 처리 확인·보류·새 draft 연결·늦은 원 결과 격리 및 단일 노드/다른 회차 범위 검사를 반영한다. 실제 #5 복구 실행은 포함하지 않는다.
- [ ] 일반 장시간 작업의 lease 갱신·다중 머신 cancel/HA·운영 장애 복구를 별도 수용한다. 현재 범위를 일반 분산 scheduler로 보고하지 않는다.

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
- [x] 실사용자 최초 관리자·제품 계정 합성 영상 E2E는 위 실제 제품 작업 #1 범위로 수용했다.
- [ ] 공용 원본 이관, 순수 UI-only 고정 모델 언어 선택 및 기타 미수용 범위는 별도로 남긴다. 개인 소유권 배정은 현재 요구가 아니다.

## 미확정 사항

스토리지 제품·배포 위치, 외부 실행 관리자, drain 제한시간/강제중지와 장애 후 소유권 인계는 [미확정 기획](ideation.md)에서 별도 결정한다. 원본·작업 이외의 관리 기능과 서버 전체 에이전트 제어는 관리자 전용이다. 현 CPU 기본 동작은 강제 종료가 아닌 drain이다.

## 관련 문서

- [구조](architect.md) · [실행 계약](../references/high/runtime.md) · [미확정안](ideation.md)
