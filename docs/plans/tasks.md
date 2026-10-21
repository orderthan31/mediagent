# 현재 구현 태스크

## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 현재 상태

### 실제 RabbitMQ·제품 티켓 제어 연결 — 격리 수용 자료, 운영 미적용

- 고정 대상 제어 21경로는 PM 수용 후 `6e78e7e4147545f4f52f37712f2fb1a0829ab922`로 분리했고 App push 완료를 전달받았다. 이 소스의 동일 시험은 반복하지 않았다. 후속은 별도 source diff이며, 운영 bootstrap 등록·제어 활성화는 계속 금지한다.
- 새 TLS RabbitMQ/S3·전용 PG에서 실제 CPU encode consumer 두 개와 validate consumer, 결과 소비기·상태 collector를 연결했다. 각 consumer의 명령/상태 credential을 분리하고 상태 발행 주소는 개별 ID에 고정했다. 실제 broker에서 다른 ID의 상태 exchange 발행이 403으로 거부됐다. 기존 역할별 권한/운영 MQ는 바꾸지 않았다.
- 실제 제품 API의 업로드·불변 workflow·티켓 생성·계획/동의/승인·run으로 티켓 #1/#2를 처리하고 제품 버튼으로 0→1→2→0을 조작했다. 합성 영상의 실제 FFmpeg 입력을 격리 이미지에서 실시간으로 제한했으며 원래 FFmpeg binary SHA는 보존했다. 이는 모델 대체나 상태 주입이 아니다. 두 티켓은 각 ID/boot/attempt와 연결된 채 중지 중을 유지했고, 신호 발행 후 30초를 넘어서도 실제 실행 중이었다. 최종 encode→validate 완료·원본 산출물 다운로드 SHA와 45.056초 영상을 확인했다.
- 종료 신호와 드레인 대기를 분리한 durable journal을 추가했다. CLI ACK를 sent로 기록한 뒤 제어기를 강제 중단했을 때 TTL 후 UI는 개수/작업/제어 결과를 확인 불가로 표시하고 조작을 막았다. 재기동한 제어기는 같은 요청의 sent action을 재발행하지 않고 관측만으로 정상 종료를 확정했다. action별 issue_count는 1이며 실제 대상은 exit0이다. 대기하던 #3은 명시적인 제품 시작 조작 뒤 처음 처리돼 완료됐고 다운로드 SHA도 일치했다. 당시 티켓 DB의 running은 명령 예약/발행 상태이며 실제 소비 시작 증거는 별도 worker busy/attempt 기록이다.
- 신규 범위 PostgreSQL/신호/재기동/티켓 binding 테스트 9 passed와 실제 PC/390px 브라우저 증적을 확보했다. 첫 PATH 기반 실시간 래퍼는 자식의 제한 환경에 전달되지 않아 긴 작업 gate가 실패했다. 그 실패를 보존하고 격리 이미지의 wrapper/interpreter 배치만 고쳐 실제 긴 작업을 검증했다. 제품의 환경 필터는 완화하지 않았다.
- **남은 경계:** 신호 발행 직전/직후 ACK 영속화 사이에 중단된 issuing/unknown은 자동 재신호·성공 처리하지 않고 봉쇄한다. 이 모호한 구간의 운영자 확인/복구 절차는 미구현이다. 비정상 종료도 unknown으로 남긴다. 새 signal-only adapter는 `restart=no`인 사전 고정 슬롯만 허용하며 운영의 restart 정책을 변경하지 않았다. 운영 대상 등록·정책/복구 수용·배포는 별도 PM 검토/승인 전까지 하지 않는다. 공용 자료함과 기존 CAS/FK WIP는 후속 이미지에 섞지 않았다.

### 실제 제어 연결 — 고정 대상 격리 API/UI 체크포인트, 운영 적용 전

