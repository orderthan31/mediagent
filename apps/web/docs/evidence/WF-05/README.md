# WF-05 · 원하는 지원 지점의 사람 검수·명시 이어 실행

기준 1e07aa7d035c423af70ece708b339d7d0f0f6ecf. 제안 A 승인 메시지1560380363283370015와 같은 WF05 결정절을 적용했다. 신규 검수 지원 티켓만 대상이며 기존 순차/병렬 티켓·고정 workflow/검수·legacy 큐/render·Worker checkpoint/retry를 소급하지 않는다. Codex/코딩Agent 없이 직접 구현했고 독립 coding-review agent 검토를 주장하지 않는다.

## 실제 실행/저장 계약
- catalog review 노드는 VALUE_TYPES의 자료 유형에 따른 value→value typed gate다. 캔버스에서 서로 다른 위치에 배치/옵션/연결/좌표를 저장·재열고 신규 review-tickets admission에서만 실행한다. 기존 순차/graph admission은 검수노드를 거절한다. 기존 compiler/snapshot/owner/선택고정/typed manifest 계약을 재사용하며 미디어·clock 병합/AI Decision은 추가하지 않았다.
- ReviewTicketStore는 별도 .workflow-review-tickets/owner namespace다. held 생성과 server definition snapshot/입력/revision, 선언된 선택과 실제 실행 정의를 대조한다. 기존 legacy 큐/render 재개 API를 호출하지 않는다. 기존 graph/순차의 정상 계약은 유지한다.
- scheduler NodeWait는 실패가 아닌 영속 waiting이다. 해당 후행은 pending, 독립 가지는 계속 실행한다. runnable이 정리되면 프로세스/스레드를 붙들지 않고 awaiting_review로 반환하며 재열어도 gate와 자료가 유지된다. 선택 필수 join은 승인한 gate가 성공하기 전 대기한다. waiting/pending/running을 completed로 숨기지 않는다. 실제 failed/blocked·미선택 skipped 의미는 그대로다.
- 정상 검수의 명시 pass만 continuation으로 수행한다. 성공/실패/차단/미선택 결과는 seed로 보존하고 승인한 waiting gate만 pending으로 전환한다. succeeded native 노드는 다시 실행하지 않는다. 오래된 running/crash·일반 실패 retry·취소 resume·승인 취소/후편집은 제공하지 않는다.
- 텍스트는 원본 clock·검증된 원본 길이의 transcript segment 배열/SRT만 편집한다. 기존 구간 수·speaker를 유지한 텍스트/시작·끝 수정, 형식/유한수/원본 길이·겹침 등 기존 검증을 적용한다. 각 문서/결과1MiB, 최대10000구간 및 API 본문 한도를 적용한다. 구간 추가/삭제, 미디어 bytes·clock map·manifest 구성원 편집은 미지원이다. packed/미지원 clock·원본 길이 미확인은 이유를 표시하고 편집하지 않는다. 영상/음성/metadata/timeline/report/manifest는 참조 확인만 지원한다.
- 원본/과거 수정본을 덮어쓰지 않는다. 검수 노드별 원본 metadata/clock/SHA·불변 document/output version·document SHA·output SHA를 기록한다. 대상 token은 티켓/노드/원본 자료를 결속한다. 별도 state_revision은 저장/수정요청/승인 결정의 CAS이므로 반려 후 옛 승인을 수용하지 않는다. 원본/자료/SHA 변경을 mutation 전에 다시 검사한다.
- 저장은 승인도 실행도 아니다. 정확한 revision/SHA의 자료를 별도 승인하고 차단 placeholder가 남으면 거절한다. 반려는 changes_requested로 대기 유지한다. 같은 승인 요청 ID/내용은 새 revision 없이 반환하고 다른 내용/옛 대상은409다. 화면 미저장 편집은409 뒤와 반복 stale PUT에도 유지한다. 명시 재조회로 새 server revision을 채택한 뒤 사용자 저장/재확인만 허용하며 자동 병합/교체하지 않는다.
- 승인 후에도 자동 시작하지 않는다. 승인 revision/SHA/결정 상태·실제 미실행 단계·서빙·phase가 계획 token에 결속된다. 지원 gate 뒤에서 모델 호출이 가능해질 때 그 pass의 역할/비용을 새로 명시 확인한다. 수정본/서빙/계획이 바뀌면 재확인한다. 완료 단계 산출물·당시 serving_snapshot을 보존하고 미실행 단계만 최신 확인값을 사용한다. 키는 기존 resolve를 통해 메모리에만 공급하며 복사하지 않는다.
- start/continue는 request_id+revision/token/operation을 기록한다. 같은 요청 재전송은 현재 상태를 반환하고 native 실행·revision을 추가하지 않는다. 다른 대상/내용은409다. 상태 readback·파일/hash를 검증하고 승인된 실제 bytes/참조만 후행에 전달한다. 이는 전역 원자 과금/전체 불변 버전·분산 queue 보호의 완성 선언이 아니다.

