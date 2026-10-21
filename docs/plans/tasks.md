# 현재 구현 태스크

## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 현재 상태

### 사용자 재확정 요구와 다음 구현 순서 — 2026-10-21 19:49 KST

- 단일 직접 writer는 Windows의 혜윤, 혜지는 요구사항/결과 검토와 GitHub App push를 담당한다. 개발 checkout `C:/Users/skygg/dev/mediagent-s2`, `renewal`, 시작 HEAD `625bd9289649321a92f1a6469912d3a44ea49615`. 기존 문서 WIP·미추적 evidence와 원본/DB/키/백업을 보존한다.
- 현재 완료는 고정 로컬 영어→독일어 제품 job의 UI/API 혼합 실행과 다운로드/재생이다. 일반 provider 실행·순수 UI-only 생성·공용 자료함·티켓별 물리 저장·실제 원격 agent 관리가 완료됐다는 뜻이 아니다. 현재 배포는 `625bd928…`이며 새 구현의 배포/제품 UI 검증과 분리한다.
- [ ] 1차: 실제 독립 agent 관측을 화면에 연결한다. 연결/준비/추론 성공을 혼동하지 않고 관측 실패는 unknown, 미지원은 unsupported로 구분한다. 현재 API credential의 passive queue 조회는 실제 HTTP가 아닌 AMQP channel 403으로 거부됨을 확인했다. 권한을 임의 확대하거나 초록색 표시로 대체하지 않는다. 관측 연결과 원격 start/stop/scale 제어의 완료를 별도로 기록한다.
- [ ] 2차: 인증된 공용 원본/작업/결과 조회·사용·다운로드와 업로더/실행자 기록을 연결한다. credential·관리 API의 보호는 유지하며, 구버전 원본을 개인 계정 소유함으로 옮기는 이전 제안은 폐기한다.
- [ ] 3차: `originals/{original_id}` 및 `tickets/{ticket_id}`의 단계별 파일/manifest를 실제 object 저장에 연결하고 기존 owner-CAS 읽기를 보존한다. 단순 경로 설명이나 PG 목록만으로 완료 처리하지 않는다.
- [ ] 4차: 기존 원본17개를 이력 복원 없이 공용 목록에 이관한다. 대용량 보관·재생·다운로드와 실행 용량 제한을 분리하고 전체 SHA·멱등 재실행·실제 읽기를 수용한다.
- [ ] 5차: connection/model/credential→실제 capability별 provider 요청과 태스크별 동적 폴백 체인을 연결한다. 폴백0개 허용·추가/삭제/재정렬·snapshot pin·A실패→B실패→C성공/전부실패/폴백없음/취소중단·오류별 전환 정책·후보별 능력/인증/비용 확인·실제 시도 순서/최종 모델 표시를 수용한다. 유료 외부 호출은 별도 승인 전에는 실행하지 않는다.
- [ ] 6차: 언어/모델/폴백 선택→원본/workflow→티켓→별도 승인/실행→중간/최종 결과를 순수 제품 UI로 검증한다. 다른 로컬 모델 대체나 API 우회 결과를 UI 완료로 보고하지 않는다.

#### 1차 수정 묶음 A — 관측/제어 오표시 제거

- 혜지의 실제 diff/manifest 검토로 부분 수용됐다. 후속 지적에 따라 AMQP mode를 runtime 값과 분리해 조회 실패 중에도 전용 패널을 유지하고 로컬 활성화/개수 form이 나타나지 않도록 보완했다. 목록도 `/api/admin/agents`의 같은 상태 해석을 사용한다. 실제 실패를 재현한 후 보완했고 PC/phone 목록·상세/실패/복구 계약24건을 통과했다. 변경 frontend lint/format·build·Node test도 통과했다. telemetry/원격 제어 완료와 운영 배포는 별도로 기록한다.