- `create_app(remote_control=...)`의 명시 opt-in으로 관리자·CSRF·요청 ID 멱등성과 revision/CAS·처리 중 요청 덮어쓰기 거부를 연결했다. PostgreSQL에 먼저 요청을 저장하고 별도 호스트 제어기가 고정 container/image/label/worker ID만 조작한다. API에는 Docker CLI/socket·호스트 설정을 주지 않으며, API DB 역할도 관측값·대상 계약·요청 완료 상태를 쓸 수 없다. 기본 bootstrap은 바꾸지 않았다.
- 제품의 같은 관리 API와 production bundle 버튼에서 **실제 임시 대상 0→1→2→1→0**을 실행하고 매번 API 재조회와 화면의 실제 개수 반영을 기다렸다. 원래 요청 재전송은 같은 revision을 반환하고 stale revision·일반 사용자·임의 container ID 입력을 거부했다. PC/390px 모바일을 확인했다.
- 합성 작업 처리 중 2→1 축소에서 해당 ID의 현재 작업을 유지한 채 중지 중을 표시했다. 추가 2→0 시험에서는 제거 대상 모두에 병렬로 종료 요청을 보내 각 작업 완료를 기다렸다. 작업 중인 실제 FFmpeg 영상은 완료·bytes/SHA 보존, 뒤에 넣은 작업은 배정되지 않은 queued 상태, 대상 종료 코드0을 확인했다. 제한시간 SIGKILL이나 결과 불명 요청 자동 재신호는 없다.
- **검증 대상은 전용 PG와 제한 역할을 쓰는 합성 처리용 컨테이너다.** 이는 실제 Docker 대상에 대한 제품 제어 경로의 수용 자료이지 운영 RabbitMQ consumer·제품 DAG/ticket·운영 에이전트 축소 수용이 아니다. fixture의 작업번호·PG bytea 산출물을 제품 티켓/CAS 저장 완료로 취급하지 않는다. 기존 공용 자료함·인스턴스 exchange WIP는 섞지 않았다.
- 신규 Python/PG/API 및 기존 primitive 범위 8 passed, 실제 브라우저/프로세스 증적을 확보했다. 운영 제어 전 소스·격리 결과를 혜지에게 검토받는다. **운영 웹 `6eb22e2`, API/agents `6986b614`·`manageable=false`는 유지**한다. 실제 브로커 인스턴스별 인증/collector 연결·운영 bootstrap/고정 슬롯 provisioning·장시간/제어기 중단의 결과 불명 복구 정책은 미완료이며 검토 없이 운영 제어를 켜지 않는다.

### UI 묶음 운영 반영 완료 — 실제 제어 연결은 별도

- 혜지의 수용/App push 후 원격 `6eb22e2308cc955f24ebc38614435168d522fe87`를 읽고 해당 clean archive의 웹만 반영했다. 기존 소스 시험·재제출·재push는 반복하지 않았다. 실제 HTTPS PC/모바일에서 encode ID `81831977b4214488b19fb78fca17c213`의 축약/펼침과 정상·1개·작업 없음, 일반 작업 셀 이동, 처리 에이전트 목록 분류, 원본/산출물 WebM 안내 삭제와 다운로드 링크 보존을 확인했다. 브라우저의 실제 GET 지연 중 media skeleton과 응답 후 복귀도 확인하고 지연 설정은 복구했다. HTTPS JS/CSS는 실행 image bytes와 일치한다. 비웹17개·bootstrap96파일·기존 WIP42경로·롤백을 보존했으며 API/에이전트는 `6986b614…` 그대로다. 실제 API의 `manageable=false`도 재확인했다. 이번 배포로 제품 start/stop/scale이 새로 연결된 것은 아니다.

