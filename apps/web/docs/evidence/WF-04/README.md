# WF-04 · 수동 선택·독립 병렬·선택 결과 목록 합류

기준39617aecd0bfc8410130fbf7919ab245520df0df. 제안A 승인 Discord1560355980796240024 및 같은 WF04/결정절에 따라 신규 분기·병렬 티켓에만 적용한다. 기존 정상 순차/고정 template·티켓·Worker checkpoint/재시도는 보존한다. Codex/코딩Agent 없이 직접 구현했으며 독립 coding-review agent 검토라고 주장하지 않는다.

## 실제 경로와 의미
- 기존 editor/catalog/revision/DefinitionStore를 재사용하고 select(수동 a/b/both), join(선택 결과 manifest)을 추가했다. 자료유형 옵션에 따른 포트는 서버 node_spec과 공통 frontend resolvePorts가 맞춰 표시/검증한다. manifest는 artifact_manifest 유형이며 단일 video/audio/subtitle 입력으로 위장하지 않는다. catalog valid는 실행/과금 성공이 아니다.
- compile_graph는 정의의 실제 노드/포트/옵션을 검증하고 각 native 인과사슬의 기존 compile_sequence 제한도 재사용한다. select를 통과하는 원래 자료 producer를 추적하되 실행 bindings에는 실제 select port를 유지한다. 원본video 하나·기존 지원 media 처리 범위 내 fork/독립사슬을 지원한다. 얼굴합성 session/preview·GPU VAD·유료발성분석이 활성인 비off전처리·외부오디오/세션·새검수/AI Decision·오류전용분기는 미지원이다. 미선택 가지도 저장 정의의 기본 native지원/유형 검사를 면제하지 않는다.
- GraphTicketStore는 별도 .workflow-graph-tickets/owner namespace이며 기존 .workflow-tickets/legacy queue를 소비하지 않는다. WF03 TicketStore의 생성 snapshot/request중복·plan/confirm·비밀없는 설정결합·키context hash·설정 drift거절·owner/file confinement/SHA 다운로드 계약을 상속한다. 기본 순차 compiler는 그대로이고 내부 compile hook만 분리했다.
- 수동 선택은 생성 요청 options와 고정 정의를 함께 hash/재대조한다. 변경은 새티켓/새확인. 운영키/암호문은 복사하지 않고 기존 resolve 결과를 실행 순간 메모리에서만 사용한다. 시작 전 확인값을 재검사하며 단계별 최신 모델로 몰래 교체하지 않는다.
- ThreadPoolExecutor의 실제 동시 진행, 티켓당 상한2(내부 primitive허용1~4), coordinator 하나의 원자 영속 상태 저장을 쓴다. 여러 티켓의 전역 worker quota/분산 queue 보호를 추가한 것은 아니다. 각 native 호출의 source/filter/language/encode/provider 객체를 분리하고 선행으로부터 문맥을 복원한다.
- 선택되지 않은 경로/빈join은 skipped. 선택 필수 선행 failed/blocked이면 해당 후행/join은 blocked이며 독립 가지는 계속 실행한다. 모든 실행 가능한 가지가 정리된 뒤 failed/blocked가 있으면 failed, 없으면 completed. pending/running이 남은 상태는 completed로 표시하지 않는다. 신규 자동retry/취소후resume/crash복구 없음.
- select는 immutable 참조를 전달하며 원본 대용량파일을 복사하거나 새 다운로드로 공개하지 않는다. join은 선택 입력만 nodeID.port namespace에 유형/경로 또는 참조/SHA/bytes/clock provenance를 보존한 JSON manifest를 실제 파일로 쓴다. 동명 산출물은 각 producer 작업폴더에서 보존되고 미디어/clock 병합·대표 입력 선택은 하지 않는다. packed audio/timeline 문맥도 개별 보존한다.