- `RabbitClient.observe`는 명시 role의 기존 queue를 passive 조회만 한다. consume/get/publish/queue 생성·삭제는 하지 않는다. 403은 endpoint/인증정보 없이 고정된 관측 권한 오류로 구분한다.
- broker 배포의 `/api/admin/agents`와 상세·설정 경로를 로컬 `Fleet` 대신 새 read-only `BrokerFleet`에 연결했다. 로컬 subprocess 모드의 Fleet은 유지한다. CPU와 engine v2를 분리 관측하고 전처리는 두 family를 보존한다. 일부 family 조회 실패도 전체 connected로 합성하지 않는다.
- connected/disconnected/unknown/controller/unsupported를 구분하며 관측 불가는 consumer0/중지로 바꾸지 않는다. broker 연결 수로 PID·개별 worker 생존·추론 readiness·목표 replica를 합성하지 않는다. DB 유효/만료 lease와 누적 완료를 별도 집계로 표시한다. 원격 제어 adapter가 없으므로 start/stop/scale form은 숨기고 서버 설정 요청도 거부한다. 제어 기능 완성이 아니다.
- RED→GREEN: passive 관측 메서드 부재, 403 구분, API의 잘못된 로컬 fleet 선택, UI 상태 helper 부재/unknown의 잘못된 숫자 노출을 실제 실패 후 수정했다. 새 단위12개 통과. 확장 격리 transport 회귀는 **21 passed/3 skipped**, PG를 요구한 3개는 network-none 실행에서 미수행이고 Starlette 의존성 경고1개가 있었다. 처음 선택한 운영 API image에는 pytest가 없어 실패했으며 기존 acceptance image로 재실행했다.
- web 전체 Node test **47/47 통과**, production build 통과, 변경 frontend 파일의 ESLint/Prettier 통과. 전체 lint는 미변경 파일의 80 errors, 전체 format은 미변경3파일 부채로 실패했으며 고치거나 숨기지 않았다. 정본 밖 private 로그를 보존한다.
- PC1440/phone390의 격리 production-bundle UI 계약 **14 cases/0 failures**: 5상태와 연결 후 조회실패/복구를 각각 검사해 stale connected 제거·오류 해소·가로 overflow 없음·미연결 제어 미노출을 확인했다. fixture capability의 verified_uploads 누락 때문에 초기 browser 검증이 가드 화면에서 실패했던 기록은 별도로 보존했고, fixture 보정 후 전부 재실행했다. 실제 제품 worker readiness/UI 수용으로 확대하지 않는다.
- 새 source를 격리 process로 실행해 실제 PG/AMQP를 read-only 조회했다. analyze/transcribe는 실제 관측403→unknown, 누적 완료1을 각각 확인했고 review=controller/decision=unsupported였다. 운영 source·credential·broker 권한·DB 행·컨테이너는 변경하지 않았다. 현재 제품 배포는 여전히 `625bd928…`다.
- 검토/다음 구현: 기존 controller credential에 광범위 queue 접근을 추가하는 대신, 명시 read-only 관측 credential/별도 telemetry 경로의 최소권한 경계를 검토한다. 실제 worker identity/생존/작업 heartbeat·원격 제어가 연결돼야 1차 전체 수용이다. 이번 WIP의 독립 검토·운영 배포는 아직 미완료이며 다른 Agent/Codex를 reviewer로 새로 실행하지 않는다.

2026-10-20/21 사용자가 Windows 목적지의 renewal 배포·SQLite 이관·새 consumer·로컬 GPU/모델과 합성 영상 검증을 승인했다. 아래 기존 격리 수용과 목적지 실제 실행을 구분한다. 기존 Worker·기존 큐 소비, 외부 유료 provider, 공개 ingress·registry publish·VPS 분할은 승인 범위가 아니다.

### Windows 목적지 실행 체크포인트 — 전체 완료 아님

#### 장애 후 복구 스레드 재확인 — 2026-10-21 KST