- 소스 `67b493bceb4aa71fae5dcaa3e639534550db64f0`의 28경로만 분리했다. 단일/복수 실제 ID 필드의 축약·전체 펼침·실제 클립보드 복사, 각 ID와 상태/현재 작업 결합, 관측 실패 시 ID/마지막 응답 보존과 과거 busy 숨김을 격리 PC/390px 브라우저로 확인했다. 모바일은 가로로 상태가 잘리지 않도록 카드로 표시한다. 이는 계약 fixture UI 수용이며 운영 다중 인스턴스·scale 수용이 아니다.
- 작업 행 일반 셀 클릭·Enter·Space 이동과 별도 버튼/체크박스·수정키의 비간섭을 확인했다. 처리 에이전트 목록에서 제어/사람 검수를 제외하고, 기존 workflow 노드는 보존하면서 추가 메뉴·편집/실행 canvas에 일관된 제어/사람 검수 아이콘을 적용했다. 분류 메뉴 조작으로 위치/연결/실행 설정을 저장하지 않았다.
- 목록·표·플레이어/정보·폼·캔버스·실행 현황별 초기 GET 스켈레톤을 적용했다. 실제 지연·첫 실패·갱신 지연/실패/복귀 fixture에서 빈 목록과 구분하고 기존 목록을 유지하는 것을 확인했다. 기존 PG에서 미제공인 시스템/역할 설정 경계는 열지 않았다. legacy 설정·저장 공간·검수·자막 페이지의 placeholder 교체는 소스/build 범위이며 해당 legacy 제품 여정 전체 수용은 아니다.
- 설치 API `6986b614` + 별도 일회용 PG/tmpfs CAS로 일반 사용자 PC/모바일의 중단→동일 세션 재개→등록을 다시 실행했고, **완료 후 reload/이동 없이 원본 목록 자동 갱신**과 UI 다운로드 SHA 일치를 확인했다. 운영 재시험이 아니며 backend WIP overlay·가짜 성공 응답은 없었다. 일회용 자원은 정리했다.
- 배포 전 renewal typecheck/build·Node50·격리 UI14 묶음·broker UI36 통과. 변경 포맷 통과, 신규 lint 오류0이며 기존 3파일의 17개 lint 오류는 baseline 비교로 분리했다. source의 부모에 수용/push된 WebM 삭제 `99e4a7b`도 함께 반영됐다. 현재 운영 웹은 `6eb22e2`, API/에이전트는 `6986b614`다. 실제 제어 WIP와 공용 자료함 WIP는 이번 소스/이미지에 포함하지 않았다.

### 업로드 복구 운영 반영 — 2026-10-22

- 혜지의 소스 수용/App push 후 `origin/renewal == ad38393b5a789dc1a1b69488e914f7a30e5d6f2f`를 읽어 확인했다. 해당 clean archive의 웹만 교체하고 실행 image ID/revision과 실제 HTTPS JS/CSS bytes 일치를 확인했다. API·에이전트는 `6986b614…` 그대로이며 비웹 running17개 ID/image/start/mount/env와 bootstrap96파일 hash, 기존 WIP bytes를 보존했다. 이전 웹 `8935793` 롤백과 canonical override의 웹 image/label도 보존·갱신했다.
- 실제 vault 로그인 후 PC/390px 모바일 원본 목록의 업로드 버튼과 상태 접근을 확인했다. 모바일에서 합성 영상 `upload-web-ad38393-synthetic.mp4`를 파일 입력으로 실제 업로드해 100% 완료를 보고, 페이지 재조회 후 원본 `500a823526d74a0ea3f8187ad24cb32a` 등록·상세를 확인했다. 상세의 원본 다운로드 URL을 통해 실제 받은 4,265,166 bytes의 SHA가 입력과 일치했다. 기존 원본은 삭제하지 않았다. 운영에서 실패/재개를 재현한 것은 아니며 해당 수용은 앞선 격리 설치 API 증적이다. 완료 직후 목록 자동 갱신까지 검증한 것으로 확대하지 않는다.
- 후속 WebM 설명문은 원본/산출물 두 상세 소스에서 삭제했고 재생·원본/WebM 다운로드 링크는 유지했다. 별도 source commit `99e4a7b480e04c0bab6670a0cb570740dfd48082`, 범위 RED→GREEN·Node 회귀·변경 lint·renewal build 통과. **당시 혜지 검토/App push 완료였고, 이후 `6eb22e2` 웹에 포함해 운영 반영·원본/산출물 화면 확인까지 끝났다.** 제품 제어는 여전히 미완료다.