## API와 화면
/api/settings/review-tickets runtime/capability/create/list/get/plan/confirm/start/continue/reviews GET·PUT/decision/history/input/artifacts. 기존 settings auth/owner/same-origin·입력 admission·서빙 resolve·비밀 암호화 경로를 사용한다. runtime factory는 review_executor_factory 한정이며 운영 기본은 미연결이다. 기존 workflow/graph factory와 Worker를 시작하지 않는다.
/#/review-tickets와 GNB, 공통 티켓 UI의 별도 review 모드를 연결했다. 노드별 원본 확인·clock/provenance·구간 편집·불변 이력·저장/정확한 승인·수정요청, 미실행 계획/비용 확인·별도 이어 실행, 독립 결과/필수 join 대기·manifest/다운로드를 표시한다. 운영 미연결은 버튼/API 모두 차단한다. 한결/Indigo를 유지했다.

## 검증과 증거 경계
- 영향 backend52PASS = 신규10 + 기존42. Node40/lint/format/build/browser 타입 통과. 전체 backend 또는 독립 coding-agent review가 아니다. 설치 이미지의 동일 신규10 검증 여부/결과는 배포 receipt에서 별도로 보고하며 위52와 합산하지 않는다.
- 고유 browser6PASS: 신규 PC1440/390 실제 ASGI 여정2, 기존 graph2+순차2 회귀4. 각 호출은 network-none 실제 FastAPI/TestClient·DefinitionStore/ReviewTicketStore/LLMSettingsStore를 새로운 프로세스에서 재열며 실제 executor 파일을 생성/읽는다. 화면 mock/가짜 상태 전환이 아니다. 실행기는 명시 결정론 fixture이고 encode 산출물은 NOT_video 표기 JSON fixture다. 실제 미디어/실모델 성공으로 주장하지 않는다.
- 새 여정은 캔버스 검수3개/좌표 저장·재열기→held/계획비용확인→전사 뒤·독립 metadata 뒤의 실제 waiting/후행 pending→브라우저 재열기→차단 승인422→외부 실제 저장 r2→옛 r1 PUT409와 반복 stale409/편집유지→명시 GET/r2 채택→사용자 수정본r3 별도저장/후행미실행→정확SHA 승인/후행미실행→readonly metadata 승인→서빙 drift409/새계획1→명시 이어실행→실제 승인 text bytes로 자막 생성→두 번째 자막 검수 위치 waiting/encode pending→명시 승인/이어실행→최종 manifest/completed다. trace의 STT/독립분석 호출은 각각1회다.
- stored-*는 Python 저장 JSON의 raw bytes를 그대로 복사해 nanosecond 정밀도를 보존한다. review-docs-*는 그 최종 티켓 ID에 일치하는 원본/외부 수정/사용자 수정본·결정/승인 상태의 실제 저장 파일이다. 각 버전 document/output SHA와 최종 승인 산출물 metadata를 대조했다. initial-*는 이전 촬영/실행 출력 보존이며 최종 authoritative stored/review-docs와 구별한다.
- CPU-actual-result/manifest/approved.srt는 별도 실제 합성 blue/sine0.4초→실제 FFmpeg extract/preprocess→명시 offline STT fixture→차단 gate/사람 수정→실제 subtitle 생성→두 번째 검수/승인→실제 software encode/burn→ffprobe/decodable validation→manifest의 결과다. actual report valid=true 및 실제 mp4 bytes/SHA를 확인했다. 영상은 검토 ZIP에만 첨부한다. 실GPU/provider/과금/사용자 원본을 사용하지 않았다. STT1회와 과거 serving revision0/후행 revision1도 검증했다.
- RED: wait/doc/runtime 모듈·API/화면 미구현을 먼저 확인했다. input SHA 변경 뒤 승인을 수용하던 검사를 RED로 잡아 mutation 전 원본/검수 입력 hash 재검사를 추가했다. 원본 길이 미확인 자료의 편집 허용도 RED로 잡아 readonly 사유로 보완했다. 첫 API seed는 burn 기본값의 자막 입력 누락이어서 fixture subtitle_mode=none으로 수정했다. 캔버스 초기0은 선택 후 명시 열기 누락인 여정 오류로 수정했다. 초기 frontend curly9개는 국소 eslint fix 후 통과했다. 검수 입력 hash 검증의 API event-loop 차단은 실제 병렬 GET/barrier RED로 확인하고 저장/결정 handler를 threadpool로 이동해 통과했다. evidence 복사에서 admission.lock을 티켓으로 고른 여정 오류는 정확한32hex 디렉터리만 선택하도록 수정했다. 완료 후에도 검수 panel이 이어실행 전이라고 표시하던 RED는 승인 gate 통과/서버 확정 revision·SHA 표시로 보완했고 로컬 미저장 편집은 실행본과 분리 보존한다. 처음6개 통합 foreground는 도구420초 타임아웃으로 완료 결과가 없으므로 통과로 세지 않고, 명시 background job에서 신규2/기존4를 각각 완료했다. 기존 FastAPI/Radix/fixture thumbnail 경고는 남는다.

운영 factory 미연결/두 Worker 정지/기존 큐 미소비·사설 임시 무인증·데이터/DB/실키/설정/WIP/백업 보존. 실제 배포/원격/이미지·health/HTTPS assets/신규 무입력 화면·보존/복구는 같은 WF05 별도 receipt에서 확인한다. 사용자 다른 장치 접속·실모델 품질·운영 실행 연결·전역 과금/API우회 보호·전체 retry/crash 복구·AI Decision·VPS 분할은 미확인/미구현이며 승인 범위가 아니다.