- Windows 명령과 브라우저 도구 응답을 실제 확인했다. 이전 empty 응답의 원인을 전사 장애로 확정하지 않는다. 모델/공급자/OAuth/gateway/다른 프로필은 변경하지 않았다.
- 개발·원래 설치 checkout 모두 `renewal`, HEAD `625bd9289649321a92f1a6469912d3a44ea49615`다. 최초 조회의 로컬 추적 ref 대비 ahead 1은 혜지의 canonical 일반 push 완료 통보 후 두 checkout에서 각각 fetch/readback하여 해소했다. 두 곳 모두 `HEAD == origin/renewal == 625bd9289649321a92f1a6469912d3a44ea49615`를 확인했다. 개발의 미추적 evidence와 설치의 `docker-compose.renewal.pg.json`을 보존했다. repo명이 명령줄에 포함된 기존 host writer/build는 발견하지 못했지만, 이름만으로 다른 Codex/앱 프로세스의 작업까지 부재라고 단정하지 않는다.
- 대상 이미지 14개 container가 모두 위 revision label과 일치하며 running/restart 0이다. API/web와 infra PG/broker/object health는 healthy다. 기존 사설 HTTPS와 loopback 진입점은 각각 HTTP200이며 재배포하지 않았다. 옛 Worker 두 개는 exited 상태를 유지한다.
- 복구 직후 실제 HTTPS와 검증 브라우저 모두 최초 관리자 미설정이었다. 사용자 설정 완료 후에는 `setup_required=false`이지만 검증 브라우저만 미인증임을 따로 확인했다. 당시 vault 항목 부재와 `prompt_unavailable`로 중단했으나, 이후 사용자가 vault에 기존 실제 계정을 저장했다. 19:08 KST vault fill→로그인 제출→세션 재조회로 **실제 관리자 인증**을 확인했다. 채팅 비밀번호의 직접 입력·가짜 계정·인증 우회는 사용하지 않았다.
- broker의 기본 vhost 조회 빈 결과를 운영 큐 부재로 해석하지 않았다. 실제 `/mideagent`에는 consumer 연결 큐 12개가 있으며 각 consumer 1개, 해당 큐 ready/unacked는 모두 0이다. 과거 격리 acceptance namespace의 dead queue 메시지 2개는 재처리/삭제하지 않았다.
- 사설 HTTPS `/healthz`는 HTTP200(text/plain), 미인증 `/api/accounts`·`/api/legacy/summary`는 각각 HTTP401이다. 첫 curl probe는 Windows 출력 장치 쓰기 오류(exit23), 후속 health probe는 응답을 JSON으로 가정한 검사 코드 오류(exit1)가 있었다. Python HTTP 재조회와 content-type/상태 검사로 각각 확인했으며 서비스 장애로 분류하지 않는다.
- bundle 재생성·재전송, migration 재실행, 기존 초장문 세션 continue, 다른 Agent/Codex 대체를 수행하지 않았다. 기존 격리 음성/GPU 수용을 이번 제품 계정 성공으로 확대하지 않는다.

#### 실제 제품 계정 영상 E2E — 2026-10-21 저녁 KST

- 기존 합성 음성 `spoken-fixture.mp4`를 실제 제품 UI로 업로드했다. 자산 `7f0b0ded68ee476387e74abe3a5b737e`, 원본 84,409 bytes/SHA `9843beef198559046399b077ffa91d92aacbb93bedacbbcae59fb9db72e931fc`, 640×360/25fps/12.6초이며 API 재조회에서 content_verified와 WebM ready를 확인했다.
- 제품 API로 workflow `f95a30fb3510483b94da73fafa7f63fe` r1, **제품 E2E · 영어 음성 → 독일어 번인 · 2026-10-21**을 신규 저장·재조회했다. 격리 fixture에서는 8단계/10연결의 정의 구조만 재사용했으며 격리 schema의 job/result/승인/전사·번역 결과를 복사하지 않았다. 제품 UI의 원본·저장 workflow 선택과 지원 runtime 조회를 확인했다.
- 새 작업 화면의 현재 언어 기본값은 auto/ko이므로 이번 고정 모델 수용은 제품 API에 `source_language=en`, `target_language=de`를 명시해 preview→create했다. **순수 UI-only 언어 설정 동선까지 완료한 검증은 아니다.** 이후 실제 작업 상세 UI에서 실행 계획 확인→동의 저장→실행 요청을 각각 수행했다. 계획은 ready이며 paid_roles는 비어 있고 verified_no_external_calls였다.
- 제품 **작업 #1**, job `77f979c398234344a650e813df890b55`, status completed/revision19/generation1. 분석→오디오 추출→필터/VAD off 전처리→Whisper tiny.en 전사→OPUS-MT en→de 번역→자막 생성→번인→검증의 8개 run이 모두 attempt1/completed/error 없음이다. GPU VAD/FaceFusion은 이 제품 job에 포함하지 않았다.
- API뿐 아니라 실제 PG `public`의 해당 owner/job을 read-only transaction으로 대조했다. 8개 node_runs 완료, artifact9, 결과 inbox8을 확인했다. 명령 outbox CPU v1 6개·engine v2 2개 모두 published다. 별도 accepted 이벤트8은 미발행 상태로 남아 있으므로 전체 outbox가 비었다고 하지 않는다. 운영 consumer 연결 큐12/consumer12, ready0/unacked0을 확인했다.
- 실제 제품 다운로드 MP4 94,627 bytes/SHA `0848c896f8a050f53fccfe326b137f54da4df2d7498b55d64344dd1b2a275c71`, WebM 113,843 bytes/SHA `7c69ca4c0ea1f943be1b78698fd542844144cbd0fe1579cda82f130ed89d6f9f`를 저장하고 서버 reference와 해시를 대조했다. 내려받은 MP4 ffprobe는 exit0, H.264/AAC/640×360/25fps/12.6초다. 제품 출력 WebM player를 무음으로 처음부터 끝까지 재생해 ended=true/12.607초/315frames/drop0/decoder error 없음, 독일어 번인 화면을 확인했다. 음질 청취·번역 품질 전반 수용과는 구분한다.
- 결과 위치: 제품 작업 목록의 **#1 → 영상 인코딩·번인 노드 → 작업 결과 원본 받기/WebM 받기/플레이어**. API job·PG readback·MQ·재생 증적과 다운로드는 비공개 운영 디렉터리에 보존했다. 배포 revision `625bd928…`와 WIP/기존 원본/SQLite/키/백업을 유지했으며 재배포·migration·전체 회귀·외부 유료 호출·옛 Worker 재시작은 수행하지 않았다.
- 브라우저 도구의 최초 재연결에는 port 파일 접근 오류가 있었으며 파일 부재/기존 daemon 조회 후 1회 재연결은 성공했다. 최종 전체 페이지 재열기에서는 인증 쿠키가 없는 상태와 HTTP401을 한 번 관찰했다. vault 재로그인 후 **동일한 기존 완료 job의 HTTP200/8개 완료**를 다시 확인했고 job은 재실행하지 않았다. 이 세션 소실 원인은 아직 browser-harness/제품 중 어느 쪽인지 확정하지 않았으며 장기 세션 지속성 수용으로 보고하지 않는다.