### 이전 운영 웹 반영 및 제어 어댑터 진행

- 웹만 clean archive `893579340680c8e189fe0d73bfff13943232fae9` 이미지로 반영했다. API·에이전트는 `6986b614…` 그대로다. 실제 사설 HTTPS/vault 로그인 후 PC·모바일 인코딩 상세, PC 목록 및 사람 검수의 `확인 불가` 보정을 확인했다. HTTPS JS/CSS hash가 실행 이미지 파일과 일치하고 health200/미인증 agents401이다.
- 웹 이외 기존 running 컨테이너17개의 ID·image·start time·mount·환경 hash와 bootstrap96파일 bytes를 전후 대조해 보존했다. 웹의 기존 port/mount/restart 정책과 롤백 이미지/설정도 보존했다. 첫 배포 검증에서 기존 Compose revision label 상속을 발견해 웹 label만 보정했고 이미지 ID까지 재확인했다. 목록 확인 중 브라우저가 about:blank로 전환된 도구 세션 문제는 vault 재로그인으로 복구했으며 제품 세션 지속성 전체 수용으로 확대하지 않는다.
- 후속 `agent_control.py`는 host 전용, 고정 container ID/image/Compose label allowlist의 제어 primitive다. API endpoint/권한 경계가 아니며 API에 Docker socket을 주지 않는다. 네트워크·port·키·데이터 mount 없는 일회용 테스트 프로세스 두 개로 실제 0→1→2→1→0 시작/중지·개수 readback과 잘못된 개수 거부를 확인한 뒤 테스트 컨테이너만 정리했다. 운영 에이전트를 이 테스트로 중지하지 않았다.
- 실제 제품 버튼·관리자 admission/revision/idempotency·최소권한 제어 전달·드레인 진행 상태·운영 대상 적용은 아직 미연결이다. 소스 primitive의 실제 Docker 동작을 제품 start/stop/scale 완료로 보고하지 않는다. 해당 소스와 공용 자료함/개별 인스턴스 WIP는 웹 이미지에서 제외했다.

### 최신 제품 수용 기준 — 화면 단순화와 실제 기능

- 최우선: 원본 목록에서 업로드를 바로 찾을 수 있게 복구하고 진행률·실패·재개를 실제 연결한다. 업로드 상태 접근도 현재 운영 모드에서 숨기지 않는다. 업로드 버튼만 복구한 것으로 끝내지 않는다.
- 필요한 식별 정보는 제거하지 않는다. 실행 인스턴스가 하나여도 고유 ID를 축약 표시하고 전체 확인·복사를 제공한다. 복수 실행은 각 ID·상태·현재 작업을 결합하며 순번으로 대체하지 않는다.
- 작업 목록의 일반 행 영역 전체를 상세 진입점으로 제공한다. 버튼/선택/다운로드 조작과 이동 이벤트가 충돌하지 않아야 한다. 지적한 WebM 안내는 삭제하고 다른 장문으로 대체하지 않는다.
- 에이전트 목록에는 실제 처리 에이전트만 표시한다. IF/Switch 등 제어와 사람 검수는 workflow에 유지하고 서로 구별되는 아이콘을 추가 메뉴·편집/실행 canvas 모두에서 일관되게 사용한다. 기존 연결/설정은 보존한다.
- 원본/작업/workflow/agent/serving/settings GET의 최초 목록·상세 로딩은 실제 행·플레이어·폼 배치에 맞는 skeleton을 제공한다. 주기 갱신 중에는 기존 내용을 유지하며 loading/empty/error를 구분한다.
- 업로드 복구 소스 검증: 운영과 동일한 설치 API `6986b614` + 별도 일회용 PG/CAS에 연결한 production bundle에서 일반 사용자로 PC/390px 모바일 파일 선택→4MiB 전송 후 의도적 연결 실패→페이지 재열기→동일 파일 재선택→저장 prefix 검증/동일 업로드 세션 재개→등록→화면에서 다운로드 SHA 일치를 확인했다. backend WIP overlay나 가짜 성공 응답은 사용하지 않았다. 아직 운영 배포 결과가 아니다.

