# WF-02 · 실제 편집 정의·서버 저장

기준a60832297e4c3188edae542d60f4a5862e4a21ec. 기존 catalog9/validate_node를 재사용하며 Worker·고정template·티켓·LLM설정 source는 변경하지 않는다.

- /#/workflow-editor: catalog선택→배치/끌기/방향키/숫자좌표→출력/입력 연결·해제→속성/삭제→서버검증·저장/재열기. 외부 입력은 $input의 유형 선언일 뿐 실제 파일·세션이 아니다. Canvas는 내부 스크롤이며 작은화면은 기본 접근만 확인했고 모바일전체정책을 확정하지 않았다.
- GET /api/settings/workflow-definitions, GET/PUT /{32hexID}, POST /validate. 기존 settings auth/origin/CSRF 유지. 새 정의만 owner별 .workflow-definitions에 저장하며 owner는 해시 namespace, edit revision CAS/OS lock/atomic replace로 보호한다. 목록·조회는 없는 폴더를 만들지 않는다. 입력128KiB·노드100·연결300·외부입력20 제한.
- 이름/catalog버전/배치·ID형식, 실제 catalog I/O·필수입력·옵션, 존재하지 않는 endpoint/port, 중복·한 입력의 여러소스·순환을 서버가 검증한다. 문제마다 node_id/edge_id/읽을 수 있는 이유를 반환해 패널·노드·선/목록에 표시한다. 검증 실패 정의는 저장하지 않고 편집은 유지한다. 서버도 직접 PUT을 재검증한다. 연결선 분기는 데이터 연결 편집일 뿐 병렬 실행 정책이 아니다.
- 서버 재조회는 명시적으로 편집을 교체한다. revision은 편집 충돌검사용이지 불변 실행버전 정책이 아니다. 기존 workflow/티켓에 소급·마이그레이션하지 않는다. 저장값 executable=false이며 파일/시간축/모델·엔진·실행 성공은 검증하지 않는다. 실제 티켓/순차실행은WF03, 병렬/합류는S5 범위다.

## 실행 근거
격리 network-none 실제 API·설정·기존workflow 영향회귀24PASS. 신규3테스트는 owner 격리/roundtrip/위치·이름·revision보존/모든9catalog의 단일노드 정의/잘못된 유형·끊김·중복·자기순환·옵션·NaN배치 거절/직접API save/read/list/409/422/404/413/cross-origin403을 포함한다. 기존 Node40/lint/format/build·browser타입 통과.

최종 브라우저3PASS=PC1440/390 실제ASGI 저장여정2+100개 기본배치 범위 회귀1. 여정의 HTTP전송만 Playwright에서 network-none Docker의 실제 FastAPI TestClient/DefinitionStore로 연결하며, 응답이나 revision을 별도 mock 구현하지 않는다. 저장 실패503만 안전한 OSError 주입, 외부충돌은 실제 API를 통한 다른 저장으로 revision을 증가시킨다. 실제 temporary JSON을 다시 읽어 stored-1440/390.json으로 제출한다. 이는 운영 저장/실엔진 성공이 아니다.

여정: 필수입력누락→연결/포인터끌기/속성/좌표수정→PUT0/503 편집유지→PUT0/200(r1)→실제외부저장(r2)로PUT1/409→같은1/409(자동개별GET없음)→명시GET2/서버이름채택→재입력PUT2/200(r3)→GET3로이름/배치/옵션/연결보존→방향키이동/노드추가·삭제/연결해제/유형오류→복구PUT3/200(r4)→GET4에서x700/y240·strong/off·노드2/연결2보존. event ledger와 stored JSON·PC/작은화면 screenshot에 대응한다. pageerror0·문서가로overflow없음.

## 실패 이력과 보완
storage/graph/API/UI가 없던 각 RED를 보존했다. 100노드의 기본 y5420이 서버3000범위를 넘는 것을 추가 browser RED로 재현하고 8열 배치로 보완한 뒤 모든100개좌표 범위/추가차단을 통과했다. 통합 재실행 중에는 실제 저장/재열기 완료 후 증거 JSON 쓰기 다음 screenshot scroll에서 DOM/context가 바뀌어2개가 실패했다. 증거 JSON 쓰기를 모든 브라우저 검증/촬영 뒤로 옮기고 최종 동일3개PASS를 확인했다. 개발파일 감시 영향이 의심되나 원인을 확정하거나 운영앱 오류라고 판정하지 않는다. 같은여정의 반복실행을 새로운테스트 수로 합산하지 않는다. 기존 FastAPI httpx·Radix·thumbnail fixture 경고를 유지한다.

실제 배포 source/image/health와 실제 새 편집 정의 저장/재열기 화면은 같은 WF-02에 별도 제출한다. 원본데이터/키/DB/큐·Worker상태와 임시 사설무인증을 보존하고 GPU/provider/유료/원본처리·삭제를 실행하지 않는다.