#### 실제 object storage·구버전 원본 점검 — 2026-10-21 저녁 KST

- 제품 작업 #1의 원본/중간물/결과/원본·결과 WebM reference12개를 기준으로 고유 object11개를 **원격 GET**하여 크기·SHA 전부 일치 확인했다. 원본 추출 audio와 off 전처리 audio는 같은 CAS bytes를 공유한다. 8개 attempt의 claim.json/result.json도 모두 원격에서 읽혔다. 실제 배치는 owner별 CAS `prefix/owner/blobs/SHA256`, attempt receipt는 `prefix/owner/attempts/attempt_id`이며, job/노드/파일 관계는 PG에 있다. 작업별 사람이 읽는 파일명 폴더로 복제된 구조는 아니다.
- 사용자는 구버전 작업 이력 복원이 아니라 **보존 원본을 현재 계정의 원본 목록에 노출**하는 것을 요청했다. 이력은 복원하지 않되 기존 이력·백업·파일 삭제 요청으로 확대하지 않는다.
- 옛 Worker mount에서 실제 원본 경로를 재발견했다. 기존 원본17개/29,073,982,271 bytes(29.074 GB)가 존재하며 각 파일 전체 SHA와 크기를 기존 migration snapshot에 대조해 **17개 전부 일치**했다. 원본 손실이 아니라 owner-scoped native asset 등록 미완료다. 이전 일부 backup 경로에는 16개만 있으므로 그 사본을 전체 정본으로 사용하지 않는다.
- 17개 모두 현 `MAX_CONTENT=256 MiB`를 넘는다. 제한은 업로드 폼뿐 아니라 ContentStore/S3 reference 검증에도 적용된다. 현재 코드에서 PG 행만 등록하거나 한 군데 제한만 바꾸면 실제 읽기/다운로드/실행 경로가 불일치한다. 이번 점검에서 native asset 가짜 등록·상태 주입·제한 monkeypatch·원본 이동/삭제는 하지 않았다.
- 다음 작업은 원본 보관·다운로드 전용 대용량 경로와 명시 owner/불변 SHA·멱등 import를 분리하고, 현재 처리 용량 제한·WebM 미준비 상태를 정직하게 유지하는 것이다. 이는 배포 `625bd928…` 변경이 필요한 구현 범위이며, 목록 노출/대용량 원본 이관은 아직 완료가 아니다. 원격 object 점검과 원본17개 무결성 inventory는 비공개 운영 증적에 보존했다.