- 혜지 검토 보정: `controller`는 실행 방식 구분이며 정상 동작의 증거가 아니므로 기본 상태를 `확인 불가`로 표시한다. `RenewalJobDetail.tsx`의 실패한 patch는 무변경이며 HEAD 대비 diff 없음으로 재확인했다. 공용 자료함 읽기 전용 UI는 적용 완료가 아니다. 이 묶음은 화면 정리만 분리하며 실제 제어·provider 호출·제품 전체 완료로 확대하지 않는다.

- 에이전트 기본 화면은 이름·짧은 상태 뱃지·실행 개수·현재 작업·최근 응답·조작으로 구성한다. 독립 소비자/독립 AMQP/실행 경로/worker/heartbeat/lease와 장황한 내부 설명은 기본 화면에서 제거한다. 기술 정보를 다른 긴 문구로 바꾸지 않는다.
- 상태는 정상/처리 중/중지/연결 끊김/확인 불가/오류처럼 짧게 표시한다. 수신이 불명확한 개수를 0으로 꾸미지 않는다. 이번 관측 수용은 기능/사용성 전체 수용이 아니다.
- 시작·중지·실행 개수 설정은 실제 대상에 동작해야 한다. 미연결 안내문이나 가짜 설정 저장으로 완료 처리하지 않는다. 다중 인스턴스 식별/권한/제어 adapter의 실제 검증은 여전히 필요하다.
- 전사·번역 제품 경로는 등록 모델 API와 모델 선택·유한 동적 폴백·실제 호출을 연결한다. 로컬 Whisper 시험은 제품 기본 동작의 대체가 아니다. Gemini 키 등록 막힘도 해결 항목이다. 유료 호출의 기존 별도 승인 경계는 유지한다.
- 모든 캔버스에 찾기 쉬운 자동 정렬·연결선 정리·전체 보기를 제공한다. 노드 겹침과 선 선택을 개선하되 연결 관계·실행 설정을 변경하지 않아야 한다.
- 진행 중 공용 자료함 소스/FK/CAS WIP와 격리 테스트는 보존한다. 운영 DB에 새 공용 원본 migration을 적용하지 않았고, 운영 이미지에 WIP를 포함하지 않았다.

### 사용자 재확정 요구와 다음 구현 순서 — 2026-10-21 19:49 KST