## API·화면·운영 경계
/api/settings/graph-tickets의 create/list/get/capability/runtime/plan/confirm/start/artifacts. 기존 settings owner/auth/origin/body한도·영상 admission·서빙 resolve·명시 비용확인·threadpool 시작을 재사용한다. 별도 graph_executor_factory만 확인하며 운영 기본은 미연결이다.
/#/graph-tickets에서 저장 정의+영상·수동 선택→범위 재검사→held생성→고정 선택·계획/서빙/비용 확인→요청/실제 상태·실패/blocked/skipped·성공/partial·manifest 다운로드·재열기를 연결했다. 기존 /#/workflow-tickets의 첫실패 중단 의미는 그대로다. 캔버스도 실제 제어노드·자료 포트·옵션/연결/저장·재열기를 지원한다. 사람검수/AI Decision은 만들지 않았다.
운영 executor 미연결·두 Worker 정지·기존 큐 미소비·사설 임시무인증 유지. 이번은 격리 실제 실행경로와 제출 배포 근거이며 운영 실행/실GPU/provider/유료/사용자원본 처리 허가가 아니다.

## 검증
- backend 영향42PASS(신규11+기존31), Node40/lint/format/build/browser타입 PASS. 전체 backend suite 또는 독립 coding-agent 리뷰는 아니다.
- 새 PC1440/390 실제 ASGI 여정2 + 공유 UI를 쓰는 기존 WF03 회귀2 = 고유4PASS. 기존 WF03 evidence는 재생성분을 이번에 덧커밋하지 않고 기존 bytes로 보존했다. 반복 실행을 합산하지 않는다.
- 새 여정: 미지원GPU 거절→held/both고정→외부 정의r2 편집에도snapshot1→서빙 drift409/명시새계획1→두 실제 executor가 동시에 running인 GET/영속 상태를 관찰·캡처한 뒤 격리 fixture latch를 release→한가지 실패/partial·다른가지 성공·join blocked→선택a로 새티켓/새확인→b skipped·선택a만담은 manifest 다운로드→저장 재열기→both 성공 새티켓→실제 캔버스 left_type 변경/유형실패 편집유지→수정저장/새문서재열기. 각 viewport 저장JSON3티켓(completed2/failed1)·원본 numeric token(stat ns)과 trace를 보존한다. fixture release는 테스트 전용 ASGI의 latch이며 운영API에 추가되지 않는다.
- 실제 스레드 Barrier/trace로 두 가지 시작이 어느 가지 종료보다 빠르고 thread가 다름을 검증한다. UI상태만 가짜로 바꾸지 않는다. 실행기가 실제 파일을 만들고 실제 GraphTicketStore/compiler/scheduler/API가 기록한다. 이 여정의 encode 결과는 명시 결정론 fixture이며 실미디어 성공으로 주장하지 않는다.
- 별도 CPU 검증은0.4초 합성 blue/sine영상→수동both→실제 software FFmpeg encode2/각validate→실제 join manifest까지 GraphTicketStore/native 경로를 통과한다. CPU-actual-ticket/manifest는 그 실행 결과이고 실제 mp42개는 검토 ZIP에만 첨부한다. 실제 cloud/GPU/provider 호출 없음. 순차 CPU/fixture STT 회귀의 통과 역시 실모델 성공이 아니다.
- 신규 scheduler 미구현/부분결과 누락/정적 admission RED, API/UI 미구현 RED를 거쳐 구현했다. 초기 회귀16 오류는 source read-only 아래 legacy ROOT/data/test-runs 쓰기였고 tmpfs로 격리했다. 다음507실패2는 테스트 컨테이너의 startup disk threshold이며 컨테이너에만 MIN_FREE_SPACE_BYTES=0을 적용해 최종42PASS. 운영설정은 바꾸지 않았다. 신규 frontend 첫 lint curly10오류는 중괄호 수정으로 최종PASS. 기존 FastAPI/Radix/thumbnail 경고는 유지한다.

실제 배포 SHA/이미지·health/HTTPS 화면/원격/데이터 보존·복구 근거는 같은 WF04에 별도 제출한다. 다른장치 접근·실모델 품질·전역 과금/API우회 보호/전체 버전·복구·분산 registry/VPS분할은 이 작업의 완료 선언이 아니다.