- [x] 원본 1,587파일의 SHA snapshot, SQLite 3개 무결성, private 설정/키·정의·기존 ref/WIP/stash 보존.
- [x] `legacy/unassigned` 관리자 전용 immutable archive importer와 009 migration. 작업42(완료31/실패11, 내부25/사용자17), 인덱스42/14의 독립 namespace, 자산17·정의1·비활성 설정1을 분리한다. dry-run117 → 실제117 → 재실행 추가0을 대조했다. 개인 계정/새 실행 receipt/승인을 합성하지 않았다.
- [x] PG dump를 실제 별도 임시 DB에 restore하고 종류·상태·내부 구분·native jobs0·physical runtime4를 대조했다. 임시 DB만 정리하고 원본 SQLite/미디어·실제 DB/volume은 보존했다.
- [x] 기존 사설 443→loopback5177 경로에 API/web를 교체하고 PG/TLS RabbitMQ/S3를 기동했다. API/CPU/model/GPU는 UID10001·read-only root·역할별 bootstrap mount를 사용한다. 기존 secret bytes는 유지하고 controller 권한/참조 JSON과 새 역할만 추가했다.
- [x] CPU 정규화(`audio_filter=off`, `vad_mode=off`)와 별도 model/GPU v2 MQ를 구현했다. CPU v1에 GPU/model 역할을 끼워 넣지 않았다.
- [x] 실제 Whisper tiny.en CPU int8 전사, OPUS-MT en→de CPU int8 번역, NVIDIA Marblenet CUDA VAD, FaceFusion CUDA swapper/NVENC self-swap과 S3 receipt 재전달을 검증했다. 모델·GPU별 새 attempt의 실제 TLS MQ command/result/confirm/ACK도 별도 수용했다.
- [x] 합성 음성 영상의 분석→추출→전처리→전사→번역→자막→번인→검증을 실제 S3/TLS MQ/격리 PG에서 완료했다. 내려받은 12.6초 영상의 SHA/ffprobe와 실제 브라우저 끝까지 재생(315 frames, decoder error 없음)을 확인했다. 이 작업은 **disposable schema 검증**이지 제품 계정의 완료 작업이 아니다.
- [x] 별도 CPU 6개·model 2개·GPU 2개 consumer와 결과 소비자2개가 목적지의 독립 큐에 각1개 연결됐음을 확인했다. 실제 입력/출력 수용과 단순 connection 수를 구분한다.
- [x] **실제 최초 관리자 설정/검증 브라우저 로그인 → 제품 원본 등록/저장/실행 → 제품 job/다운로드/플레이어 수용**. 위 제품 작업 #1의 영어→독일어 합성 영상 UI/API 혼합 경로에 한정한다. 일반 사용자 role·임의 언어·순수 UI-only 생성 동선 전체를 수용했다고 하지 않는다.
- [ ] 사용자 요청의 구버전 원본17개를 인증 사용자 공용 자료함에 멱등 이관하고 원본 목록/보관/다운로드/재생을 검증한다. 업로더는 행위자 기록이며 개인 자료함으로 분리하지 않는다. 작업 이력 복원은 요구 범위가 아니다. 17개 전부 기존 SHA 보존 확인, 전부 256 MiB 초과이므로 원본 전용 대용량 지원이 선행되어야 한다.
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
- [x] 실사용자 최초 관리자·제품 계정 합성 영상 E2E는 위 실제 제품 작업 #1 범위로 수용했다.
- [ ] 공용 원본 이관, 순수 UI-only 고정 모델 언어 선택 및 기타 미수용 범위는 별도로 남긴다. 개인 소유권 배정은 현재 요구가 아니다.

## 미확정 사항

스토리지 제품·배포 위치, 외부 실행 관리자, drain 제한시간/강제중지와 장애 후 소유권 인계는 [미확정 기획](ideation.md)에서 별도 결정한다. 원본·작업 이외의 관리 기능과 서버 전체 에이전트 제어는 관리자 전용이다. 현 CPU 기본 동작은 강제 종료가 아닌 drain이다.

## 관련 문서

- [구조](architect.md) · [실행 계약](../references/high/runtime.md) · [미확정안](ideation.md)