- 단일 직접 writer는 Windows의 혜윤, 혜지는 요구사항/결과 검토와 GitHub App push를 담당한다. 개발 checkout `C:/Users/skygg/dev/mediagent-s2`, `renewal`, 시작 HEAD `625bd9289649321a92f1a6469912d3a44ea49615`. 기존 문서 WIP·미추적 evidence와 원본/DB/키/백업을 보존한다.
- 현재 웹은 `ad38393b5a789dc1a1b69488e914f7a30e5d6f2f`, API·에이전트는 `6986b61471765aa53afc4b8b2b6a1c33b88a3b21`이다. 고정 로컬 영어→독일어 제품 job의 UI/API 혼합 실행과 단일 인스턴스별 worker telemetry 관측을 실제 확인했다. 일반 provider 실행·순수 UI-only 생성·공용 자료함·티켓별 물리 저장·원격 start/stop/scale 전체 완료가 아니다. 공용 자료함 소스 WIP는 배포에 포함하지 않았다.
- [x] 1차-관측: 상태 전용 broker/제한 PG 경로로 worker10개를 연결하고 실제 합성 작업의 처리·heartbeat 만료·복귀와 collector 중단/복귀를 API 및 PC 제품 목록·상세에서 확인했다. 준비 상태는 작업 수신 등록이며 추론 품질·개별 모델 초기화 수용이 아니다. 기존 controller의 passive403 권한을 넓히지 않았다.
- [ ] 1차-제어: 원격 start/stop/scale adapter를 실제 대상과 연결한다. 현재 검증용 Docker 조작은 제품 제어 기능이 아니다. 먼저 exchange당 단일 worker ID 바인딩을 다중 인스턴스 식별/수용 구조로 보완해야 한다.
  - 후속 소스 WIP: 동일 기능의 여러 실행 인스턴스에 각각 ID가 묶인 상태 발행 주소를 부여하는 opt-in 경로와 송신 설정을 추가했다. 기존 단일 인스턴스 설정/권한은 변경하지 않는다. 프로토콜·송신 설정 범위 7개 테스트 통과. 운영 broker provisioning·다중 인스턴스 실제 수신·start/stop/scale adapter와 제품 버튼은 미완료이며 UI 커밋 `8935793`/전달 bundle에 포함하지 않았다.
- [ ] 2차: 인증된 공용 원본/작업/결과 조회·사용·다운로드와 업로더/실행자 기록을 연결한다. credential·관리 API의 보호는 유지하며, 구버전 원본을 개인 계정 소유함으로 옮기는 이전 제안은 폐기한다.
- [ ] 3차: `originals/{original_id}` 및 `tickets/{ticket_id}`의 단계별 파일/manifest를 실제 object 저장에 연결하고 기존 owner-CAS 읽기를 보존한다. 단순 경로 설명이나 PG 목록만으로 완료 처리하지 않는다.
- [ ] 4차: 기존 원본17개를 이력 복원 없이 공용 목록에 이관한다. 대용량 보관·재생·다운로드와 실행 용량 제한을 분리하고 전체 SHA·멱등 재실행·실제 읽기를 수용한다.
- [ ] 5차: connection/model/credential→실제 capability별 provider 요청과 태스크별 동적 폴백 체인을 연결한다. 폴백0개 허용·추가/삭제/재정렬·snapshot pin·A실패→B실패→C성공/전부실패/폴백없음/취소중단·오류별 전환 정책·후보별 능력/인증/비용 확인·실제 시도 순서/최종 모델 표시를 수용한다. 유료 외부 호출은 별도 승인 전에는 실행하지 않는다.
- [ ] 6차: 언어/모델/폴백 선택→원본/workflow→티켓→별도 승인/실행→중간/최종 결과를 순수 제품 UI로 검증한다. 다른 로컬 모델 대체나 API 우회 결과를 UI 완료로 보고하지 않는다.

#### 후속 묶음 B — 상태 전용 worker telemetry (단일 인스턴스 운영 관측 수용, 원격 제어 별도)

