# WF-03 · 별도 보류 티켓·정의 기반 순차 실행

기준0616538b81b827fabc43d4fefe569046874dab38. 혜지의 제안A 승인에 따라 새 순차티켓에만 적용한다. 정의 ID/revision/내용은 생성시 복사·hash검사, 서빙의 비밀 아닌 값/revision은 명시적 계획확인 시 결합한다. opaque 계획token은 원본 stat·옵션·정의내용·설정/일시적인 키context까지 묶지만 키/암호문은 티켓·응답에 복사하지 않는다. 시작전 비교 후 같은 snapshot값으로 provider객체를 구성한다. 입력/옵션변경은 새요청ID·새티켓·새확인으로 분리한다. 기존티켓 소급/전체버전정책은 아니다.

## 실제 경로·지원 범위
- sequential_workflow.compile_sequence는 workflow_graph/실제catalog를 먼저 검증하고 명시 port binding으로 단일사슬을 정렬한다. 고정template으로 치환하지 않는다. 선택한 node/options/output 계약 그대로 전달한다.
- 현재지원: 단독 analyze; extract_audio→preprocess_audio→transcribe→translate→generate_subtitle→encode→validate_video의 필요한 순차부분. STT는 동일전처리의 audio/timeline, 번역은 해당전사, 자막은 전사/번역, encode자막은 해당자막생성, 출력검증은 해당encode를 요구한다. 원본video의 정적인 encode입력 재사용은 허용하지만 독립사슬·분기/합류는 거절한다.
- 외부video하나만 현재 admission지원. faceswap session/preview·GPU VAD·유료발성분석이켜진전처리·새검수/Decision·외부자막/오디오반입은 지원하지않고 이유를 반환한다. 기존고정workflow/얼굴합성/전사재사용경로는 source불변이다.
- MediaNodeExecutor는 기존 media.probe/extract_audio/preprocess_audio/encoding_args/run_process, provider.transcribe/translate, packed_timeline.restore_segments·completed_transcript의 원본clock/sha/재사용, subtitle/validation함수를 호출한다. 새encode는 명시CPU software codec 경로다. 실패 partial전사/번역·차단결과를 남기고 차단자막은 검수없이burn하지않는다.
- TicketStore는 .workflow-tickets owner namespace의 별도 상태/파일이며 legacy job.json/JobRecord queue에 넣지 않는다. OS실행/상태lock·원자적JSON저장·요청ID중복방지·정의/순서/옵션재대조·원본stat/단계입출력sha·같은실행계획context를 검증한다. 첫실패에서중단·성공/partial파일보존, 전단계성공만completed. 자동retry/취소후resume·오래된 running 복구는 미구현이다.

## API/UI
/api/settings/workflow-tickets의 list/create/get, capability/runtime, plan/confirm/start/artifacts. 기존 settings auth/origin/CSRF/소유권·bounded JSON·서버asset검증 재사용. 추가키/옵션 필드는 strict body로거절. start는 확인token/revision/context와 실제연결된 executor factory를 확인한뒤 threadpool에서 실제공유orchestrator를 구동한다. 실행중GET이막히지않음을검사했다. 다운로드는owner/경로/sha검사와실제파일확장자보존.

/#/workflow-tickets에서 영상+저장정의 선택→범위검사→별도held 생성→명시plan/비용확인→실행요청·상태재조회/단계/부분·최종산출물링크로연결했다. 입력변경은기존확인초기화, 정의새편집은티켓snapshot에자동반영하지않는다. 접속/저장/키보유/모델목록을추론성공과구분한다.

**운영 기본 executor factory는 비어있다. 두 Worker/기존큐를 시작하거나 새티켓을 자동실행하지 않는다.** 운영 UI는 새실행기미연결/실행요청비활성, start API도409다. 실제 native 진입점 run_media_ticket는 설치되지만 이번에운영호출하지않는다. 격리에서실제실행경로를연결한것과운영Worker/실모델연결은별개다.

## 실제 검증·산출물
backend영향31PASS(신규7+기존24), Node40/lint/format/build/browser타입통과. 전체backend suite는아니다. 정상생성/중복요청/정의복사/환경설정drift와재확인/키미포함/불변sequence재검사/실패보존/재실행거절/실제artifact전송/실행중조회/직접import경로를확인했다.

신규실행은network-none/tempdata에서실제orchestrator를구동한다. 결정론executor가실제파일을써서상태/순서/부분보존을검증한다. 별도테스트는0.4초 합성blue/sine영상에실제CPU FFmpeg추출·전처리·SRT·burnencode·검증까지7노드를구동하되 STT/번역은 명시fixture provider다. CPU-actual-ticket.json/CPU-actual-validation.json은그때실제생성된값이다. synthetic mp4/SRT는검토ZIP에만첨부한다. 실사용자영상·GPU·외부provider호출/유료/실모델성공이아니다. 기존원본clock10.1복원·완료전사reuse1회·cache변조후재과금전거절도검사했다.

최종PC1440/390 두여정PASS: 실제ASGI/DefinitionStore/TicketStore+명시결정론executor, 합성영상metadata입력. 미지원분리사슬→held(정의r1)→실제정의서버편집r2뒤에도snapshot1유지→plan서빙0→실제설정변경1에확인409→명시plan1/재확인→실제prepare실패·extract성공/partial다운로드→입력변경/확인초기화→정의2다시읽고새티켓→양단계완료→서버GET완료후plan초기화·산출물3개보존. 각viewport의실제저장JSON에failed/completed 두티켓·정의1/2·서빙1이대응한다. 모든응답을가짜상태로꾸민것이아니며banner/실행기mode에격리결정론이라고명시한다.

## 실패 이력
compiler/store/adapter/API/UI미구현 RED, sequence변조거절누락 RED, 미계획유료발성분석guard RED, 동기start가상태GET을가린 RED→threadpool, 확장자누락 RED, child-first circular import RED→부모설정lazy조회를보존한다. 재열기검증은캐시된동일노드개수만보지않도록서버응답상태문구와plan초기화를추가했다가전역연결status와strict locator가충돌해2개실패했다. 로컬페이지status로한정한뒤같은2개최종PASS;앱실패로확대하지않는다. 기존FastAPI/Radix/thumbnail 경고보존·반복개수합산없음.

실제배포image/fullSHA/health·실제무입력화면은같은WF03에별도기록한다. 데이터/DB/키·설정·큐·WIP/backup보존. 모델/엔진실제연결·유료·실미디어·재생품질/다운로드통합·전체버전/복구/서버과금보호완성은아니다.