- **2026-10-21 22:09 KST 실제 운영 readback:** 혜지의 23경로 검토/App 일반 push 보고 뒤 Windows에서 `origin/renewal == 6986b61471765aa53afc4b8b2b6a1c33b88a3b21`를 fetch/readback했다. 이미 만든 clean-archive 이미지5종만 사용해 기존 대상14개와 collector1개를 전환했다. 전부 동일 revision/running/restart0/paused=false이며 API/web/infra health 정상이다. 대표 API/CPU/model/GPU에 실제 import된 shared module bytes도 해당 archive와 대조했다. 공용 자료함 intake/test WIP bytes는 보존해 운영 이미지에 섞지 않았다.
- 제한 PG 역할의 collector heartbeat가 실제 지속 갱신되고, CPU6/model2/GPU2 worker10개가 실제 상태 보고를 했다. 기존14개 mount를 목적지별로 대조해 보존했고 기존 bootstrap95파일 bytes와 옛 Worker 두 개의 exited 상태도 유지했다. collector에 공개 port/Docker socket을 추가하지 않았다.
- 새 제품 **티켓 #2 `9d61714277ea49598e15e865fa9a6f11`**는 기존 승인 음성 fixture의 영어→독일어 8단계 완료다. **#3 `3aaa2a9a95f54fc0b24e707b8391d6ff`**는 같은 합성 영상의 50초 반복 입력으로 encode→validate 두 단계만 실행해 짧은 busy 상태를 실제 제품 상세에서 포착했다. 원본 등록/생성은 API 설정, 실행 계획/동의/실행은 제품 UI였으며 순수 UI-only 수용으로 보고하지 않는다. 유료 외부 호출은 없고 GPU 추론 수용을 새로 주장하지 않는다.
- 실제 API의 busy sample과 PG `worker_observation_events`/`node_runs`/`jobs`를 read-only 대조해 두 티켓의 10개 attempt와 worker family/기능/논리 node가 모두 일치함을 확인했다. #3 encode의 worker `81831977b4214488b19fb78fca17c213`, attempt `d8dd352593a54303afc997f221648f2f`가 제품 화면의 #3/encode/attempt 표시와 일치했다. 결과 상태/전사·번역/worker 보고를 수동 주입하지 않았다.
- collector를 실제 stop하여 TTL 뒤 API/목록/상세가 **관측 불가**가 됨을, collector 복구 뒤 전체10개 ready를 확인했다. 이어 idle encode worker 하나만 pause하여 collector healthy 상태의 **응답 끊김**을 API/목록/상세에서 확인하고 unpause 후 같은 worker ID/boot가 ready로 돌아오며 과거 ticket/attempt가 현재 값으로 남지 않음을 확인했다. 최종15개 running/restart0, worker10개 fresh/ready, collector healthy다. 원격 제어는 미구현으로 유지한다.
- 실제 JSON/PG 대조/화면 증적은 기존 비공개 ops의 `telemetry-20261021/live/`에 보존한다. 첫 #2의 짧은 encode busy는 API sample에는 있었지만 UI polling 사이에 지나가 #3으로 실제 busy 화면을 추가 확인했다. 큰 binary를 한 CDP 메시지에 넣은 시도는 browser-harness transport limit으로 실패했고 업로드 부작용 없음을 확인한 후 작은 메시지로 나누었다. 이후 도구의 browser context 소실 때문에 추가 실제 phone 확인은 미수행이며 PC 실제 수용과 기존 phone fixture 테스트를 혼합하지 않는다. 일회용 PG/internal network는 테스트 schema0/tmpfs/단독 membership을 확인한 뒤 해당 고유 테스트 자원만 정리했다.

아래는 배포 전 승인 차단과 해소 과정의 과거 체크포인트다.

- **승인 재요청 후 실제 결과:** 선배의 원래 명령 재시도 허용에 따라 같은 명령을 실행 도구에 다시 요청했고 승인되어 exit0으로 완료됐다. 이어 새 제한 DSN으로 별도 연결해 `current_user=mideagent_telemetry_v1`, 상태 table INSERT 허용, jobs UPDATE 불가, accounts SELECT 불가를 다시 확인했다. 기존 광범위 DSN을 수집기 실행에 우회 사용하지 않았다. 아래 승인 만료/역할 없음 기록은 이전 체크포인트이며 현재 PG 선행 차단은 해소됐다. 이번 명령에서 배포·worker 전환·제품 UI 수용·push는 수행하지 않았다. 공용 자료함 소스 WIP와 기존 evidence를 보존했다.

- **2026-10-21 21:20 KST 실제 체크포인트:** A 보완 `adfebd97cdecf48fa830a6336bfc96a0c5173fc6`, B source `6986b61471765aa53afc4b8b2b6a1c33b88a3b21`로 각각 커밋했다. B의 clean git archive에서 API/web/CPU/model/GPU 다섯 이미지를 build exit0으로 만들었고 image revision label을 읽어 확인했다. 원격 App push는 아직 하지 않았다.
- 사전 PG dump와 기존 정의/설정 hash를 private rollback에 보존한 뒤 **새 011 migration 하나만 적용**했다. 상태 전용 broker 계정11개·역할 exchange10개·전용 queue1개를 추가하고 실제 권한을 다시 읽었다. 기존 broker 계정12개의 권한은 동일하며, definitions의 기존 기록과 나머지 bootstrap95파일의 bytes도 보존했다. 본체 작업/원본/credential 이관을 실행한 것이 아니다.
- 다음의 **수집기 전용 제한 PG 역할 생성 명령은 실행 도구 승인창이 5분 만료되어 실행되지 않았다.** 같은 명령 재시도·다른 경로 우회·기존 광범위 DSN으로 collector 실행은 하지 않았다. readback에서도 새 PG 역할 없음, worker/observer 보고0행이다. 새로운 역할은 상태 table만 접근하도록 준비됐으며 제품 로그인 계정 생성과는 별개다.
- **제품 배포는 시작하지 않았고 14개 대상은 모두 기존 `625bd9289649321a92f1a6469912d3a44ea49615`, running/restart0을 유지한다.** API/web/infra health 정상, 옛 Worker 두 개 exited다. 따라서 새 화면과 실제 worker 기동→대기→처리→heartbeat 만료→복귀는 아직 미수용이다. 현재 제품의 예전 꺼짐 표시는 아직 새 source로 바뀌지 않았다.
- build 최초 시도는 Bake의 기본 Compose 동시 탐색으로 bootstrap 변수 보간에서 중단됐으며 `-f docker-bake.hcl` 명시 후 성공했다. 운영 데이터 오류가 아니며 최초 로그도 보존했다. disposable PG 테스트 컨테이너/내부 network 한 세트는 승인 차단 시점에 남아 있어 재개 시 해당 고유 테스트 자원만 정리해야 한다(운영 PG/volume 정리 금지).

- 고정된 worker 식별자와 정렬 가능한 boot generation/sequence, family/기능, 마지막 서버 수신 heartbeat, 현재 job/attempt 및 PG가 대조한 node/ticket을 제공한다. consumer 수를 worker 생존/준비로 환산하지 않는다.
- 별도 역할별 상태 발행 계정은 자신의 상태 exchange에만 write, 수집 계정은 전용 상태 queue에만 read한다. 기존 controller/worker의 broker 권한은 보존한다. API는 PG만 조회한다. 원격 start/stop/scale은 별도 미완료이며 제공하지 않는다.
- collector와 worker의 수신 만료를 분리하고 연결/작업 수용 준비/처리 중/heartbeat 끊김/관측 불가를 표시한다. 별도 연결의 상태 보고 실패가 기존 처리·result publish·ACK 순서를 바꾸지 않도록 격리한다. 이전 boot 및 중복 sequence는 현재 상태를 갱신하지 않는다.
- 추가 migration `011_worker_telemetry.sql`은 상태 snapshot/변화/수집기 heartbeat table만 추가한다. 기존 job/result/원본/키를 변경하지 않는다. 배포 시 사전 PG dump와 기존 bootstrap hash/권한 readback을 보존한다.
- 변경 범위 테스트: Python 27 passed/3 skipped(기존 AMQP 통합 세 항목), 웹 변경 lint/format/build 및 전체 Node test 통과, 기존 관측 표시 PC/phone 24건 통과. 별도 disposable PG의 순서/만료/boot fencing와 인증된 실제 ASGI 목록·상세 경로를 포함한다. 이 결과는 운영 worker 변화나 배포 완료를 뜻하지 않는다.

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
