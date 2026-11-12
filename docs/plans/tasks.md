# 현재 구현 태스크

## 저장 자막 → 번역 전용 준비 — source/offline 범위

- [x] 이미 연결된 일반 SRT/완료 transcript·동일 영상 WAV 입력은 유지하고, 독립 저장 copy를 선택 번역 에이전트 하나에 연결한다. explicit translation_goal과 별도 frozen translation_selection을 사용하며 기존 render_goal/영상 준비 기록을 바꾸지 않는다.
- [x] 실제 접근 가능한 workflow revision의 모델/후보/옵션·해석된 분할/media/호출 budget을 보존한다. 모델 선택은 그 goal에 이미 고정된 등록 ID/revision으로 제한하고 credential namespace/권한을 넓히지 않는다. source-owner binding으로 paid metadata를 계산하며 미래의 명시적 시작은 기존 비용 동의·Start/queue 조건을 따른다.
- [x] 공용 준비 화면의 번역 mode·저장 목록/상세 진입·언어/모델/옵션·호출 범위·오류·preview 무효화·전체 reload를 연결했다. 영상 준비의 불필요한 DISPLAY node ID suffix만 제거했고 실제 ID/value/canvas는 유지한다. 기존 번역 transcript JSON 결과 읽기/받기를 재사용한다.
- [x] 새 연결만 production resolver/route/Create/실제 preflight·_plan/SDK pin·첫 translate 명령·role envelope를 fake DB/registry와 임시 CAS로 검증하고, React/AuthGate/production CSS PC1440/390을 오프라인 fixture로 확인한다. 과거 전체 suite/운영 여정은 반복하지 않는다.
- [ ] 부모 독립 검토·설치 후 GET/inspect/preview 제품 수용은 별도다. 실제 새 job/Start/번역/provider/GPU/렌더는 이 source writer가 수행하지 않으며 성공을 주장하지 않는다.

## 저장 수정본 → 별도 자막 영상 준비 — 소스 범위

- [x] copy ID/SRT SHA만 받는 server-resolved 입력을 기존 NormalInputs에 연결했다. 실제 custodian·receipt·원문 SHA·변환 transcript SHA를 고정하며 accepted job/run 출처를 만들지 않는다. 미리보기는 CAS를 쓰지 않고 영상 길이·native 자막 소비 한도를 확인한다.
- [x] 실제 저장 workflow의 자막 영상 에이전트만 명시 선택해 inspect/preview/Create가 같은 agent-only 정의를 사용한다. 원래 workflow revision/hash와 effective graph를 구분하고 새 snapshot에 고정한다. 기존 입력·과거 absent-policy snapshot과 정상 새 Start 대기열 경로를 유지한다.
- [x] 저장 목록·상세에서 기존 인증 shell의 준비 화면으로 연결하고 URL의 copy identity를 reload에서 서버 재조회한다. 선택 변경 시 preview를 무효화한다. 생성 오류/응답 불명은 목록 확인을 안내하며 자동 재전송하지 않는다.
- [x] 새 연결의 production resolver/HTTP/Create/command/자막 serializer를 임시 CAS·fake DB로, 실제 React/production CSS PC1440/390을 오프라인 fixture로 확인했다. 영상 encoder·provider·운영 데이터 호출은 하지 않았다.
- [ ] 부모 독립 검토와 실제 설치 후 권한·저장소·명시적 새 작업 생성·Start·native 렌더·MP4 및 자막 결과 수용은 별도다. 이 소스 작업에서 실행·배포·publication을 수행하지 않는다.

## 확정 추가 범위: 에이전트 전용 워크플로우와 실제 소스 계층

- 만들 것: 전사 → 한국어 번역 → 자막 영상 제작의 업무 에이전트만 저장/편집/실행 캔버스에 둔다. 분석·오디오 준비와 구간 처리는 전사 내부 도구, 자막 생성·번인·검사는 영상 제작 내부 도구다. 오케스트레이터는 에이전트 간 순서·배정·준비를, 에이전트는 자기 도구 선택·순서·결과 확인을 책임진다.
- 사용: 영상과 등록 모델을 고르고 시작한다. 에이전트 상세에서 하위 도구의 진행·출력·실제 콘솔을 본다. 오류는 붉은 노드/이유로, 다음 실행기 실제 준비는 연결선의 ‘다음 단계 준비 중’과 대상 노드의 ‘준비 중’으로 구분한다. 내부 도구 준비는 에이전트 내부 진행이다.
- 소스: 기존 모노레포 안에서 오케스트레이터 구현·업무 agents·tools/툴허브·runtime/컨트롤넷을 실제 이전한다. 기존 import/CLI의 필요한 경계는 구현 없는 호환 모듈로 유지하며 원본 구현을 복제하지 않는다. 패키지·Docker·실행 진입점과 전후 트리를 함께 검증한다.
- 확인 경계: 새 작업·30/31 재실행·실모델/provider·유료/GPU 호출·새 검증계 없이 기존 개발계 빌드/시작과 화면, 네트워크 없는 결정/상태 회귀를 검증한다. 과거 작업 snapshot·실행·결과·불명 원장은 그대로 보존하고 과거 화면의 집계 투영과 새 실제 에이전트 실행 계약을 구분한다.
- 외부 통신: 승인 1565553471640572038의 범위로 전사/번역 연결부만 기존 API 외부망에 연결했다. DNS·인증서 검증 TLS 1.3은 양쪽 성공, HTTP 요청 0, 기존 작업/실행/호출 원장 동일. 이는 전사 완주·품질 검증이 아니다.
- 미검증/미결정: 실영상 새 흐름 완주와 콜드부트 전환의 신규 실행 실증은 승인 범위 밖이다. 없는 과거 HTTP 상태·콘솔을 만들거나 불명 호출을 자동 재호출하지 않는다.


## 최신 정정: 콘솔 원문과 멈춘 작업 표시

로그 탭은 시작·종료 이벤트가 아니라 실행기·모델 연결부의 실제 stdout/stderr와 예외를 보여준다. 태스크별로 구분하고 인증정보를 가린 뒤 컨테이너 밖에 보존한다. 과거에 출력·저장하지 않은 로그는 없다고 표시하며 재실행으로 만들지 않는다. 완료·오류·대기 태스크 모두 출력/로그 탭을 유지한다. 확정 오류와 응답 불명 보류를 작업·태스크 화면에 구분해서 보여주되 원래 실행 기록과 재호출 방지는 보존한다. 시험 작업은 생성 근거로 현재 목록에서만 삭제하고 사용자 작업 20·21·30·31과 불명·감사·결과 기록은 남긴다. 새 시험 작업이나 모델 호출은 하지 않는다.

- [x] 콘솔 보존 경로·오류 표시·시험 작업 목록 정리를 기존 개발계에 반영한다. 완료·대기·보류 태스크의 탭과 휴대폰 전환을 실제로 확인했다.

31번 과거 기록에는 HTTPError 이름만 있고 상태 코드·원문 콘솔은 남아 있지 않다. 없는 로그를 만들지 않았다. 현재 모델 연결부는 내부 통신망에만 붙어 Google 주소 조회에 실패하며 API 쪽은 조회가 된다. 전사 실행 복구는 아직 아니다. 새 모델 호출에서 비어 있지 않은 콘솔을 실증하지 않았고, 실패 구분·실제 자식 stderr·보존 파일 수명은 네트워크 없는 단위 검사로 확인했다. 새 작업과 30·31 재실행은 하지 않았다.

## 이번 작업: 테스트 자료 정리와 한국어 자막 번인

- [x] 테스트로 확인된 원본·워크플로우를 현재 목록에서 삭제하고 대상·남은 목록을 기록한다. 실제 영상·기존 작업과 결과는 보존한다.
- [x] '영상 전사·한국어 자막 번인'을 저장하고 다시 읽어 자동 감지·한국어 번역·자막 번인 연결과 사용 가능한 정의인지 확인한다.
- [x] 태스크 패널을 출력/로그 탭으로 나누고 기존 완료·보류 작업으로 실제 기록과 다운로드를 확인한다.
- [x] 기존 개발계에 반영하고 PC·휴대폰의 탭 전환과 스크롤을 확인한다.

새 작업이나 모델 호출은 하지 않는다. 티켓 30은 보류 상태와 기존 기록을 그대로 두고 조회한다. 새 워크플로우의 실제 영상 완주와 모델 품질 확인은 이번 확인에 포함하지 않는다. 테스트 워크플로우 12개·원본 7개는 현재 목록에서 삭제했고, 현재 사용 중이거나 판정이 어려운 워크플로우 2개·원본 2개는 남겼다. PC·휴대폰 탭 전환과 스크롤, 기존 완료 영상 다운로드, 티켓 30의 보류 로그를 실제 개발계에서 확인했다. 대상 ID와 실행·화면 근거는 저장소 밖 작업 기록에 둔다.

## 무엇을 만드는가

전사 에이전트가 오디오를 준비하고 구간별 전사문을 완성한다. 번역 에이전트가 문맥과 자막 시간을 유지해 번역문을 완성한다. 두 에이전트가 쓰는 도구와 수행한 작업을 목록·상세에 연결한다.

## 사용자는 어떻게 쓰는가

원본·모델·언어를 선택하고 작업 시작을 한 번 누른다. 처리가 끝나면 자막과 영상을 내려받는다. 에이전트 상세에서 진행과 작업 기록을 확인하고 해당 작업의 결과로 이동한다.

## 실제로 확인한 것

- [x] 전사·번역이 준비·모델 호출·구간 확인·결과 합치기를 맡아 결과를 완성한다.
- [x] 기존 오디오와 완료된 결과를 재사용한다. 취소 뒤에 다음 모델 요청을 시작하거나, 응답 여부가 불명확한 요청을 자동 반복하지 않는 기존 보호를 유지했다.
- [x] 에이전트 목록·상세에 실제 작업 기록과 사용 가능한 도구를 연결했다. 기존 전사·번역 링크도 에이전트 상세에서 열린다.
- [x] 기존 개발 환경의 작업 #29에서 시작 한 번으로 처리를 마치고 자막과 영상을 내려받았다. 영상 파일을 끝까지 읽어 재생 오류가 없는지 확인했다.
- [x] PC와 좁은 화면을 확인했고, 처리가 끝난 실행기가 정리되는 것도 확인했다.

## 남은 것과 이번에 바꾸지 않는 것

- 실제 모델의 인식·번역 품질은 확인하지 않았다. 이번 결과는 정해진 시험 응답으로 처리 흐름을 확인한 것이다.
- 모델이 사용할 도구를 매 단계 스스로 고르는 기능은 추가하지 않았다. 도구를 편집기에 직접 배치할지도 결정하지 않았다.
- 기존 저장 워크플로우와 진행 작업, 원본·결과·보류 기록은 유지한다. 기존 실행 대기 작업을 대신 시작하거나 과거 불명 요청을 다시 실행하지 않는다.
- 새 서버·별도 시험 환경·권한 확대·승인 없는 유료 호출이나 GPU 실행은 추가하지 않는다.
- 전체 화면 코드 검사에는 기존 실패가 남아 있다. 이번 변경의 검사와 실제 처리 확인이 통과했다는 것과 구분한다.

기술 근거는 [구조 문서의 구현 근거](architect.md#구현-근거-개발-참고)와 아래 이전 작업 기록에 둔다. 현재 확인 결과와 이전의 미완료 상태를 섞어 읽지 않는다.

## 이전 개발 기록

아래는 당시의 구현·확인 기록이다. 현재 전사·번역 작업의 완료 범위는 위 설명을 따른다. 새로운 작업 승인이나 현재 설치 상태로 간주하지 않는다.

### 이전 툴 연결 작업의 기록

- [x] 내부 툴 등록·허용 목록·입출력·공통 호출 경계. 기존 CPU/모델 실행·저장·복구 재사용.
- [x] 툴 목록·상세와 실행 주체의 허용 툴 연결. 고정 처리기와 자율 에이전트 표현 분리.
- [x] 기존 개발계의 새 식별 가능한 통제 작업으로 허브 호출→기존 처리→실제 결과/다운로드 확인. 기동·재사용·회수 재사용.
- [x] source/설치·화면·실행 증거, 실제 모델 품질과 통제 출력의 구분 및 미완료 범위 보고.
- 범위 제외: 워크플로우 편집기/노드 유형/기존 정의·작업 변환, 새 자율 판단 범위 발명, 허브별 상주 컨테이너·별도 검증계, 유료/GPU/#21/과거 불명 재실행, 새 Notion·자동 handoff.


실제 개발계 작업 6f9757e3dbcc434fae808007fde92829에서 기존 LangGraph 전사·번역 노드가 StructuredTool을 호출하고 역할별 영속 기록/채택 결과 및 인증 MP4 다운로드를 확인했다. CPU 실행 소스·캔버스/노드 정의·기존 전송 계약은 변경하지 않았다. 자율 선택/새 자율 에이전트·MCP SDK 호환·보컬/기존 GPU 실행 전환은 완료로 세지 않는다. 전체 frontend lint/test에는 변경 전 소스와 같은 기존 실패가 있으며 좁은 변경 검사·타입/빌드는 별도로 통과했다.

## 현재 최우선: 기존 전체 작업(얼굴합성 제외) renewal 연결

기존 업로드 d54/Gemini 목록 매핑 214f의 운영 수용은 종료 상태로 유지한다. 현재 운영은 accepted 214f scoped API/web·normal·기존 19+021이며 이번 후보와 분리한다. PM1563433804524421122에서 60135e8d2d→04c35f4691→e25831b36e의 기본 경로 소스와 제출된 격리 증거를 수용하고 App publish를 완료했다. Windows 원 저장소의 원격 renewal도 e25831b36e67852aa8314f2e4544246881ab1e93으로 읽기 재조회했다. 운영 반영·기존 전체 기능 동등·실제 공급자 품질/유료 실행은 아직 미완료다.

- [x] 실제 refs/WIP/운영 pin 보존. main 없음, master 57d34e99 읽기 비교, renewal 214f 단독 격리 후보 작성.
- [x] 공용 캔버스 내부 하단 도구·40px 선 선택·연결해제·입출력 재연결·취소/Esc·설정/모델핀 보존 undo. 실제 PC1440/390 조작과 정상 PostgreSQL/CAS 저장·재열기 완료. 이미 확인한 이 경계는 반복 시험하지 않는다.
- [x] 기존 번역 프로필/모델·연결·키 개정 보존, 공식 근거 있는 Gemini 명시 전사 variant/개별 proof/새 호환 개정·NodeModelBinding 고정/저장·재열기. 실제 공급자 호출권한·인식 품질 수용은 아니다.
- [x] 편집형 전체작업 정의: 분석→추출→전처리→전사→번역→원문/번역 SRT·SMI→선택 검수→영상 합성→검증. 검수 기본 노드는 유지하고 no-review는 명시 옵션으로만 만든다. 과거 저장 정의/티켓은 자동 교체하지 않는다.
- [x] 명시 bounded batch 정책/티켓 호출 상한·노드 시간상한, PCM 프레임 분할·원본/입력/clock SHA·언어·후보/모델/연결개정 결속. 단일 음성 60초/2MiB·번역 100구간/16000 UTF-8 bytes·전역 입력/결과 한도는 그대로다.
- [x] 후보 022 per-chunk intent/참조 cache/단조 호출 budget. 실제 PG에서 intent commit 전 외부 진입0, 완료 참조 재사용, 결과 commit 실패/유실 intent unknown·held/재과금 금지, 살아 있는 guard 비고아화, 고정 상한/언어/원본/PCM clock 변조 거부 확인. 운영 022/권한 적용은 안 했다.
- [x] 저장한 실제 frontend 정의의 121초 합성 입력→정식 preview/create/plan/confirm/admit/run→독립 API/results/model 프로세스·별도 CPU consumer→분할 전사 3회→번역 1회→원문/번역 SRT·SMI→실제 영상 생성/전체 decode·인증 다운로드 SHA/manifest 확인. 실제 TLS MQ/S3와 PG, 통제 HTTP 응답이며 공급자 인증/품질·운영 사이트 증거가 아니다.
- [x] 바뀐 경계만 좁게 검증: 실제 분할 사이 취소 뒤 다음 구간/번역0, 명시 기존 recovery·위험인지·새 동의로 완료 구간 재사용. dense 자막에서 100구간/16KB 분할과 ID/순서/시각 보존. 최신 guard 설치 프로세스의 완료 참조 재전달은 HTTP/추가 budget·receipt0, 위조 참조2개는 격리 큐만 거부하고 manifest 불변.
- [x] subtitle revision3의 SRT+SMI 별도 출력/원문·번역 언어, 실제 .smi 인증 다운로드와 MQ 옵션별 output 검증. 기존 revision1/SRT 기본 계약은 유지한다.
- [x] CPU 전처리 9392b123은 PM1563438659888218175에서 소스 수용/App publish 완료했고 원격 renewal SHA도 같은 값으로 재조회했다. 운영·NVIDIA 실실행 수용은 아니다. 명시 silence_pack_v3/revision3로 conservative(10초)·strong(5초)·silence3(3초), -45dB/0.2초 padding과 정수 PCM-frame 복사를 연결했다. off/revision1을 자동 변경하지 않으며 기존 300초 clock·256MiB 한도를 유지한다. 새 정의/정식 티켓→설치된 CPU 자식 실행과 원시각 복원을 좁게 검증한다. 운영 반영·NVIDIA VAD·긴 clock 지원은 아니다.
- [x] fd5b455b의 NVIDIA 계약·구간 적용은 PM1563448261023633529에서 소스/제출 통제 증거 수용·App publish 완료했고 원격 SHA도 재조회했다. 실제 GPU/운영 수용은 아니다. nvidia_regions_v4는 명시 NVIDIA 엔진/고정 모델/옵션 명령만 사용한다. source SHA·PCM frame 수에 묶인 선택 audio_regions CAS 입력을 검증하고, master 순서(무음 유지구간→보호 0.3초 확장/합침→겹친 제거제안 전체 veto→원본좌표 제거→VAD 최종 교집합)로 적용한다. CPU 프로필/기존 GPU off-only 경로는 자동 승격하지 않는다.
- [x] 통제 CUDA-child 응답으로 정확 PCM·빈 결과 실패·잘못된 source pin의 child 진입0·CPU 요청/위조 VAD 구간 거부를 확인한다. 실제 PG 저장 정의/정식 티켓은 protocol2 GPU/model pin을 claim만 하고 dispatch하지 않는다. 별도 통제 clock-shaped 입력으로 기존 registered ASR 단일/분할·번역 소비와 잘못된 audio pin의 HTTP0을 검증한다. 이를 실제 GPU→ASR 전체 여정이나 S3/MQ·품질로 합치지 않는다.
- [ ] 실제 NVIDIA GPU inference 및 운영 target/slot 등록·기동은 별도 명시 실행 경계다. 소스 수용으로 실행하지 않는다. 모델 파일 SHA·입력 SHA/길이·단일 실행 상한을 고정한 비운영 fixture만 별도 판단하며 외부 공급자 유료 호출과 혼동하지 않는다.
- [x] 6d811597 수동 구간 검수/결정 CAS/CPU 소비는 PM1563471820278206595에서 소스·제출 격리 증거 수용/App publish 완료했고 원격 SHA를 재조회했다. 운영/GPU/자동 보컬 runner는 미반영이다. audio_regions_v1 검수 producer의 제품 보호/제거 배열 편집·저장/재열기→원본 audio SHA/frame 고정 CAS 확정→새 계획/동의/접수→regions_pack_v4/revision4 실제 CPU 소비를 연결했다. 300초/256MiB는 유지하고 결정 포트만 128KiB·각 1,024구간으로 제한한다. 과거 일반 검수/프로필은 자동 승격하지 않는다. 새 검수의 반복 확정은 동일 CAS/상태로 반환하며 stale/취소/임의 source 덮기를 막는다.
- [x] 새 결정 CAS→명시 NVIDIA 고정 명령 전달은 실 PG claim까지만 검증한다. GPU dispatch/inference는 0이다. 인증된 오디오 source 읽기/확정 전 별도 대기·공개 DTO의 내부 request 비노출·로컬 CAS/S3 경계는 보존한다.
- [x] PC1440/390의 새 검수 화면에서 실제 격리 PG/auth/CAS 저장·재열기·확정·새 동의 후 CPU 소비와 source decode/SHA를 관측했다. PC/모바일 업무 변경은 앞선 실행에서 완료했고 검증기의 비공개 request 필드 기대/정상 GET abort 분류 오류 뒤에는 완료 작업을 재실행하지 않고 읽기 재조회했다. 혼합 세대 관측을 한 번의 fresh all-pass 실행으로 재구성하지 않는다. JSONB 속성순서와 무관한 시작→끝 표시/체크박스 배치를 보완했다.
- [x] 자동 vocalization의 도메인 프로토콜은 master의 30초 중심/앞뒤 2초 문맥, 전역 speech/uncertainty 보존, strong 0.15/그 외 0.3초 경계, 0.1~8초 제안 및 문맥+정확구간 독립 확인/늦은 veto를 통제 응답으로 구현했다. 동일 frame 제안 중복 확인을 줄이고 취소/고정 호출 상한/잘못된 bool 승인 거부를 검증한다. 이 도메인 함수는 HTTP/키/기본 모델을 갖지 않고 제품 route/실행 factory에 연결하지 않았다.
- [ ] 자동 탐지의 등록 모델 목적/호환 proof·불변 연결/키·SQL intent/불명 보류·유료 승인 runner 연결은 미완료다. binding digest와 함수의 메모리 호출 상한은 승인/영속 과금 보호가 아니므로 실제 공급자 실행에 사용하지 않는다.
- [x] 03ace76d projection-only는 PM1563481434331684898에서 소스/제출 통제 증거 수용·App publish 완료했고 원격 SHA를 재조회했다. 그 batch-policy 사례의 ASR은 1회이며 복수 분할 실증이 아니었다. 명시 packed_projection_v2에서 제거 구간을 가로지르는 문장을 원본 구간별로 분리하고 master의 full-sentence-repeat 정책을 따른다. 단어별 정렬을 추정하지 않는다. 원래 literal ID/text/speaker/packed 시각과 각 원본 piece/새 child ID/드롭 사유를 trace에 연결하고, parsed packed transcript CAS·audio/timeline/output SHA를 고정한다. 기존 옵션/티켓은 legacy envelope 복원 그대로다.
- [x] 실제 PG 저장 정의→수동 검수/CAS→새 동의→설치 CPU 실제 제거→통제 HTTP ASR(단일/분할)→projection/trace CAS→번역 ID·시각 보존→SRT/SMI 소비를 좁게 검증했다. 잘못된 frame clock은 HTTP0, 후처리 실패는 원 전사 CAS를 보존하고 번역/모델 재호출 없이 실패로 남긴다. 통제 응답이며 인식/번역 품질·운영/MQ/GPU 증거가 아니다.
- [ ] 좁은 회귀의 과거 test_transcription_execution 두 케이스는 공식 공급자에 loopback endpoint를 넣어 현행 연결 계약에서 거부된다. 새 후보와 6d의 변경 모듈을 복원한 비교 이미지에서 동일 실패를 확인했고 가드를 완화하지 않았다. 그 비교 이미지는 과거 원본 이미지의 재검증이 아니다. 유효한 Custom fixture의 기존 단일/분할 소비 회귀는 별도로 통과했다.
- [x] 후속 미수용: audio_long_v5의 원본 보관 한도(기존4GiB)와 이 오디오 pipeline 영상 입력(256MiB), 파생 PCM 입력/출력(1GiB), source/packed frame(각6h×16k), timeline/전사/trace/각자막(16MiB), regions(128KiB)을 분리했다. snapshot에는 정책/역할 상한을, CPU revision5/등록-model command에는 정확한 선택 역할·실제 처리/command/lease/call 예산을 동결한다. 기존 clock/role 기본값은 올리지 않는다.
- [x] 새 regions_long_v5 CPU producer는 실제 입력/출력 PCM frame 수·원본/packed SHA와 정책 SHA를 version5 clock에 결속한다. packed_projection_v5 소비는 새 media budget·동결 wrapper를 요구하고, 옛 reader/ticket은 새 clock을 자동 수용하지 않는다. 선택 전처리/보호 구간·SRT-only/SRT+SMI 선택을 유지한다. 기존 analyze/encode/validate는 기존256MiB·60s native process/90s command/120s lease로 남기며 이들의 긴 실행 예산을 조용히 올리지 않는다.
- [x] 실제321초 합성 원본의 설치 CPU 추출/수동 결정 CAS/packing→6 ASR HTTP chunk→gap projection/trace→2 bounded translation chunk→SRT/SMI 소비를 검증했다. PCM 제거 bytes, 각 chunk SHA/연속 frame coverage, ID/시각/직렬화 bytes를 대조한다. 실제 프레임상 최소 ASR 호출 수와 직렬화된 번역 분할 수가 선택 cap을 넘으면 해당 역할 HTTP 전에 거부한다. 처리/산출물/trace cap은 실제 파일/UTF-8 bytes에 적용하며 넘치는 SAMI는 파일 쓰기 전에 거부한다.
- [ ] 6h는 새 계약의 최대값이지 실제6h 전체 성공이 아니다. >256MiB 파생물/독립S3·MQ/큰 원본 오디오 pipeline 및 긴 encode 실행 예산·GPU long profile·6h 전체 실증·구신 consumer 혼합·운영은 미검증/미활성이다. 원본4GiB 업로드 보존을 해당 오디오 pipeline 입력4GiB 지원으로 세지 않는다.
- [ ] 검수·다국어 및 같은 사설사이트 여정을 이어간다. 기존 packed_projection_v2는 source/packed 300초·결과 10,000구간/16MiB 한도이며 전역 300초/256MiB는 유지한다. 새 policy 명령은 갱신된 등록-model application consumer가 필요하며 구버전 consumer 혼합/운영 접수는 승인하지 않았다. 후처리 실패 CAS의 제품 재투영/복구 UI도 별도다. 현재 결정 적용/통제 응답은 탐지·확인 품질 수용이 아니다. CPU 전처리 off/no-review의 기본 경로 성공을 기존 전체 작업 동등으로 종료하지 않는다.
- [ ] 긴 원본의 역할별 CPU/clock 계약: 현재 기존 audio clock의 packed 300초와 CPU 역할별 256MiB 경계는 유지돼 있다. 새 분할 helper의 6시간/1GiB 상한은 전체 6시간 작업 지원 증거가 아니며 전역 한도를 풀어 해결하지 않는다.
- [x] 기본 경로 3묶음의 좁은 source gate/PM 수용·App publish(e25831b36e). 이후 CPU 후보 및 남은 동등성은 별도 미수용이다.
- [ ] 같은 사설사이트 운영 활성화/필요 WebM 의존 연결→실제 원본·워크플로우 선택/고정/실행·재생·다운로드. 020/022 및 최소 권한/전용 캐시/프로세스 연결은 격리 검증과 운영 적용을 분리한다.
- [ ] 실제 공급자 유료 호출은 모델·입력길이·호출/비용 상한 승인 후에만 수행한다. 현재 호출은 통제된 격리 peer뿐이다. 얼굴합성/root키복사/포괄GRANT/새 공개망/타호스트 이전과 운영 #5/DLQ/accepted/initializer 조작은 제외한다.

검증 정본: legacy-equivalent-workflow-214f1fe313/installed-long-evidence-r2 및 좁은 PG/코어 로그. 최초 하네스의 admit 뒤 run 누락은 waiting/runs0/outbox0/provider0으로 분리했고 원 사실을 보존했다. positive 설치 실행과 그 뒤 추가한 budget/언어/프레임 guard의 검증 세대를 분리한다. 예전 mutable app tag는 현재 inspect 불가이므로 당시 build log를 후대 전체 byte readback으로 표현하지 않으며 최신 guard 이미지는 별도 고정했다. 최종 후보 설치본의 shared/API 실제 113경로 byte readback 일치와 최신 프로세스의 완료 참조/위조 참조 경계를 확인했다. 호출 직전 원 PG 세션/정확 advisory guard 재검사와 실제 세션종료 뒤 adapter HTTP 진입0도 별도 좁게 검증했다. 기존 Starlette/httpx와 Vite chunk 경고·변경 Python의 부모 4진단을 숨기지 않는다.

## Gemini 용도 매핑 — 214f 운영 수용 종료 / 아래는 당시 후보 기록

- 업로드 d54a2e118e의 동일 사설 운영 반영과 대표311,042,538byte UI→등록/재조회→native다운로드 SHA 확인은 PM1563251284352700457 수용으로 종료했다. 원본23/작업8·기존19+021·006SHA/020부재·normal·기존자료/키/WIP/롤백 보존을 승계하며 업로드 재시험/재배포나 별도 docs-only 왕복은 요구하지 않는다. 아래13b/업로드 후보 문구는 그 당시의 역사기록이다.
- 수용 classifier의 Gemini 정확3ID 제한 때문에 실제 기존키 GET의 gemini-2.5-pro 등 다른 확인된 텍스트 모델이 profile=None/용도 미확인이었다. 공급자 목록 자체는 계속 실제 GET으로 발견한다. capability 근거표는 드롭다운 모델목록의 대체물이 아니며 generateContent/이름접두만으로 용도를 부여하지 않는다.
- 실제60개에서 허용된 공개 metadata 필드와 Google 모델/API 문서·공식 googleapis/python-genai Model literal 근거, 현재 Gemini 텍스트 어댑터의 교집합을 대조했다. 같은 기록metadata의 최종 설치parser replay는 번역후보16/현재제품미지원23/근거미확인21이다. 기존3모델의 canonical profile(멀티모달 유형 포함)은 정확히 유지하고 새 후보는 최소text/text_generation만 부여했다. 전사/타임스탬프 role은 자동 부여하지 않는다.
- 실제latest3개 version은 사람이 읽는 영문라벨이고 baseModelId는 없었다. 특정 모델로 resolve했다고 만들지 않았다. 공식SDK의 유한 latest변형 literal+실제 name/version/displayName/description/method를 대조해 최소텍스트 후보만 표시하고 기반모델 미고정/제공사변경·실행미검증을 알린다. 통제된 version-witness 검사는 별도 합성 경계이며 실제60개 버전필드로 주장하지 않는다. 문서상3.5Flash→3.6/3.7Flash→3.8 제공사라우팅은 알리되 저장/요청ID를 바꾸지 않는다.
- 알려진 이미지/TTS/임베딩/Live/predict/종료preview 및 전사기능이 알려졌지만 현재제품 연결계약이 검증되지 않은 전용전사는 현재제품미지원으로 구분한다. 근거미확인은 별도이며 키없음·401/403/429조회실패·성공한빈목록을 모델분류와 섞지 않는다. 공급자 자체가 전사/생성을 지원하지 않는다는 뜻은 아니다.
- 설치 후보 실제Python33검사(순수31+실제PG/ASGI등록보존2)·Node표시3·타입/build·변경범위 lint/format을 확인했다. 기존Starlette/httpx·Radix경고/전체lint 부채는 보존한다. API/DB의 암호화 키/참조·connection개정과 기존Flash모델 row/profile을 유지하며 Pro 일반등록/재조회, 위조model/profile/누락proof422·기존개정CAS409를 확인했다. 새마이그레이션/GRANT/Registry/CredentialStore 변경은 없다.
- 별도 실PG와 실제운영 API table/column ACL 복제 LOGIN/CREATE불가·합성키·정상로그인/CSRF/컴파일웹/실제Edge PC1440와390에서 기록60개 upstream GET replay를 사용했다. Pro 번역후보 선택/정상저장200/개정1재조회와 latest미고정 안내, TTS현재미지원·aqa근거미확인/저장차단·각 viewport 문서넘침0/오류0을 확인했다. 실제공급자 재호출·추론/품질·운영계정 등록 성공으로 확대하지 않는다. 네이티브PNG/JSON 및 최종정적JS·CSS SHA 결속을 보존한다.
- 운영은 여전히 수용d54 업로드 API/image4604f41d6bb8·web558b030c0492이다. 다음 반영 후보는 이 현재기반 위 backend model_catalog.py/gemini_catalog.py 2개와 web ModelCatalogPicker.tsx/model-catalog-purpose.ts 2개뿐이다. 소스 검토/App publish 뒤 동일운영에 연결한다. 020/preview접수·runner/키root복사·등록모델consumer/paid·실전사번역·타역할/slot/GPU/#5/DLQ/accepted/initializer/WIP 보존은 계속 별도 경계다.

## 원본 직접 업로드 4 GiB 보정 — 당시 후보 검증 기록 (운영 수용 종료는 위 최신기록)

- PM1563217001281888378 지시에 따라 WebM 운영 준비보다 업로드 결함을 먼저 처리했다. 실제 설치의 요청모델/서비스/DB expected_size/조립 저장이256MiB였고 최근 원본 신청POST422를 확인했다. 사용자 SWXP68.mp4 파일은 복사·변경·삭제하지 않았다.
- 원본 전용 MAX_ORIGINAL_UPLOAD=4,294,967,296bytes로 요청/서비스/새021 CHECK/조립 저장을 맞췄다.006 원문/SHA·전역 MAX_CONTENT256MiB·4MiB 청크·HTTP body·CPU/타역할/결과 예산은 그대로다. 초과는413과 실제4GiB 한도를 안내한다.021은 명시적으로 단독 적용/체크섬 기록해야 하며 전체 pending migrate로020을 끼워 적용하지 않는다. 운영 DDL은 아직 미실행이고 새 GRANT 요구는 없다.
- 큰 원본 완료는HTTP202 뒤 같은upload 상태를 조회한다. 현재 단일 API 프로세스의 별도 조립 thread1/최대 접수2이며 독립 preview/model consumer가 아니다. 업로드 청크는 SQL/CAS에 남고, 서버 재시작으로 미시작/중단된 조립은 같은 업로드에서 명시 완료 재시도한다. 영속 작업큐/자동재실행으로 표현하지 않는다. API 종료 시 새 조립을 막고 진행 작업 종료를 기다린다.
- 조립/원격 SHA/ffprobe/썸네일 I/O 동안 업로드 행·장기 SQL transaction을 잡지 않는다. 같은 전용 PG advisory session이 최종 짧은 transaction/소유키 재검사/원청크 재대조/asset INSERT와 upload 결속 commit을 수행한다. 유실 세션은 다른 연결로 채택하지 못한다. 중복 완료는 같은 asset이고, 알려진 파생물 미준비가 검증된 원본 등록을 막지 않는다.020 없는 normal에서는 full preview 자동접수/경로를 켜지 않는다.
- 재선택 검증은 모든 보존 바이트를4MiB 단위로 대조하되 서버는 겹치는 청크만 읽는다. 뒤쪽 범위 검증마다 앞 청크를 다시 다운로드하던 경로를 좁게 고쳤다. 임시 조립/원격검증 중첩에 필요한 추가 디스크를 사전 확인하며 본문 전체를 메모리에 올리지 않는다.
- 별도 실제 PG(020 제외, 기존 API table/column ACL 복제·CREATE불가)/검증TLS MinIO/설치 API·컴파일 웹/Edge에서 합성 RGB24 MOV2,211,843,938bytes(1280x720/10fps/80초, padding없음·전체 native decode0)를 실제390px 파일 선택으로 전송했다.24MiB 보존 후 일시정지→새로고침→같은 파일 재선택·prefix6범위 검증→같은upload9a8bb06eb7184967a70db2c1cd77389c→완료POST202 1회→asset d4116be824974e4e87dfed4a34c295be 등록/재조회→UI 원본받기/native Edge 저장을 확인했다. 원본/등록/저장파일 SHA e985101bbb13b2dd6e57cf617e8f7dbc43ac702245cc5140347c88e9dde12685 일치다. 전송·재선택·조립/등록 합379.889초이지 순수처리속도/전체4GiB 성능 보장이 아니다. 실제 조립 guard는 idle/xact없음, API부모 VmHWM223348KiB 관측이다.
- 작은 유효MP4의 청크/중복/변경prefix/정상등록·공유다운로드 회귀와 실제 PC1440 최종UI1613byte 업로드/다운로드를 큰 파일과 구분했다. 최초 AVI 합성 샘플은 공통 probe 허용포맷 밖이라 전송 후 등록이 거부된 별도 음성검사로 보존했고 global 포맷목록을 풀지 않았다. 최초 업로드 상태 팝오버 미개방 하네스 실패/부분청크도 보존했다. 해당 AVI 실패를 MOV 성공으로 덮거나 원 업로드 내용을 바꾸지 않았다.
- 새 원본 PG 좁은7검사와 Node 업로드12검사를 통과했다. 행 잠금100ms barrier, 중복완료/세션종료뒤 채택0·명시재시도, 크기/초과·S3기본상한 보존을 포함한다. 최종 타입/build·범위 신규 lint0, 기존 PythonF4011·StorageUploads curly1/Starlette·Radix 경고는 유지한다. 큰 파일 전체 전송 JS SHA cac830c3ee480daae3275ba9dc80bee8b471c28613babfae24a6ab49146e2e89는 최종 번들과 같다. CSS 변경 뒤 같은 완료 원본390px 재열람/캡처와 작은 파일을 대표 재확인했으며 큰 파일 재전송으로 세지 않는다.
- 현 운영은13b scoped API(1da+수용5모듈)/웹(c826+수용5소스)·normal 그대로다. 배포 후보도 그 기반 위의 원본 변경만 담고 results/engine-results/dispatcher·물리agent는 교체하지 않는다. rollback은 원본/청크/021/신규 큰 원본을 보존해야 하며, 옛256MiB 완료 코드로는 새 큰 미완료 업로드를 끝낼 수 없는 제한이 있다. 키/WIP21/backup/#5/DLQ/accepted/initializer·대상/slot/GPU/유료·provider 추론/020·runner·S3 root 자격 복사는 건드리지 않았다. 소스검토/App publish 후 같은 사설 운영 반영이 남았다. Gemini 용도 매핑은 그다음 별도 수정이다.

## 직전 우선 묶음 종료 수용 기록

-13b4b509 소스/App push·같은 운영 API/웹·Gemini60→후보3→단일등록/불변개정 재조회는 PM1563192535407399077 수용이다. 작업 상세390 보충도 PM1563194839087059056 수용으로 종료했다. 옛1280x720 PNG/원보고 보존 및 재분류, 옛 원인 미확정과 기존20회/새release·cancel각1의 분리를 승계한다. 아래 과거 미완료 표기는 각 당시 기록이며 현재 우선 묶음을 다시 열지 않는다.


## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 최우선 캔버스 터치·공식 공급자 등록/목록 — 변경 검증 완료, 소스 검토·운영 화면 연결 전

- 최신 지시1563115933810298952와 보충1563116507637096481에 따라 워크플로우/작업 상세 공통 캔버스, OpenAI·Google Gemini·Anthropic Claude·xAI Grok 등록/공식 모델 조회를 먼저 처리했다. WebM 운영·전사/번역 실사용·Loop/Fallback보다 앞선 범위다. 운영 반영은 이미 지시된 범위이며, 개발→변경검증→PM 소스 검토/App push→같은 사설 주소 운영 확인 순서만 유지한다. 목록 조회 허용을 생성·유료 호출 승인으로 확대하지 않는다.
- 실제 운영 웹c826의 같은 JS/SHA·vault 로그인에서 두 상세의 touchStart/연속move/release·cancel 백화와 null x stack을 확보했다. 공유 WorkflowCanvas에서 enqueue 전에 좌표/drag 값을 포착하고 pointer 소유권·capture/lost/cancel 정리를 고쳤다. ErrorBoundary로 감춘 것이 아니다. 최종 운영기반 후보 번들을 브라우저에서만 overlay하여 실제 읽기 API와 PC1440/390px 두 상세를 각각100회 검증했다: pageerror/백화/unsafe 요청0, 이동·선택·확대·전체보기 유지, 정의 SHA 불변이다. overlay는 검증 뒤 해제했고 운영 배포로 세지 않는다. 별도 실제 PG/API 위치 저장·재조회/CAS409와 옵션/model_ref/fallback_refs/입력/edges 보존을 확인했다. 운영8작업 snapshot의 원 PostgreSQL JSON text SHA도 변경 전 실제 복원 backup과 같다.
- 네 이름 있는 공급자의 새 등록은 URL/protocol을 서버 정본으로 고정하고 폼에 주소를 요구하지 않는다. Grok은 xai 공급자이며 OpenAI-compatible 사용자 분류로 합치지 않는다. 커스텀/로컬/사설은 명시 URL을 유지한다. 기존 주소/protocol·키 참조/과거 개정·모델/티켓은 조용히 개정하지 않는다. 비정본 옛 연결의 공식 조회는 거부하고 사용자의 명시 개정을 요구한다.
- 서버가 선택한 저장 연결의 현재 키로 공식 모델 GET을 수행한다. 응답 metadata+공식 capability 근거+현 adapter 교집합만 용도 후보로 표시하며 불명/미지원은 구분한다. OpenAI 목록의 id만으로 capability를 추측하지 않고 Gemini generateContent를 STT로 표시하지 않는다. Claude는 공식 명시 버전·pagination, xAI는 language-models의 modality metadata를 사용한다. 선택 모델·용도·owner/connection 개정·내용 SHA/key 참조/기한에 결속한 암호화 proof를 기존 CredentialStore 키로 검증한 뒤 일반 CAS 등록/재조회한다. 새 키 저장소나 조회용 테이블·마이그레이션은 없다.
- 공급자별 정본 HTTPS origin·GET 목록 path만 허용하는 별도 전송을 사용한다. DNS 결과의 공인 unicast 주소를 고정하고 원 Host/SNI·기본 인증서 검증을 유지한다. env proxy/redirect/다른 주소 자동 재시도·POST 추론 전송 완화는 없다. 응답 크기/페이지/모델 개수와 socket timeout/query deadline을 제한한다. 키 없음·401/403/429·빈 목록·불명 응답·오래된/위조 proof와 전환 중 늦은 응답을 별도로 처리한다. 브라우저에는 키/응답 원문을 보내지 않는다.
- 1563147503455445033은 DNS 원인분리 지시이지 새 설정 승인으로 해석하지 않았다. 실제 API는 Docker127.0.0.11 내부 postgres는 응답하나 사이트/공식4곳 SERVFAIL·default route 없음·설정 upstream192.168.65.7 및 공인 숫자IP443 모두 unreachable였다. 호스트와 기존 web namespace는 같은 조건 DNS/TLS/무키401·403을 통과했다. MagicDNS 전체 장애나 숫자 URL 해결로 단정하지 않았다. 앞선1563146957751590953의 API-only 송신 복구 범위로 기존 검증된 video-subtitle_ingress를 API에만 연결했다. API 재시작/공개 포트/다른 역할 망·전역 DNS/Tailscale/URL·TLS 검증 완화가 없다. 실제 API와 설치 후보의 동일 network namespace에서 네 공식 host DNS/검증 TLS, Google403·나머지401을 확인했으며 이는 인증/목록 성공이 아니다. canonical API metadata에 egress network와 좁은 disconnect rollback을 남겼다.
- 최종 실제 격리 PG source36/설치 후보36, Node64, 목록 계약 browser PC/390px6, 통제 HTTP native 공급자3을 각각 구분한다. 최종 source/운영기반 후보 타입·build, 범위 ESLint/format/Ruff0 및 설치5모듈 SHA를 확인했다. Starlette/httpx·Radix 기존 경고와 전체 lint/format 기존 부채는 남는다. 최초 RED, capture 회귀 RED, Connection-close bounded-read RED와 하네스 실패는 지우지 않았다. 증적 정본은 mediagent-renewal-ops/touch-frontier-ae8088e2다.
- 현 운영 source1da/웹c826·normal/broker/control·단일 CPU는 유지되고 API egress만 복구됐다. 새 화면 설치·저장된 실제 키의 공식 목록/선택·등록·재조회 운영 확인은 소스 검토/App push 다음 단계다. 키 없음/업체 거부를 통신 실패와 분리해 남긴다. 비용 실행/독립 model consumer·GPU/020·preview runner·대상/slot 변경은 없다. 앞선 ae8088e 전체길이 WebM/guard의 PM 수용·App push 종료 기록을 승계하고 기존 미디어·PG 전체 검증을 재개하지 않는다. 원본/키/DB/WIP/backup/rollback과 #5/DLQ/accepted/initializer 보류를 유지한다. 아래 미완료 문구는 각 과거 묶음의 당시 기록이다.

## 전체길이 WebM guard 세션 유실 보정 — 81b 위 corrective / 운영 미변경

- PM1563035656211402762가 81b의 소스/40초 동선·기존 증적은 확인했고, App push 전에 단일 소유권 경계만 보류했다. 살아 있는 Python 객체/self.guard 참조는 PG session advisory lock의 소유 증거가 아니다. reviewer 원본 probe/result와 81b 소스·패킷을 그대로 보존했다.
- 별도 실제 PG에서 제출81b+정확한020/첨부코드로 **A guard backend만 종료→B exclusive→queued2→A/B 각각claim, running2/서로다른instance/각claim1**을 직접 재현했다. 실제 FFmpeg 두 개나 운영 fault를 돌린 것이 아니다.
- 선점·중간 상태·최종 채택 SQL을 모두 잠금 소유 **동일 PG 세션의 transaction**으로 옮겼다. 그 transaction 안에서 자기 backend의 정확한 advisory key/lock을 확인하며, 별도 SELECT1/guard.closed 사전확인과 다른 connection의 UPDATE로 나누지 않는다. 세션이 끊기면 그 선점/채택 transaction도 성공 반환하지 못한다. running/held가 있으면 같은 소유자도 두 번째 선점을 받지 않는다.
- 소유권 유실은 객체를 영구 fenced/held로 latch하고 재접속·재등록·재claim하지 않는다. native 직전 확인·Popen·encoding stage 기록도 같은 owned transaction에 묶고, 처리중 확인·최종채택 역시 같은 소유 세션을 사용한다. 유실 시 자기 자식만 종료/관측하고, 정상 ready/failed로 덮지 않고 원 DB 상태와 불명 private scope를 보존한다. 새 실행기는 이전 running을 기존 정책대로 held로 남겨 추가 실행을 막는다.
- 보정 probe는 **A claim불가/B claim1/B추가claim불가/running1**이다. 최종 실제 PG 좁은7검사: stale-owner 교체, 대기 정상종료/재기동+중단held, 입력검증뒤 실행전 유실, 최종채택중 유실, 선점 UPDATE뒤 commit전 유실/queued불변, native-launch/monitor 유실2경계다. native2경계는 실제 짧은 Python 자식의 소유/종료와 DB원상태·scope보존을 본 통제 lifecycle fixture이며 인코딩 결과를 위조하거나 영상 성공으로 표시하지 않는다. 최초 해당 소스RED6+기존경계1pass, 보정7pass/Starlette경고 보존·변경 Ruff0다.
- 기존 **40초331,778,658byte→1,597,969byte/SHA ea3c6e6f…·600frames/PC1440·390·생성취소404/최종13·Node60**은 81b 제출·reviewer 확인 범위로 유지하고 다시 실행하지 않았다. FFmpeg argv AST·preview profile/020·API/UI bytes는81b와 동일하다. 이번 설치 보정 worker 모듈 SHA를 소스와 대조했다.
- 운영은 normal/기존22원본·8작업/30초판·원본다운로드 그대로다. 이번은 source corrective와 disposable PG뿐이며 운영 DB/서비스/권한/실행slot/키·원본17·#5/DLQ/accepted20·initializer/유료/provider/GPU를 건드리지 않았다. 기존 WIP21/운영16의 generation/config/mount를 보존했다. 원81b source/증적을 대체 삭제하지 않고 corrective commit·combined patch/bundle로 인계하며 **소스 수용/App push 및 운영 승격은 각각 미완료/별도**다.

## 전체길이 영속 비동기 WebM — 개발·격리 확인 완료 / 운영 승격 전

- PM1563013463947616337에서 **1da32470 대용량CPU 운영 반영을 수용 종료**, 후속문서 `a9a04b59643b79123a148a3fd8bf31c41bfca66b`까지 App push·Git/GitHub API 일치를 확인했다. 이 묶음 시작 시 Windows HEAD/직접 ls-remote도 a9 일치였다. 아래 과거 개발·운영 기록은 당시 상태이며, CPU 운영은 현재 normal/원본22·작업8/같은slot cap1·epoch2다.
- 이번은 그 위의 **개발·격리만**이다. 020 additive `video_preview_jobs`에 원본 custody/ref/SHA·고정 profile, 또는 정상채택 ticket/node/run/attempt/generation/port·snapshot/accepted-receipt SHA·ticket storage ref를 별도 불변 요청으로 저장한다. 동일 결속의 요청은 같은 영속 id를 돌려준다. SQL-only 요청/상태/취소이며 HTTP에서 원본 fetch·WebM 생성을 하지 않는다. 새 업로드와 공통 CPU 정상채택은 대기 sidecar만 등록하고, 미지원 preview/가득 찬 자동대기는 별도 실패로 남겨 원본 업로드·본 작업 채택을 실패시키지 않는다. 수동 미지원 요청은 거부한다.
- 독립 opt-in `python -m video_service.full_preview_worker --dsn-file <private-leaf> --object-config <private-leaf> --cache-root <real-disk-mount> --enable-full-previews`가 처리한다. API background task/브로커 TTL 변경/단순30초 제한 삭제가 아니다. 같은 DB/schema의 전용 PG session advisory guard로 동시1·claim_count<=1을 지킨다. SIGTERM은 새 claim을 멈추고 현재 작업을 끝낸다. 대기 작업은 재기동해도 유지하며, 이전 running/session 유실·object storage의 미확정 결과 또는 남은 private scope는 **held·자동재실행 금지/전체 preview runner 보류**다. 보류 해제/재시도 자동화는 이번에 만들지 않았다.
- `full-webm-vp9-opus-v1`: 입력4GiB·6시간·8,294,400픽셀/각변4096, 출력512MiB, 전체 I/O+생성 wall4시간, private cache10GiB/시작free>=10GiB, 대기최대32·동시1, 최대960x720/15fps VP9+선택 Opus. POSIX 독립 main-process wall alarm으로 storage I/O도 시간한도에 포함한다. bounded streaming/CAS·파일 상한·실제 ffprobe 길이차<=0.25초·원격 재조회 SHA/metadata 검증 후에만 ready를 저장한다. 상한 성능보장은 아니며 일반업로드256MiB·CPU/타역할 입출력·저장읽기8GiB는 바꾸지 않았다.
- 캐시는 명시 disk bind만 허용하고 tmpfs/ramfs 및 config/cache 불일치를 거부한다. 실제 UID10001→host marker readback/free·동일 destination tmpfs 부재를 확인했다. 정상/알려진 실패/취소는 자기 per-job cache scope만 정리하고 storage미확정/탈출예외의 자기 scope는 판단용으로 보존하며 S3 원본/산출물/불명 scope를 삭제하지 않는다. runner는 신뢰 application-side 역할이며 기존 실행 agent slot/target/host를 추가하거나 변경하지 않는다. fixture 제한 LOGIN 역할의 jobs/accounts 쓰기·password 읽기·preview 요청 INSERT 권한은 false였다.
- 기존30초판·원본받기·과거 manifest/accepted receipt/원파일은 유지한다. 새 full derivative는 sidecar이며 과거 ticket/manifest를 갱신하지 않는다. artifact 결속 조회는 job 행 잠금을 취하지 않는 plain SELECT이고, 처리와 저장은 preview 행 최종채택 트랜잭션 밖이다. 최종채택 및 파일 I/O 후에도 취소/현재 원결속을 재대조한다. 취소/실패/held/늦은 결과는 정상 full preview 다운로드에 노출하지 않는다. 인증된 공용 읽기와 요청자/원custodian/admin의 preview취소 경계, 기존 CSRF·로그인 보호를 재사용한다.
- 별도 PG/TLS MinIO·설치 CLI의 **331,778,658byte 실제 raw RGB24 MOV(640x360/12fps/40초)** 1개를 만들었다. 원본 SHA `1fdb54394ec44961207e7b84af7e694bfeed778564bac1ad9b35f3b700a4fd75`; 요청 HTTP202 약0.027초/queued·중복 같은id → 독립 생성 → 길이40.000초·출력1,597,969bytes SHA `ea3c6e6f3f9948bd77470e6fa0a2a8c3c3f445337d4fe68f5247eac0f23051f5`. 실제 브라우저 fetch/SHA와 파일 SHA가 같고 Edge(Chromium, CPU rendering)에서 seek 없이4배속 ended40초/600frames/dropped0를 확인했다. native decoder도600frames/전체 decode exit0다. native download manager 성공을 주장하지 않는다.
- 같은 단일 합성 파일의 별도 취소용 asset alias(CAS bytes 중복 없음)를 사용했다. 명시 PG row-lock barrier로 queued를 유지한 실제 CLI가 ready를 보고한 후 SIGTERM exit0 → API/runner 재기동 후 같은 pending id 유지 → 실제 encoding stage에서 취소 POST1 → cancelled/claim1·full file404다. 대표 성공도 claim1이며 기존 운영 작업은 사용하지 않았다. 최초 pending-stop 시험은 CLI readiness 전 신호로 원 요청이 정상 생성되어 **미수용 하네스 시도**로 보존했다. 재시도는 원 상태 reset이 아니라 별도 취소 subject 경계다.
- 첫 S3 fixture의 `put(max_bytes=...)` 미지원 실패는 보존하고 새 disposable DB에서 고쳤다. 일반 S3 put 상한을 올리지 않고 preview만 명시512MiB CAS+conditional object write로 저장한다. browser-harness 초기화/자동재생/미디어정지 실패는 제품 실패와 분리, 설치 Edge로 실제 확인했다. 모바일 긴 SHA 가로넘침은 wrap으로 보정했다. StorageVideoInfo와 정상 산출물 화면에 full 상태/생성/취소/받기를 별도 연결했으며 PC1440/390px 실제 제품 DOM·끝재생·가로넘침0을 확인했다. API 연결은 정상 인증 TestClient를 내부에 둔 격리 ASGI transport이며 운영 로그인 UI 재검증이 아니다.
- 최종 PG/설치 경계 XML **13 pass**, web Node **60 pass**, 타입/build·변경 ESLint/format 통과. 신규 Python Ruff0/부모 F4011, 전체 web lint 신규0/부모80 및 format 부모2파일(`busy-retry.ts`, `busy-retry.test.mjs`)는 그대로라 전체 lint/format 통과라고 쓰지 않는다. 기존 Starlette/httpx·Radix build 경고를 보존했다. source/설치 bytes 및 actual records는 `mediagent-renewal-ops/full-preview-a9a04b59` 증적이다.
- 운영16역할 ID/image/StartedAt/Config/목적지별 mount와 WIP21SHA는 동일, read-only 관측 원본22/작업8·미발행accepted24·운영020미적용이다. 원본17 일괄재생성/재전송·기존작업 재실행·#5/DLQ/accepted20 변경·유료/provider/GPU·공개ingress·추가실행slot·타host·initializer 강제정리는 없다. 비용/권한 확대나 운영 배포·worker 활성화는 승인하지 않았다. **소스 검토/App push 후 운영승격을 별도로 진행**해야 하며, 4GiB/시간단위 성능·HA·처리중 강제장애 실환경 수용으로 확대하지 않는다.

## 대용량 CPU 운영 반영 완료 — 소스 수용과 구분

- PM1563000997155049564가 소스1da32470ef157f5b067ff5b99a8bb27fa3f53338까지 수용/App push·Git/GitHub API 일치를 확인했다. Windows 실제HEAD/ls-remote도1da 일치 확인 후 동일 사설 목적지에 반영했다. 개발/격리 증적의 재수용이나 docs-only 왕복을 선행조건으로 두지 않았다.
- 운영 API/CPU결과/engine결과/후속dispatcher와 encode·validate·controlhost는 **1da32470 설치본**이다. 웹c826 및 다른8개 물리reader252d는 기존 계약/한도로 유지했다. 변경코드 실제reader의 imported모듈/CPUdecoder bytes를 커밋과 대조했다. 일반 업로드/타역할 상한·등록모델/provider 비활성·최소권한·normal/auth/CSRF/TLS/단일capacity1을 유지했다.
- 기존사이트 Stop0 `83e1929e59bc4b0c8861c608381f4f10`→encode/validate/oldhost 정상exit0→새created target→감사preview/decision `0facfd0b03ac4b31834b143eec28b9cd`/apply→별도exact binding→사이트명시Start. 동일slot epoch2/cap1/replicas1/관리중 요청없음이다. oldAPI SIGTERM exit143, 결과수신/후속앱 exit0로 기록하며 모두0으로 꾸미지 않는다. oldPID/컨테이너/image/ACK/rollback을 보존했다.
- 수신기3개의 /data/content512MiB tmpfs가 새diskbind를 가려 #8 첫채택이 OSError로 중단됐다. 권한·코드검증·상한을 넓히지 않고 그 destination tmpfs만 제거, 실제 컨테이너UID→호스트 파일 readback/free검증으로 수정했다. 원S3완료영수증·원MQ결과를 정상수신 재개로 채택했으며 작업/명령/이벤트 재발행이나 재실행은 하지 않았다.
- 준비된 실제 **311,040,938byte MOV**를 승인된 synthetic 원본으로 1개 등록해 원본22개가 됐다(기존21 SQL COPY 전체값은 최신backup과 동일). 같은 HTTPS **실제화면에서 원본선택→새티켓 #8 `b89c93081dce4fb29745d7952929ffd2`→계획동의→실행→인코딩/검증 완료**, 각attempt1/revision2다. 티켓·동의를 seed/직접POST로 대신하지 않았다. 영상2,465,062bytes SHA554748687ba46145aac5167d7a431eb80ad31c3d27dce160cc6e0a5ebe4f8329/검증119bytes SHA1ee60f811d8fda44ca80f63029e46539b215d7dbf8debeb63fb6fb27573143b7 및 manifest를 실제UI링크 응답으로 다운로드·파일SHA 대조했다. nativeCDP download-context 실패는 별도이며 브라우저 응답을 boundedchunk로 저장한 증거다.
- 작업8개/원본22개/정상산출물2개. 원job1–7/run/archiverecord117/oldoutbox45 전체필드 동등, #5 rawrunning/needs-review·DLQ 보존. 원accepted20+기존#7의2개+새#8의2개로 미발행accepted총24이며 옛20을 지워0으로 맞추지 않았다. WIP21SHA 불변/원본17 재전송·재해시/모델·GPU/provider유료호출/initializer강제정리/타host·추가slot 없음.
- 캐시10GiB/입력4GiB·6시간/encode2시간/출력256MiB 등 수용된 지원제한은 그대로다. 운영대표311MB를 통과한 것이 전체4GiB/6시간 성능 보증이나 전체길이영속WebM 지원은 아니다. **전체길이 비동기WebM은 다음 별도묶음**. 현재 운영핸들은 `C:/Users/skygg/dev/mediagent-renewal-ops/deploy-large-cpu-1da32470`/canonical-running-deployment.json이며 새v2티켓이 있으므로 옛maintenance/구target자동복귀 금지다.

### 공통 engine 임대 회귀 보정 — b676 위 corrective 변경

PM1562998217422147606의 b676 검토에서 기존 engine wire2(3필드 agent)를 CPU 전용 lease helper에 무조건 전달하는 공통 _insert_run 회귀를 확인했다. _insert_run 한 줄만 wire1일 때 CPU lease helper/그 외 검증된 engine은 기존120초로 분리했다. CPU encode·validate agent revision1=120초/revision2=9600초는 유지하고 engine/CPU 입력 계약 자체는 변경하지 않았다. 별도 network-none PG의 실제 공통 node INSERT·request 저장·DB임대120초 회귀1과 CPU임대4=5검사 통과/Starlette경고보존. 실제 모델·GPU/provider·311MB 성공취소·17개·기존UI를 다시 실행하지 않았다. 원b676/증적 유지·운영미변경이며 이 보정만 추가소스검토 대상으로 인계한다.

## 대용량 CPU 입력 — 개발·격리 확인 완료 / 운영 미반영

- PM1562978435666808863에서 직전 운영 복구 기능c82636d5/문서d5fa274f를 수용·App push, Git/GitHub API 일치로 종료했다. 이번 개발 기준HEAD/직접 ls-remote는 `d5fa274f9210e9a2b9aecbd6a91223bf7d8ec26b`다. 기존 UI/17개 전체 전송·해시·대표 미리보기 묶음을 다시 열지 않았다.
- 신규 대용량 티켓만 `cpu_video_v2`를 고정한다. wire는 CPU protocol1/agent revision2이며 encode·validate_video만 허용한다. 원본4GiB/길이6시간/픽셀8,294,400(각변4096 이하), encode wall2시간/명령9000초/임대9600초/명령별캐시10GiB/정상 결과256MiB다. 일반 업로드256MiB·보관참조8GiB·명시보존import4GiB와 다른 역할revision1 입력256MiB는 그대로다. 새 상한은 보장되는 처리속도나 결과크기가 아니다. 결과 예산/길이검사를 통과하지 못한 잘린 영상은 성공 채택하지 않는다.
- API의 원본 선택 가능/처리역할·한도를 기존 선택기와 plan.notice로 연결하고, 실제 정의/원본에서 profile을 재검사한 뒤 불변 snapshot·요청 SHA·노드agent개정·전송임대를 맞춘다. 미지원 전사/번역/타역할·새 상한초과는 원본 fetch/티켓 INSERT 전에 거부한다. 새 입력의 API local runner도 거부하며 독립 브로커 경로를 요구한다.
- CPU는 S3를 chunk 전송/검증하고 private attempt 입력을 chunk 복사·해시한다. v2 cache는 명령별 private scope로 정상/알려진 실패 종료 시 정리하며 중단 후 남은 scope는 자동 삭제/재실행하지 않고 판단 대기한다. encode 출력은 파일·wall budget과 원길이 일치로 제한한다. 확인된 v2 실패 receipt는 실패로 전달하고, 깨진/누락/시간초과 결과는 기존 unknown·자동재실행금지를 유지한다. 물리 CPU에는 DB/암호화 master/provider키나 daemon socket이 없다.
- 업로더 미상 원본의 새 snapshot은 `original_uploaded_by`와 `storage_custodian_id`를 별도 감사한다. applied012가 쓰는 내부 uploaded_by 호환 FK slot은 기존 저장 namespace에 결속하고, 공용 DTO/manifest에는 실제 업로더 미상을 표시한다. 원asset/원owner/원파일을 바꾸거나 FK를 맞추려고 blob을 복제하지 않는다.
- 실제 큰 입력에서 결과 검증 동안 job 행 잠금으로 동시 GET503이 재현됐다. v2 입력 검증을 lock 밖에서 수행하고, lock 안에서는 같은 snapshot SHA·정확한 요청/참조·현재 취소/세대/권한을 재대조한다. 검증 barrier 중 실제 별도 PG 조회·취소 성공/해제 후 ready=false와 consent/run0을 확인했다. 입력 검증이나 취소 보호를 생략하지 않았다.
- 별도 PG·TLS RabbitMQ/MinIO·설치 API/results/각각 독립 CPU encode·validate consumer로 **311,040,938byte 실제 RGB24 MOV(1920x1080/5fps/10초, padding 없음)**를 사용했다. HTTP 원본선택/preview→티켓→계획동의/admit→독립 전달→인코딩/검증→manifest/출력 다운로드 SHA 일치다. 성공 job `22740467e6184522970ce5492da86ceb`, encode2,465,062bytes/검증119bytes. 호출 중 취소는 POST1·후속validate0·정상artifact0·늦은결과1격리(`large-cpu-cancel.json`)다. 이는 새 HTTP 제품 경로 검증이며 UI-only 재실행으로 표시하지 않는다.
- 4GiB+1은 거부용 참조/검증된 DB metadata 경계이며 실제4GiB 파일을 전송했다고 주장하지 않는다. 다른 역할/상한 거부, v1 작은 CPU 회귀, v2 local거부, 정확한 임대, 업로더·custody 분리를 좁게 확인했다. final policy XML11/PG boundary XML6와 별도 actual success1/cancel1은 서로 다른 실행이며 한 배치 all-pass로 합성하지 않는다. scoped Ruff 신규0/부모 기존7은 남기고 Starlette/httpx 경고도 보존한다.
- 현재 운영은 직전 c826/d5 정상 목록·상세·다운로드/단일 슬롯 그대로다. 새 입력을 운영에서 가능하다고 표시하지 않는다. 승격 시 encode/validate 전용 image·disk cache, API/수신송신/메시지검증/임대가 일치해야 하고 실제 고정encode는 current canonical handles의 drain→감사handover→exact binding을 재사용한다. 옛 maintenance Compose/직접 pin 덮어쓰기/추가slot/타host/provider 활성화/initializer 강제정리 없이 진행한다.
- 전체길이 비동기 WebM·다른 역할·유료/provider·멀티머신·HA는 다음 별도 묶음이다. 운영 원본17/#5/DLQ/기존accepted20/키/backup/WIP/rollback은 이번 검증에 사용하지 않았다.

## 현재 운영 — 2026-10-23 정상 조회·단일 CPU 동선 복구

- 사용자 승인1562955180637425845/실행 지시1562955522100166789로 기존 사설 HTTPS의 명시 normal/broker/control을 재개했다. 정상 vault 로그인 후 실제 목록은 **원본21개(기존4+보존17), 작업7개(기존6+새 합성#7)**다. 실제 경로는 `/api/videos`, `/api/jobs`이며 미존재 경로를 위한 전체 GET 예외는 없다.
- 최신 DB backup 실제 별도 복원(schema/data no-owner/no-privileges, 역할 backup 별도)→host267 단일 SIGTERM/exit0·소유권반납→012/019·기존 업무행 불변→HTTPS/CSRF/CAS 관리자 candidate/decision→host apply·별도 exact binding→명시 Start 완료. capacity1/epoch1/새 encode1을 유지한다. 이전 요청/계약/ACK는 보존한다. API에는 socket/DDL/계약완료 쓰기가 없고, API/실행·host의 실제 제한 권한을 확인했다.
- 수용본252d3f52 기준 clean 설치/reader9개 정상종료0·교체 후 API/웹·수신/송신을 맞췄다. 대용량 보존 읽기 수정 **c82636d534579116cbd4465e32901685e53d587a**를 API/웹/수신·송신에 설치했다. 물리 reader/host의252d 입력 계약과256MiB 처리 한도는 변경하지 않았다. 새 소스는 직접 push하지 않았으며 운영 적용과 PM 소스 수용/push를 구분한다.
- 실제 화면에서 합성#7 `8b5b48b650cf469a812c014b468d75cb` 생성→계획 동의→실행→인코딩/검증 완료·산출물2개를 확인했다. UI 실제 파일83,270bytes/SHA `d80510839fe2c9b8d3346756a4fede26eb9484f49c8762aac648f69a2c439bdd`가 결과와 같다. 티켓 seed/기존#5 재실행/provider 호출은 없다.
- 보존17개 **29,073,982,271bytes**는 변경 없는 원파일에서 conditional S3 PUT→실제 remote 전체 GET/SHA 검증 후 공용 등록했다. 원 업로더 미상은 미상이며, 실제 import계정은 저장 custodian으로 별도 감사한다. 기존 원파일/asset.json·기존assets4/jobs6·archive117행은 불변이다. 일반 업로드/실행은256MiB, 저장 참조/읽기는8GiB·명시 보존 importer는4GiB로 분리했다.
- 17개 모두 WebM **앞부분30초**이며 화면에도 범위를 표시한다. 대표340,261,063bytes는 실제 브라우저 파일/SHA 및 ended30.007초/450frames를 확인했다. 최대4,135,723,983bytes는 HTTP200 전체 전송 완료를 서버 로그로 확인했다. 최대 파일의 브라우저 로컬 경로/해시와 별도 재생 관측을 완료로 합성하지 않는다.
- #5 rawrunning/snapshot·기존 미발행accepted-result20개 정확한 행·DLQ·원키/ACK108파일hash·WIP21·원본/backup/rollback을 보존한다. #7의 새 이벤트는 별개다. 실제 provider 주소/모델/비용 승인 전 등록 모델 호출/독립 consumer는 활성화하지 않았다. initializer fdfa37bb17fc… 강제 정리도 미승인으로 실행하지 않았다.
- 남은 범위: >256MiB 작업 입력·전체길이 비동기 WebM, 실제 provider 인증/품질·비용 승인, Loop/Fallback 제어 실행, 다른 역할/다중 슬롯/멀티머신·장애복구·장기 저장정책. 이 개발 동안 정상 조회를 유지한다.
- 실제 배포/증적 정본은 `mediagent-renewal-ops/restore-normal-252d3f52/`의 canonical/current handles, actual API modules, original17-preservation-final, original-records-preserved-final, actual-original-download, small-original-browser-proof, largest-download-server-completion이다. 이전 maintenance Compose는 역사/rollback이며 현재 배포 recipe로 재사용하지 않는다. 고정 대상 재생성에는 새 audited handover가 필요하다.

## 이전 개발·격리 수용 기록

아래의 운영 미반영/미완료·제외는 각 개발 당시 기록이다. 현재 운영·승인 범위는 위 절을 우선하며 실제 provider 미수용과 보류 자원은 계속 분리한다.

### 순수 제품 UI 최종 연결 — PM 수용·App push 완료 / 운영 연결 미완료

- [x] 기존 모델 선택/선택형 폴백 저장·재조회, 원본/워크플로우/언어 선택→실행 전 확인→작업 생성→계획 동의→실행 요청→후보 기록·결과/manifest 받기를 실제 production UI로 조작했다. 초기 자료는 격리 원본/등록 모델/편집 가능한 예제 정의뿐이며 최종 티켓 seed나 시험 코드의 생성·승인·실행 POST는 없다. 로그인/CSRF/권한/비용 동의·불변 티켓과 정식 API/전용 MQ/독립 모델 consumer를 유지했다.
- [x] 별도 PG·TLS RabbitMQ/MinIO/CPU consumer와 통제 HTTP에서 PC1440/390px 성공·호출 중 취소의 대표 4경우를 관측했다. 화면 저장값/재조회→고정 티켓→DB 실행 요청→실제 HTTP의 모델·연결·키/언어·순서/request SHA를 대조했고 성공 출력은 UI 다운로드 SHA·manifest와 같았다. 취소는 후속 후보/번역0·늦은 결과 격리1/정상 모델 manifest0이다. 실제 공급자 인증·품질 검사가 아니다.
- [x] 비동기 단계 진행 뒤 화면의 오래된 개정으로 취소가 거부되는 실제 결함을 RED→GREEN 보정했다. 취소 클릭 시 정상 GET으로 최신 권한/상태/개정을 읽고 취소 POST는 1회만 전송한다. 기존 CAS를 우회하거나 409/불명확 요청을 자동 재시도하지 않는다. PC 성공은 변경 전 기존 기능 통과, 변경 뒤 PC 취소·모바일 성공/취소만 좁게 확인했으며 한 배치 4개 전부 통과로 표현하지 않는다.
- 타입/production build·변경 frontend lint/format·격리 fixture scoped Ruff 통과. 준비 시 문서 응답 필드/관측 SQL/모바일 숨김 저장 상태를 잘못 가정한 하네스 실패는 제품 결함과 분리해 보존했다. 정상 검증 프로세스/API 자식 -15·consumer/PG/MQ/S3 0을 확인하고 제거했다. 초기 준비 실패 컨테이너 1개는 API/모델 시작 전 실패, SIGTERM 1회 뒤에도 남아 강제 종료/재신호 없이 전용망과 보류했다. 기존24개/WIP21 보존. 제품 UI 소스 `62d4fdf2301996638a2d3cf923bed3f6cdbf7c66`는 PM1562941603591618693에서 수용·App push 및 Git/GitHub API 원격 SHA 일치 확인으로 종료했다. PM의 소스·증적·화면 대조와 Windows의 실행 관측은 구분하며 추가 제품 시험은 하지 않는다. 운영 연결은 미완료다. 초기 initializer와 전용망의 정리 1건만 별도 승인 대기로 유지하고, 제품 수용을 다시 열거나 전체 정리 완료로 기록하지 않는다.

### 등록 모델 전사·번역의 실제 설치 진입점 — PM 수용·App push 완료, 운영 미반영

- [x] 정식 `app.server`에 기본 꺼짐인 `--enable-registered-models`를 연결했다. normal admission/명시 broker/S3/private 정책·기존 암호화 키 resolver가 함께 있어야 하며, API는 모델을 동기 실행하지 않고 전용 등록 모델 큐로 전달한다. `app.operator consume-registered-models`는 독립된 신뢰 애플리케이션 프로세스로 같은 Execution의 실행·intent/receipt·채택을 재사용한다. CPU/GPU 물리 에이전트에 DB/모델 키를 전달하지 않는다.
- [x] 기존 local delivery 조건을 지우지 않고, 같은 credential/database와 명시 S3·등록 broker factory/runtime·정책 SHA의 결속을 검사하는 별도 전달 경계를 추가했다. MQ에는 owner/job/attempt/request SHA만 보내며 수신기는 commit된 outbox와 원 요청을 확인한다. 모델/연결/키 개정·언어/후보 순서를 실제 요청까지 유지하고, 정상 정책은 승인 origin/공인 IP에만 HTTPS Host/SNI/인증서 검증으로 연결한다. 프록시·리다이렉트·다른 IP 자동 재시도는 없다. loopback HTTP는 격리 정책+명시 시험 flag+disposable 환경 모두가 있을 때만 허용한다.
- [x] 별도 PG·실제 TLS RabbitMQ/MinIO·서로 다른 API/results/model 캐시·새 격리 CPU consumer와 통제 HTTP로 정식 설치 명령→CPU 결과 수신→등록 모델 전달→전사/번역→채택/티켓 manifest·파일 다운로드를 확인했다. 발급 후 head/endpoint/key를 바꿔도 이전 개정의 실제 주소·모델·키/언어·후보 순서를 사용한다. 정상 모델 출력2개의 실제 S3/ticket 바이트·API 다운로드 SHA가 같고, 새 프로세스의 같은 완료 참조 수신은 HTTP를 반복하지 않는다.
- [x] 호출 중 취소 뒤 503이 반환돼도 후속 후보/번역 요청은0이며 늦은 receipt1은 quarantine/정상 모델 manifest0으로 남는다. 틀린 SHA/존재하지 않는 attempt 참조2개는 격리 전용 dead queue로 거부하고 기존 완료 manifest/receipt/HTTP 횟수를 바꾸지 않는다. 기존 adapter/영상/MQ 전체 회귀는 반복하지 않았다.
- 설치된 site-packages 실제 코드9모듈 SHA를 대조했다. installed 단위9·실제 설치 경계4 통과이며 frontend 변경/화면 시험은 없다. scoped Ruff는 Git mode0644/full-tree 조건에서 신규0·부모에도 있는 I0012다. 기존 Starlette/httpx 경고는 남긴다. API 자식의 실제 SIGTERM -15와 application/CPU consumer0, PG/MQ/S3 0을 구분해 기록하고 임시 container/network를 제거했다. 기존24개 container 설정/실행 상태·WIP21 hash를 보존했다.
- 설치 소스 `14dcdfca3002d86eab92ce21cb8349f227532a21`는 PM1562928568521068615에서 **수용·App push/원격 SHA 일치 확인으로 종료**했다. 운영 배포는 아니다. 의존성 보존 후보 이미지의 정식 CLI/격리 요청·실행 연결 검증이며 실제 공급자 인증·인식/번역 품질·공인 egress 승인이나 여러 컴퓨터 설치 수용이 아니다. 운영 배포·서비스/DB/키·012/019·원본17개·#5/DLQ·정상 접수 재개는 수행하지 않았다. 기존 native lifecycle/고정 호스트와 다른 실행 역할도 그대로다.

### 공통 캔버스 자동 정렬·연결선 정리·전체 보기 — 구현·격리 확인 완료, 운영 미반영

- [x] 기존 WorkflowCanvas와 편집/renewal 실행 상세 연결을 재사용한다. 세 배치 조작을 텍스트 버튼으로 노출하며 확대/축소·화면 맞춤만으로 정렬/연결선 정리를 대신하지 않는다. 긴 이름/포트는 줄바꿈하고 실제 DOM 높이·포트 중심을 측정한다. 위상 계층과 출력 포트 순서로 노드를 배치하고, 노드를 피하는 직각 연결선/분리된 합류 접근 경로를 계산한다. 기존 노드 폭과 포트/연결 관계는 유지한다.
- [x] 편집은 위치만 바꾸고 최대20회 정렬 되돌리기·기존 개정 충돌 검사(CAS) 저장·재조회로 연결한다. 옵션/model_ref/fallback_refs·입력/연결을 보존한다. 읽기 전용 상세는 local view 배치/초기화만 제공하며 고정 ticket/snapshot 수정 요청을 보내지 않는다. 연결선 경로는 저장 위치와 포트에서 다시 계산하는 화면 기하이며 별도 실행 계약을 저장하지 않는다.
- [x] 별도 PG·실제 인증/정의 저장 API·production UI와 합성 분기 그래프로 PC1440/390px을 확인했다. 긴 catalog 이름/thumbnail만 명시 응답 fixture이고 실행 상세는 직접 seed한 불변 합성 draft다. 실제 영상·모델·MQ·저장소 여정이나 공급자 호출을 실행하지 않았다. 되돌리기/실제 저장·재조회, 설정·모델 고정값 불변, DOM 글자 범위/노드 겹침/연결선의 타 노드 관통·다른 선 교차/중첩 없음(같은 출력의 분기 접점 제외), 실제 포트 중심과 경로 끝점, 전체 보기의 노드·선 경계, 읽기 전용 수정 요청0/snapshot SHA·revision 동일과 모바일 확대·이동을 확인했다.
- 최종 Node 기하5개·실제 브라우저2개·타입/build·변경 frontend ESLint/format 통과다. 100노드 정렬은 기존 서버 위치 상한을 보존한다. 과도한 크기/연결 복잡도는 실패 안내를 남기며 연결을 삭제/변경해 성공시키지 않는다. 모바일 전체 보기는 개요이며 확대·이동으로 긴 이름을 읽는다. 기존 Radix bundle/Node Playwright 경고는 남는다. 임시 API는 SIGTERM 후143, PG는0으로 종료·제거했고 기존24개 container ID/설정/mount/실행 상태·WIP21 hash와 운영 차단을 보존했다. 캔버스3827615999db3609e4015b5d6aca495a8cc199a6은 PM 수용·App push 및 Windows 원격 SHA 일치를 확인해 종료했으며 운영 배포·서비스/DB/키·012/019·원본17개/#5/DLQ·정상 접수 재개는 제외했다.

### 티켓별 산출물 manifest·저장 배치 — 구현·격리 검증 완료, 운영 미반영

- [x] 새 Execution.create snapshot에 artifact_layout1을 고정하고, 공통 CPU/등록 모델 결과 채택에서 티켓·노드·node_run_id·시도 번호/세대·출력 포트·CAS 참조·실제 티켓 저장 참조를 함께 영속한다. 출력이 후속 포트로 연결되면 intermediate, 아니면 final로 구분한다. 제어/검수 완료·검증된 복구 재사용도 새 티켓 저장 결속을 적용한다.
- [x] 실행 계정 namespace 아래 `tickets/<job>/nodes/<node-id-sha256>/attempts/<node-run-id>/outputs/<port>/<content-sha>`에 실제 출력 바이트를 배치하고, 채택 시마다 `tickets/<job>/manifests/<manifest-sha>.json`을 불변 저장한다. 로컬은 기존 CAS와 동일 inode의 hardlink라 내용 복제가 없고, 원 CAS/원본 경로·SHA를 보존한다. S3 adapter는 명명된 티켓 object에 실제 바이트를 별도 저장하므로 로컬의 무복제 보장과 구분한다.
- [x] 최신 채택 manifest는 기존 node_run receipt의 SQL commit에 결속한다. 조회만으로 파일을 쓰지 않으며, 예전 snapshot은 기존 owner-CAS 호환 읽기와 비영속 manifest projection만 제공한다. 기존 원본/티켓을 이동·갱신하거나 원본17개를 이관하지 않았다.
- [x] 실제 상세 조회·manifest 다운로드·기존 산출물 다운로드를 연결했다. 새 작업 다운로드는 ticket storage/hash를 검증해 해당 바이트를 읽고, 정상 채택 목록은 completed 결과만 포함한다. 취소/늦은 quarantine과 저장 실패 뒤 미채택 파일은 정상 manifest/download에 노출하지 않는다. 화면에서 manifest와 비영상 산출물 받기가 가능하다.
- 별도 PG/local CAS·짧은 합성 원본·CPU 음성 추출/전처리 및 등록 adapter MockTransport 결과로 두 티켓 분리, 재조회·다운로드 바이트/SHA·실제 artifact 행의 저장 키, 업로더/실행자 분리·인증된 공용 읽기/개인 설정403·익명401을 확인했다. legacy CAS 읽기 무변경·취소 격리·manifest 저장 실패 경계와 통과형 영상의 기존 WebM 미리보기 호환도 확인했다. Python12 pass(신규11+기존 저장 guard1), 실제 production UI PC1440/390px2 pass·타입/build·변경 frontend lint/format 통과다. scoped Ruff 신규0·기존 API F4011은 남는다.
- S3 경로는 network-none byte protocol double의 원격 키/새 캐시 재조회 검사이며 실제 MinIO/S3 설치 수용이 아니다. 실제 공급자·운영 DB/키·서비스·012/019·#5/DLQ·정상 접수/배포와 기존 영상/MQ 전체 여정은 제외했다. 산출물 저장3aaec048e7bd64215797cc702711b82acfb63b07은 PM 수용·App push와 Windows 원격 SHA 확인을 마쳐 이 묶음은 종료했다. 운영 배포는 아니다.

### 접속 화면 상태 구분 — 구현·격리 확인 완료, 운영 미반영

- [x] `/capabilities`의 정확한 HTTP503 + `maintenance_admission_closed`를 **유지보수 중 · 작업 이용 제한**으로 안내한다. 일반 통신/서버 응답 실패와401 로그인 필요를 구분하고, 확인하지 않은 DB 상태를 정상/끊김으로 단정하지 않는다. capabilities가 작업 기능을 광고하지 않는 정상 응답도 PostgreSQL 미연결로 추측하지 않는다.
- [x] production frontend와 명시적인 응답 fixture에서 PC1440/390px의 유지보수·일반503·네트워크 실패·HTML503·다른 상태 코드·기존 세션 만료/로그인·token 미보유401·기능 미제공 안내를 확인했다. 관련 브라우저16개/기존 인증 세션 단위3개·타입/build·변경 frontend lint/format 통과다. UI 응답 계약 검증이지 실제 DB/운영 가용성 검증이 아니다.
- 제품 수정은 VideoWorkspace.tsx뿐이다. 인증/CSRF·관리자 허용 경로·API 정책을 바꾸거나 진단 endpoint를 추가하지 않았다. 전사/영상/MQ 전체 시험, 운영 배포·접수 재개·서비스/DB/키 변경은 없고 기존 WIP와 컨테이너를 보존했다. 화면 보정839f65eaa32b6a322412db6b7b73300746c4c4e7은 PM 수용·App push 및 Windows 원격 SHA 확인을 마쳤으며 이 묶음은 종료했다. 운영 사이트는 바뀌지 않았다.

### 등록 모델 API 음성 전사 — 구현·격리 요청/실행 검증 완료, 운영 미반영

- **소스 수용·push 완료:** `75793b1ae81b165f4492cdc9767f41b852747e8d`를 PM이 수용·App push했고 Windows에서도 원격 renewal SHA 일치를 확인했다. 제출 증적과 PM의 별도 MockTransport 확인을 구분하며 전사 묶음은 닫는다. 운영 배포·실제 공급자 인증/인식 정확도 수용은 아니다.
- [x] 전사 모델/원문 언어/선택형 순서 폴백을 저장·재조회하고 기존 티켓 snapshot/실행 command에 모델·연결 개정을 고정한다. 전사 가능성은 audio→text/speech_recognition 선언과 구현된 규격으로 따로 판정한다. 텍스트 번역 지원만으로 전사를 허용하지 않으며 로컬 Whisper 대체는 없다.
- [x] Gemini 네이티브 inline audio와 구조화된 초 단위 구간 응답, OpenAI/호환 음성 endpoint의 whisper-1 multipart/verbose_json/segment timestamps를 연결한다. gpt-4o-transcribe의 일반 JSON/텍스트 규격, Anthropic/TTS는 이번 시간 구간 계약의 실행 대상으로 표시하지 않는다. 실제 공급자 가용성/인증/인식 정확도는 미확인이다.
- [x] 검증된 원본→기존 CPU 음성 추출/전처리 off→PCM WAV→API→시간 구간 전사→기존 번역 입력→결과 다운로드를 별도 PG/CAS·통제 HTTP로 확인했다. PCM16/mono/16kHz·60초/2MiB·100구간/16KB 이내만 지원하며 시간 정보가 없거나 음성 범위를 벗어난 응답은 거부한다. 기존 audio_clock으로 보존된 원본 시각에 대응하며 클라이언트가 시각을 만들어 넣지 않는다.
- [x] 오프라인 Windows System.Speech 합성 음성을 사용해 Gemini 단독 채택, Gemini 실패→OpenAI 채택, 전체 실패, 시간 없는 응답 거부, 전사 중 취소/뒤 후보와 번역 미호출을 확인했다. 티켓 발급 뒤 모델 head/키 교체에도 원 개정을 사용하고 실제 HTTP의 WAV SHA가 CAS 입력과 같다. 기존 후보 intent/취소·세대·늦은 결과 격리를 재사용했다.
- 관련 Python16 pass/실패·오류·skip0(ASR9+공통 runner/Gemini 회귀7), 실제 production UI2 pass·Node53·타입/build·변경 TS/TSX lint/format 통과다. scoped Python lint 신규0/기존 F4011이며 기존 다른 lint 부채를 고치거나 전체 lint 통과로 보고하지 않았다. 새 화면 PC/390px를 확인하고 기존 영상/MQ 전체 여정은 반복하지 않았다.
- 초기 전사 수용은 동일 credential store/명시 transport·origin/local delivery 주입 범위였다. 위 후속 설치 묶음에서 기본 꺼짐인 정식 CLI/등록 모델 broker 연결을 별도로 확인했다. 운영 연결·승인된 실제 공급자 호출/정확도·배포·장시간 분할/다이어리제이션은 미완료이며 유지보수/중지 서비스·DB/키·012/019·대상/원본/#5/DLQ와 유료 제한은 그대로다.

### 등록 모델 번역·선택형 다단계 폴백 — 구현·격리 HTTP 계약 검증 완료, 운영 미반영

- Gemini 응답 보정: promptFeedback.blockReason의 명시 차단은 후보 조회 전 request_rejected/후속 후보0으로 중단한다. STOP 최종 텍스트의 thoughtSignature·문서화된 메타데이터는 허용하지만 thought=true·서명·도구/미디어 데이터는 번역문에서 제외한다. 최종 텍스트 없음/잘못된 자막 형식은 거부한다. 해당 network-none MockTransport 응답 fixture5개 RED→GREEN만 확인했고 기존 티켓/순서/취소·화면/영상/MQ 증적은 재실행 없이 이어 인정한다. 번역 ac55d7bf와 보정4949d8f5는 PM 수용·App push 완료이며 운영 미반영이다.

- [x] 워크플로우의 번역 모델/불변 개정과 선택형 폴백(없음·추가·삭제·순서 변경, 최대 3개)을 저장·재조회하고, 작업 화면의 원문/대상 언어와 함께 기존 티켓 snapshot·실행 command에 고정한다. 기존 암호화 CredentialStore/model resolver와 CAS/동의/claim/결과 채택을 재사용하며 로컬 모델로 대체하지 않는다.
- [x] Gemini 네이티브 generateContent와 기존 OpenAI/OpenAI-compatible를 연결한다. 후보별 사용 가능 여부와 origin/키/능력을 재확인하고, 한 후보당 한 번·최대 4개만 시도한다. 사용 불가·429·5xx·유효하지 않은 결과만 다음 후보로 전환하고 인증/요청 거부·전송 결과 불명·취소는 중단한다. 실제 HTTP 전 후보 intent를 영속 저장하며 시도/실패/전환/최종 채택을 구분해 화면에 표시한다.
- [x] 별도 PG/CAS와 loopback HTTP 서버에서 화면→설정 저장/재조회→티켓→동의/실행→결과 다운로드, 폴백 없음·복수 실패 후 성공·전체 실패·호출 중 취소/다음 모델 미호출을 확인했다. 발급 후 모델 head/키를 바꿔도 기존 모델/연결 개정으로 호출했다. PC/390px 화면, 관련 Python 33 pass/기존 browser opt-in 1 skip, 실제 브라우저 2 pass·Node53·타입/build/format을 확인했다. 변경 범위 lint는 신규0이며 부모에도 있는 Python F401 1개/프론트 effect-order 1개가 남는다.
- 이 완료는 합성 자막/통제된 HTTP의 요청·실행 계약 검증이다. 기존 video DAG의 번역 입력과 별도로, `transcript` 외부 입력만 있는 정의는 선택한 원본을 출처로 유지하면서 수동 자막 JSON(100개/16KB 이내)을 기존 CAS에 고정할 수 있다. 실제 공급자 인증·번역 품질·Anthropic 실행·대용량 분할 번역은 완료로 표시하지 않는다. 음성 전사는 위 별도 수용 묶음이다.
- 초기 번역 수용은 transport/origin을 주입한 로컬 전달 범위였다. 위 후속 설치 묶음에서 명시 bootstrap/등록 모델 broker 전달을 격리 확인했지만 운영에는 미적용이다. external 모드의 후보 전체 비용 동의·티켓/실행 승인은 유지하며 실제 외부 egress/공급자 수용은 하지 않았다. 운영 유지보수·중지 서비스·DB/키·012/019·대상/원본/#5/DLQ는 변경하지 않았다.

### 주요 공급자 연결 등록·Gemini 키 — 구현·격리 검증 완료, 운영 미반영

- [x] 기존 OpenAI/Gemini/Anthropic 선택 시 공식 기본 주소와 해당 연결 방식을 함께 채우고, 사용자 지정 서버는 주소를 직접 입력한다. Gemini 선택 뒤에도 주소가 비고 OpenAI-compatible 방식이 남아 HTML 필수 입력에서 저장이 막히던 실제 원인을 RED→GREEN으로 수정했다. 기존 연결을 열 때는 저장된 주소/방식/개정을 기본값으로 덮어쓰지 않으며 다른 공급자로 바꿀 때 새로 입력한 키를 자동 이동하지 않는다.
- 기존 등록/암호화 API를 재작성하지 않았다. 실제 설치 API·별도 PG의 화면 입력→저장→재조회→이름 수정/키 교체와 PC/390px 화면을 확인했다. 기존 키 참조·과거 불변 개정은 보존되고 응답/화면에는 키 원문 대신 보유 상태만 나온다. 관련 UI5개·실제 API/PG 브라우저1개·기존 credential API2개와 타입/build·변경 경로 lint·Node53개를 확인했다. 저장 성공은 공급자 인증·모델 호출 성공이 아니며 연결 확인은 미확인이다.
- 운영은 아래 유지보수/안전 정지 상태 그대로다. 운영 DB/키·012/019·대상·원본·#5/DLQ를 바꾸지 않았고 외부 모델 호출은 없다. 이 등록 기능의 운영 배포와 실제 등록 모델 전사/번역·유한 폴백은 별도 범위다.

### 018 유지보수 API 선행 설치 — 운영 수용

- [x] `28c14fd3`의 유지보수 API 한 서비스만 운영 설치하고 PM이 수용했다. API 전용 정책과 기존 DSN의 두 RO 파일 mount로 공유 `api.json`을 보존했다. `handover=false`·UID10001·기존 HTTPS/origin/Secure cookie·네트워크/별칭/healthcheck를 유지하며 저장소/브로커 initializer와 일반 업무 route를 열지 않는다.
- [x] 기존 normal API에 SIGTERM 한 번·자동 강제 종료 없는 대기를 적용했다. 실제 exit143·listener/Python/init 종료·OOM/재시작 없음과 업무22개 테이블의 종료 전/후/인증 확인 후 동일 해시를 묶어 확인한 뒤 새 API를 기동했다. 같은 HTTPS의 vault 정상 로그인·세션/지정 관리자 조회200과 업무503을 확인했고 web reload는 하지 않았다. 기존 업무 UI의 조회 오류는 유지보수 차단이며 새 안내 화면 수용은 아니다.

### 같은 등록 슬롯 Stop0·송신3개 정지 — 운영 수용

- [x] 현재 물리 실행기는 같은 boot의 ready/작업 없음이고 충돌 제어·새 미발행 명령·managed 미완료 전송이 없음을 대조한 뒤 정상 HTTPS/vault·CSRF·개정7로 Stop0 한 번을 요청했다. 요청 `dcccf6fb8bd04f7684178f46163e8bd1`은 개정8/succeeded, action `dc4cb60c7bd447d1abd2cb25b5f89693`은 confirmed/issue_count1이다. host267의 실제 ACK reader로 서명·원 요청·원 boot·정확한 target/image를 검증했고 기존 대상은 정상 종료0이다. 논리 슬롯1·desired0·disabled·pending 없음이며 pin/image/계약을 바꾸지 않았다.
- [x] 그 뒤 `dispatch-encode`·`results`·`engine-results`만 각각 정확한 ID에 TERM 한 번/timeout=-1로 정지했다. 세 프로세스 모두 exit0/PID0·OOM/재시작 없음이다. 처리·후속 발행·ACK 순서의 실제 설치 코드를 대조하고 결과 채널의 미ACK/미confirm/미commit이 없음을 확인했다. 종료 후 두 결과 consumer/연결은 없고 업무·outbox/inbox 해시는 그대로라 새 미확정 전송을 만들지 않았다. 별도 busy 영상 시험은 반복하지 않았다.
- [x] 원 #5의 raw running/needs_review·발행/수신 이력, accepted-result 미발행20건·encode DLQ ready1과 과거 ACK/제어 기록을 보존했다. 변경은 새 Stop0 제어 기록뿐이며 API·웹·host267·다른 실행 역할·DB/MQ/S3는 계속 유지한다. 이는 전체 작업 완료·모든 실행 역할 정지·복구 완료가 아니다.
- [ ] host267의 정상 종료/원 소유권 반납, 운영012/019·역할 GRANT·새 host/실행 이미지·대상 전환·원본17 이관·#5/DLQ 복구·정상 접수 재개는 이번 승인에 포함되지 않는다. 각각의 다음 명시 범위와 승인을 기다린다.

### 선행 운영 이력 — c106 단일 인코딩 단계

- API·CPU 결과 수신·인코딩 전송 대기·엔진 결과 수신과 웹은 `c106bf097d6ea0f84af47590e3d6dd837db944f9` 수용본으로 반영했다. 실제 설치 모듈·HTTPS JS/CSS와 정상 인증 조회를 확인했다. 호스트 `26710eb0`와 기존 인코딩 실행기 이미지·ID·`restart=no`는 유지하며 API에 Docker socket을 주지 않는다.
- 운영 DB의 custom 백업을 별도 내부 PG에 복원한 뒤 migration018만 적용했다. 복원된 기존 46개 테이블의 원래 열 값이 동일했고, 원 작업을 바꾸지 않는 확인 기록 조회가 가능했다. 처리·전송 중 작업이 없음을 재확인하고 운영에도 018만 적용했다. 공용 자료함 WIP의 migration012는 포함하지 않았다. 백업·이전 이미지·설정과 롤백 경로는 비공개 운영 자료로 보존한다.
- 실제 관리자 인증으로 작업 처리 확인 API·목록과 제품 PC/390px 화면을 조회했다. #5는 별도 확인 기록의 **처리 여부 확인 필요**로 표시하며 원 작업의 `running`·실행·요청·전송·수신 사실은 그대로다. 준비 계획·관리자 판단·새 복구 작업·예약 해제는 모두 0건이다. 실제 #5의 복구 판단·재발행·초기화는 수행하지 않았다.
- 당시 에이전트 화면은 정상 실행 1개·현재 작업 없음이며 #5 확인 목록으로 연결됐다. 변경한 5개 프로그램 외 기존 15개 컨테이너와 기존 자료·설정/키·공용 자료함 WIP를 보존했다. 현재의 유지보수·안전 정지 상태는 위 별도 체크포인트를 따른다. 동일 영상 여정·운영 장애 주입은 반복하지 않았다. 설치 revision/모듈 SHA와 원 자료 대조·화면 증적은 저장소 밖 운영 인계에 보존한다.

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
- 공용 읽기 기능의 운영 반영은 아직 별도 범위다. 현재는 위018 유지보수 API와 안전 정지 체크포인트이며 일반 공용 입력/실행 route를 열지 않았다. 운영012·구버전 원본17개 이관·#5 복구·추가 슬롯·배치 이전·유료 호출은 수행하지 않았다. 새 origin 입력을 읽는 실행단 설치본과 고정 host pin의 호환 검토 없이 normal API만 앞서 공개하지 않는다.

### 최소 유지보수 입장 정책 — 구현·격리 검증 및018 API 선행 설치 수용

- [x] `app.server`의 필수 `--admission-mode normal|maintenance`와 bootstrap의 명시 `admission_policy`가 일치해야 기동한다. 누락/불일치, 유지보수의 비보안 origin/cookie·broker·고정 mailbox/등록 슬롯 부재와019를 요구한 기동의 schema 미준비는 listener를 열지 않는다. 파일/기동 인자 재확인 없이 오류 해소나 재시작으로 normal이 되지 않는다.
- [x] 유지보수 API는 저장소/credential/broker initializer와 media/execution route를 열지 않는다. request body 수신·업무 DB/파일/외부 호출 전에 미분류 경로도 기본 거부한다. 기존 일반/관리자 세션·직접 HTTP·binary PUT·새 GET handler도 차단했다. 정상 auth/session/logout, 지정 슬롯 관리자 조회·Stop0, 명시019 단계의 관리자 교체 preview/decision만 허용한다. `/admin`/GET 전체 허용은 없다.
- [x] 018만 있는 별도 DB에서 현재267 host와 새 설치 API를 실제 TLS peer로 연결해 정상 로그인·기존 등록 슬롯 Stop0→실제 fixture 종료0·signed ACK를 확인했다. 이때012/019는 없고 새 media/public-origin API도 열리지 않았다. 별도019 적용과 명시 phase/restart 뒤 같은 HTTPS 세션으로 preview/decision→host CLI apply→조회가 연결됐고 desired0/새 target created를 유지했다. PG 보고 fixture이며 운영 MQ 영상 시험이 아니다.
- [x] 새 경계만 설치 패키지에서 검사했다. 서버 재시작 후 기존 세션과 차단 유지, schema019 요구 실패 exit2/미개방, HTTP 보안·사유·개정·권한, Start/증설/다른 슬롯·변경된 슬롯 차단과 기존 role 권한 재사용을 포함한다. 수용47/MQ 영상/A-B는 반복하지 않았다.
- [x] PM 소스·격리 증적 수용과 원격28c14fd3 반영 뒤 별도 승인으로018 유지보수 API 한 서비스의 운영 선행 설치를 수용했다. 결과 수신/DAG 후속 발행은 이 정책이 멈춘 것이 아니며, 위 Stop0·송신3개 정지는 그 다음 독립 승인과 실제 확인이다. 운영012/019·GRANT·host/실행 이미지·pin·원본17·#5 복구는 변경하지 않았다.

### 대상 교체 설치 연결 리허설 — 격리 확인, 운영 승인 아님

- [x] 수용9ae90c4f의 설치 이미지 그대로 실제 별도 LOGIN API/host 역할로 정상 경로를 확인했다. 후보 prepare→정상 bootstrap/login·CSRF 관리자 preview/decision→host CLI apply→API 조회가 통과했고, 감사 이벤트 session actor도 API→host→host로 구분됐다. role은 NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOREPLICATION/NOBYPASSRLS이며 ALL TABLES/포괄 권한으로 통과시키지 않았다.
- [x] API에는 auth/session과 admission에 필요한 명시 table/column 권한만, host에는 control/ACK·대상 전환과 관측에 필요한 권한만 사용했다. API의 계약 UPDATE·완료 phase UPDATE·후보 INSERT·이력 DELETE, host의 password_hash SELECT·accounts UPDATE는 모두 부여되지 않았다. API에 socket/host key/owner backup을 마운트하지 않았다. 두 프로세스 UID10001이며 host만 daemon group과 고정 native 권한을 갖는다.
- [x] 실제 설치 host 진입점에서 별도 binding 누락/불일치는 exit2로 차단하고 exact 파일만 채택했다. 기동 뒤 logical slot1/desired0/disabled와 새 native target created·미시작을 유지했다. config/key leaf는 RO, receipts만 RW이고 기존 config를 덮어쓰지 않았다.
- [x] 같은 별도 운영 DB 복원본에 migration loader로012·019만 함께 적용했다. 기존51개 업무 table의 기존 열 값·기존 migration facts·원 snapshot/자산/#5 raw running·제어/ACK 이력이 보존됐으며 신규 교체/복구 기록은 만들지 않았다. --no-owner/--no-privileges schema/data 범위이며 전체 cluster ACL 복구 수용은 아니다.
- [x] 이전 lint 보고를 정정한다. 수용 첨부 기준 **신규 위반0·기존 위반4**다. 2개 또는 전체 lint 통과로 기록하지 않는다. 이번은 기능/소스 변경 없이 설치 연결만 확인했고 수용47개·MQ 영상·A/B 전체를 반복하지 않았다.
- [ ] 전체 대상 교체 설치는 별도 승인이다. 현재 유지보수 API 선행 설치와 기존 슬롯/송신3개 정지만 수행했으며 host267은 계속 실행 중이다. 아래 runtime의 실제 역할 GRANT·호스트 소유권 반납·설치/대상 전환을 검토해야 한다. 운영012/019·pin/실행 이미지·원본17개 이관·#5 복구·추가 슬롯·유료 호출은 계속 제외한다.

### 논리 슬롯1 대상 교체 — 소스·격리 검증 PM 수용, 운영 적용 대기

- [x] 호스트가 정확한 이전/새 container·image·labels·worker와 정상 중지 signed ACK를 대조해 후보를 준비한다. API는 후보ID만 받아 관리자 권한·사유·개정/관측 ABA·명시 확인을 묶어 preview/decision을 남긴다.
- [x] 019의 불변 계약/후보/계획·교체 기록/이벤트와 target epoch로 이전 계약·요청·ACK·boot를 보존한다. 기존 논리 슬롯/개수는1·원하는 개수0을 유지한다. API에는 Docker 권한이나 계약/완료 덮어쓰기 권한을 주지 않는다.
- [x] 이전 host/session 소유권과 활성 sender가 있거나 진행/unknown 제어·미해결 전송이 있으면 교체를 막는다. 종료0·동일 boot·서명 ACK·no-restart와 새 대상 정지 상태를 재확인한다. 중단된 applying은 held, commit 뒤 응답 유실은 같은 완료 기록 반환이며 자동 교체/재신호/시작은 없다.
- [x] 실제 PG의 새 경계·기존 제어/복구 회귀, 정상 인증/CSRF 관리자API, 실제 별도 native 컨테이너의 offline CLI와 signed ACK를 검사했다. native 시험의 상태 보고는 PG fixture이며 MQ 영상·모델/GPU 추론·A/B 브라우저 여정을 반복하지 않았다.
- [x] PM source9ae90c4f 수용·App push와 격리 최소권한/실제 host 진입점·별도 바인딩 연결을 확인했다.
- [ ] 실제 운영 역할 GRANT·새 호스트 설치·exact 바인딩과019 교체 승인 경로의 검토·승인은 남아 있다. 기존018의 정상 유지보수 관리자 접속은 위 선행 설치에서 수용됐다. 대상 교체에는 새 호스트 실행 코드가 필요하므로, 앞선 공용 입력 compatibility의 'host binary 유지 가능'을 이번 새 기능 설치 승인으로 해석하지 않는다.
- [ ] 대상 교체의 운영 적용은 별도 승인이다. 유지보수 API 선행 설치와 기존 슬롯 Stop0가 완료돼도019/호스트 코드·계약·pin 전환은 미실행이다. 현재 상태는 위 체크포인트를 따르며012/019 부재·원본17개·#5 원기록을 유지한다. 별도 신규 교체 UI는 없고 관리자API와 host 전용명령 범위다.

### 공용 입력 운영 교체 전 호환성 — 검증 완료, 고정 대상 교체 gate 미해소

- 공용 읽기 d4a628a8은 PM 수용·App push 완료다. 이 호환성 검증 당시 운영 앱/웹 c106·호스트26710eb0·기존 실행 이미지6986은 변경하지 않았다. 이후 유지보수 API 선행 설치와 안전 정지는 위 별도 체크포인트이며 공용 기능의 정상 공개가 아니다.
- 별도 실제 TLS MQ/S3와 clean-source 후보 앱/CPU 이미지에서 기존 입력과 source_owner_id 공용 입력을 각각 encode→validate 완료했다. 두 작업 모두 각 노드 attempt1, 결과 inbox2/S3 receipt·원격 GET SHA/전체 decode 정상이며 최종 queue ready/unacked0이었다. A/B 브라우저 전체는 반복하지 않았다.
- 실제 기존 앱/CPU/model/GPU reader는 새 참조를 거부하고 후보4군은 기존·새 참조를 읽었다. 경로 탈출 origin/digest-key 불일치도 후보에서 거부했다. 모델/GPU는 기존 image layer/환경/entrypoint를 보존한 shared 설치본 읽기·검증이며 모델별 추론·engine-v2 MQ 전체를 다시 수용한 것은 아니다.
- 운영 백업을 별도 PG의 별도 DB에 복원해012만 적용했다. 기존51개 table의 기존 열 값·작업6개·immutable snapshot/원본/#5·제어 group/이력은 동일했다. 이전 c106 앱도012 상태의 기존 snapshot을 읽었지만, 새 공용 입력을 처리할 수 있다는 뜻은 아니다.
- 일괄 호환 범위는 앱4·CPU6·model2·GPU2·웹1의15개 프로그램/후보 image5종이다. 호스트 binary·collector·PG/MQ/S3 binary5개는 유지 가능하나 encode 재생성 시 새 container/image pin과 계약이 필요하다. API만 먼저 바꾸거나 옛 reader를 남기지 않는다.
- **즉시 운영 교체 불가:** 현재 exact container/image/label 검사와 group contract 등록은 새 target을 거부한다. 복원 DB의 같은 slot/다른 contract 등록도 충돌했고 원 group/이력은 보존됐다. 운영 pin을 완화/직접 수정하지 않았으며, 권한/사유/CAS/감사 대상 교체 절차는 위019 구현의 PM 검토와 별도 설치·운영 승인 gate다.
- 승인 후 교체안은 신규 접수 중단→진행 처리/ACK/drain 정리→송신 앱/소비자 종료→최신 백업·복원 확인/승인된012→후보 준비→위 target 교체 gate→맞는 앱/웹·관측/결과 수신과 명시 시작/fresh ready 확인 순서다. 현재는 그 gate를 넘지 않는다.
- 새 공용 작업이 생긴 뒤에는 옛 앱/reader/FK로 단순 복귀할 수 없다. 합성 DB에서 옛 owner FK 재추가는 거부됐고 probe를 rollback했다. 신규 원본/작업/산출물/판단을 지우는 DB 전체 복원이나 owner 재배정 대신 origin-aware 설치본을 유지한 정지·forward fix/별도 승인 복구가 필요하다.
- 운영012/image/host 지정 변경·원본17개 이관·#5 복구·추가 슬롯·배치 이전·유료 호출은 수행하지 않았다. 원 source와 WIP21·실제 운영 자원 보존/정리 결과는 비공개 호환성 인계에 둔다.

### 남은 제품 범위

- [x] 인증 사용자 공용 원본·작업·결과 읽기/다운로드 API·UI와 격리 설치본 A/B 회귀.
- [ ] 위 공용 읽기 수용본의 운영 반영. 운영012·기존 원본17개 공용 이관은 별도 검토/승인 전까지 수행하지 않는다.
- [ ] 보존 원본17개(29,073,982,271 bytes)의 공용 멱등 이관·대용량 보관/다운로드/재생. 새 작업의 티켓별 manifest/중간·최종 저장 배치와 기존 owner-CAS 호환 읽기는 위 별도 구현·격리 검증 범위다. 기존 전체 SHA 확인을 반복하지 않으며 목록 등록만으로 원본 이관을 완료하지 않는다.
- [ ] 실제 공급자 인증·전사 정확도/번역 품질·승인된 외부 호출과 운영 연결. 등록 모델 전사·번역/언어/유한 폴백의 구현·격리 HTTP 계약 검증은 위 별도 완료 범위다. Gemini 등록이나 통제 서버의 응답을 실제 공급자 인증·품질 성공으로 확대하지 않는다. 로컬 Whisper 기본 대체·유료 외부 호출은 승인하지 않았다.
- [x] 순수 제품 UI의 모델·언어/선택형 폴백→티켓→승인→실행→결과는 개발·격리 확인 완료, `62d4fdf2` PM 수용·App push로 종료했다. 공통 캔버스도 위 별도 개발·격리 수용 완료 범위다.
- [ ] 위 제품 UI/정식 실행 경로의 운영 연결·배포와 실제 공급자 인증/품질은 미완료다. 개발 수용을 운영 수용이나 정상 접수 재개 승인으로 해석하지 않는다.
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
- [x] 일반 model_ref 전사/번역의 명시 설치 진입점·owner-scoped resolver·address-pinned 전달을 위 격리 설치 경계까지 연결한다. 고정 offline STT/en→de/GPU engine v2와 별도이며 서로 몰래 대체하지 않는다.
- [ ] 승인된 실제 공급자 egress/인증·STT/번역 품질·운영 연결, 미지원 Anthropic/TTS·장시간 분할은 별도다. 통제 서버의 설치 연결 결과를 실제 provider 수용으로 확대하지 않는다.
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
- [x] 순수 UI-only 모델·언어/선택형 폴백 선택부터 티켓·승인·실행·결과 받기는 개발·격리 확인 및 PM 수용·App push 완료다. 수정 전 PC 성공과 수정 후 PC 취소/390px 성공·취소의 관측 구분은 위 수용 기록을 따른다.
- [ ] 공용 원본 이관·실제 공급자 인증/품질·운영 연결 및 기타 미수용 범위는 별도로 남긴다. 개인 소유권 배정은 현재 요구가 아니다. initializer 정리 1건은 제품 기능 미완료가 아니라 별도 승인 대기다.

## 미확정 사항

스토리지 제품·배포 위치, 외부 실행 관리자, drain 제한시간/강제중지와 장애 후 소유권 인계는 [미확정 기획](ideation.md)에서 별도 결정한다. 원본·작업 이외의 관리 기능과 서버 전체 에이전트 제어는 관리자 전용이다. 현 CPU 기본 동작은 강제 종료가 아닌 drain이다.

## 관련 문서

- [구조](architect.md) · [실행 계약](../references/high/runtime.md) · [미확정안](ideation.md)


### Preserved-transcript product reprojection (after 8167ca87)
- [x] 8167ca87 was source-accepted/App-published by PM1563523350582796321; original remote SHA was independently matched. Operating remains unchanged. The earlier 321s and later wire/package image proofs remain distinct.
- [x] Candidate only: separate additive023 projection_recoveries previews/one-shot admissions/outcomes bind the committed delivery + accepted inbox digest, original failed run/snapshot/request/result, preserved parsed transcript/audio/clock refs, original projection policy and current projector source SHA. No source job/run/budget/outbox is rewritten, resumed or promoted.
- [x] Preview and confirm verify actual CAS bytes/SHA, PCM frames and original clock/profile before model-free projection. Output transcript/trace remain separate artifacts, with explicit acknowledgement and authenticated shared JSON downloads. The original job and descendants stay failed/blocked. Same cause/invalid material is refused, not repaired by guessing word alignment or silently changing clocks/policy.
- [x] Product job-detail panel supports reference/policy selection, exact SHA review, preview/reopen, explicit confirmation and separate history/downloads. Real isolated PG/auth/API/CAS PC1440 +390 journey completed one operation and two actual download events; original source rows and model spend stayed identical. Initial controlled ASR setup is NOT a recovery model call or provider-quality evidence. Browser bootstrap initially lacked host port binding on the internal-only fixture network; existing loopback fixture bridge attachment fixed the harness without operating network changes.
- [x] New immutable recovery evidence cannot be deleted/rewritten. Durable admission commits before CAS writes; final commit uncertainty stays running/held and is never automatically replayed. Wrong context/policy, missing/mismatched accepted result evidence, source-byte tampering, nonowner writes and missing CSRF fail closed. File verification runs off the API event loop and outside the source scheduling lock.
- [ ] No live023/020/022 migration, consumer/preview/GPU/target/slot/permission/paid activation. Operating rollout, automatic vocal runner, real6h/large independent S3-MQ/large-input/long encode-GPU, full review/multilingual equivalence and mixed consumers remain pending. This is recovered artifact production, NOT automatic continuation/translation/video execution or arbitrary transcript/clock editing.


## 에이전트 전용 흐름·실제 소스 계층 — 적용 확인

### 무엇을 만들었나
- 워크플로우에는 전사 → 한국어 번역 → 자막 영상 제작 에이전트만 연결한다. 에이전트가 자기 툴 순서·호출·결과 검사를 맡고, 오케스트레이터는 에이전트 간 배정·준비를 관리한다.
- 오케스트레이터는 `apps/orchestrator`, 업무 에이전트는 `agents`, 실제 도구는 `tools/media`, `tools/models`, `tools/gpu` 및 `packages/tool-hub`, 실행기 수명주기는 `runtime/controlnet`, 모델 실행기는 `runtime/model-executor`로 실제 이전했다. 옛 import는 필요한 얇은 호환 경계만 유지한다.

### 어떻게 쓰나
- 기존 개발계의 저장된 ‘영상 전사·한국어 자막 번인’을 열어 영상·등록 모델·언어를 선택한다. 실행 캔버스에는 에이전트만 나오며, 노드를 열면 내부 툴의 진행·출력·실제 콘솔을 확인한다.
- 모델 요청 오류는 붉은 에이전트 오류로 표시한다. 불명 원장과 보류는 그대로 남고 자동 재호출하지 않는다.

### 실제 확인
- 기존 개발계 API·오케스트레이터·연결부·ControlNet·웹을 교체했다. 실행 중인 canonical 모듈 바이트와 커밋 소스, 실제 HTTPS JS/CSS와 설치 이미지 바이트를 비교했다.
- 기존 활성 정의 세 개를 에이전트 3개·연결선 2개의 새 revision으로 저장하고 읽어 확인했다. 과거 실행 snapshot·작업·run·호출·역할 task 원문은 교체 전후 동일하다.
- 저장된 편집기의 재열기 화면, 작업 31의 오류와 내부 툴, PC와 390px·줄어든 모션, 완료 툴/대기 에이전트의 로그 탭을 실제 화면에서 확인했다. 브라우저 후속 검사 timeout은 남겼고, 그 전에 저장된 실제 편집기 화면과 HTTPS 근거 파일을 회수·검증했다.
- 전사·번역 연결부에만 승인된 기존 외부 경로를 유지했고 DNS·인증서 검증 TLS를 확인했다. 해당 진단에서 HTTP 요청은 보내지 않았다.
- 포장 경로·로컬 설치 의존성·GPU 도구의 미디어 helper import 회귀를 수정했다. GPU는 모델·torch를 로드하지 않는 import 검사만 했다. 독립 재검토에서 새 보안/논리 문제는 발견되지 않았다.

### 남은 검증과 명확한 한계
- 새 작업·30/31 재실행·모델/provider·유료/GPU 호출은 하지 않았다. 따라서 전사 완주·새 자막 MP4·실제 새 콜드부트 전환의 검증 근거는 아니다.
- 준비 연결선은 실제 기동/준비/배정 관측을 사용하도록 연결하고 오프라인 회귀로 검사했다. 새로운 실운영 준비→시작 전환 관찰은 실행 승인 범위 밖이다.
- 과거 HTTPError에 남아 있지 않은 상태 코드·원문·콘솔을 만들지 않았다. 없는 로그는 없다고 표시한다.
- 전체 웹 회귀의 기존 실패는 남아 있으며, 이번 변경 범위 검사·타입 검사·웹 빌드 성공을 전체 검사 통과로 표현하지 않는다.


## 실제 사용자 작업 32 — 공개 그래프 경계 보정
- 무엇: 작업 생성/상세의 공개 `snapshot.definition`을 고정 에이전트 정의로 통일하고, 원래 내부 툴 계획은 `tool_definition`으로 분리했다. 클라이언트는 내부 툴 계획을 캔버스 대체값으로 그리지 않는다. 기존 에이전트 소유 invoker·내부 실행 계획·원장은 변경하지 않았다.
- 사용: 기존 32를 그대로 새로고침해서 전사·한국어 번역·자막 영상 제작 에이전트를 보고, 각 상세에서 내부 툴·출력·로그를 연다. 재발행할 필요는 없다.
- 확인: 실제 32의 고정 정의는 처음부터 올바른 에이전트 경계였다. 같은 32의 실제 HTTPS 응답·세 노드 정상 이름·부모별 툴과 출력/로그·전체 재열기를 확인했다. 같은 원본/워크플로우를 선택한 발행 전 화면도 세 에이전트였다. 원래 작업/실행/설정/호출/task 데이터는 비교 전후 동일하며 API와 웹만 교체했다.
- 한계: 최초 첨부 화면 당시 브라우저가 어떤 응답/번들을 읽었는지는 미확정이다. 캐시나 사용자의 옛 정의 선택으로 단정하지 않는다. 새 생성 함수 검사는 실제 handler와 저장 대체 객체로 했으며, 새 작업 실제 발행·32 시작/취소/삭제/재발행·provider/GPU 실행은 하지 않았다.


## LiteLLM SDK·워크플로우 LLM 선택 — 개발계 반영 완료, 유료 완주 별도
- 무엇: 특정 LLM 이름 제한을 제거하고 기존 모델 툴 안에 SDK를 연결한다. 새 Proxy·플랫폼·브랜치·유료 활성화 토글은 만들지 않는다.
- 사용: 워크플로우에서 등록 모델 버전과 요청 옵션을 선택하고 저장한다. 새 작업은 그 선택을 고정한다. 과거 작업은 다시 쓰지 않는다.
- 확인: 실제 저장/재조회/생성 함수를 메모리 SQL 경계로, 실제 SDK를 외부 socket 금지·메모리 HTTP 경계로 검사했다. 서로 다른 전사/번역 모델·revision·timeout/max_tokens가 실제 SDK wire에 유지됐다. 이는 제품 DB에 새 작업을 발행하거나 실제 공급자를 호출한 검증이 아니다.
- 확인: SDK의 스키마·옵션·추론 강도 변경/누락은 외부 전송 전에 거절한다. 과거 고정 요청의 허용 범위·wire·대기 시간을 유지하고, 잘못된 전사 시각은 기존 오류 기록 경로로 처리한다. 독립 최종 검토에서 보안/논리 차단 없음, 비용 없는 회귀 57건 통과. Windows 패키지 설치·실제 SDK 인자와 웹 빌드를 확인했다.
- 반영: 실행 코드 `5da2bdccead9286499bf0daf3f12df6f12a16ccb`를 기존 개발계의 API·모델 연결부·결과 수신/조율·웹에 설치했다. Linux Python 3.12의 실제 설치 패키지에서 외부 네트워크 없는 SDK 회귀 57건이 통과했다. 원래 FastAPI/Pydantic/HTTPX 버전은 유지하고, 필요한 boto3/botocore만 1.43.117로 고정했다.
- 실제 확인: 실행 중인 모듈 bytes·SDK 버전, 기존 HTTPS의 화면/정적 파일/인증 경계, 저장된 워크플로우 모델 revision과 옵션 입력의 PC/390px 화면, 원본 두 개의 TLS 저장소 HEAD 200을 확인했다. 원본·기존 32개 작업·모델/키/워크플로우 revision·시도/불명 원장은 그대로다. 실제 GitHub renewal을 정상 푸시하고 API·Git transport·원격 소스 bytes를 재조회했다. master·다른 공개 브랜치·기존 로컬 브랜치는 변경하지 않았다.
- 보존: 기존 실행 정의를 SDK로 다시 쓰지 않았다. SDK 계약은 새 작업 생성부터 고정된다. 새 제품 작업/원본 생성·기존 작업 시작/재실행·공급자/유료/GPU 호출은 하지 않았다. 종료한 구 배포 컨테이너만 로그·tmpfs·변경 파일을 보존한 뒤 제거했고, 볼륨·네이티브 실행기는 유지했다.
- 남음: 전 구간 무발화 후 번역 입력, 16KB를 넘는 번역문 재분할, 독립 전사 다중 후보는 기존 입력/설정 제한으로 남는다. 실제 공급자 인증·과금/할당량·품질과 전사→번인 MP4 유료 완주는 미검증이다. 기존 프런트엔드 테스트 실패는 이 SDK 검증 통과와 구분한다.


## 5178 기준 기능 대조·일반 사용 흐름 복원 — 진행 중

### 확인한 기준과 판정 방법
- 기준 웹: `mideagent-legacy-web`, `video-subtitle-web:dep01-rollback`, 실제 5178→80. API와 기존 worker도 별도 legacy 컨테이너이며 수정/재기동하지 않았다. API/shared 실제 설치 소스를 읽고 내부 OpenAPI와 공개 배포 번들을 대조한다. revision label이 없어 master 동일성은 미확인이다.
- 구현 체크아웃의 시작점은 `df3f49517a974de452bd22f70889ead63f468ed2`의 깨끗한 detached HEAD다. 새 브랜치를 만들지 않는다. 실제 5178의 기존 원본/작업 목록과 설정/원본 상세를 읽었으나 처리/저장/삭제/모델 목록 요청은 실행하지 않았다. 미디어 로딩도 차단했다.
- 아래는 이번 판정이며, 과거 수용과 현재 소스·화면 관찰 및 새 실행 검증을 섞지 않는다.

### 기능별 대조
- 원본 보관·업로드/블록 재개·다운로드: 5178 실제 목록/상세와 API 경로 확인. renewal에는 기존 구현/수용 근거가 있으나 이번 새 업로드 실행은 하지 않았다. 입력/결과 연결 범위 재대조 대상이다.
- 오디오만 추출·전사만·전사 후 번역·선택 자막만 번역·인코딩만·전체 처리: baseline의 실제 workflow API/`workflows.py`에 여섯 계약이 있다. 이번 기존 작업 재실행은 하지 않았다. renewal 내부 툴은 있으나 공개 에이전트 입력·독립 시작·출력 선택 연결이 제한된다.
- 이전 추출 오디오 재사용: baseline의 같은 영상·완료·미만료 WAV 선택/검증·snapshot 경로 존재. 임의 외부 오디오 업로드 기능과는 다르다. renewal 전사 에이전트가 항상 영상에서 추출/전처리하므로 입력 재사용 연결 누락을 확인한다.
- SRT 첨부·기존 자막을 번역/영상에 사용: baseline 원본 상세의 SRT 첨부와 API 계약 확인. renewal 공개 workflow는 외부 입력을 빈 객체/영상으로 제한해 transcript/subtitle 입력 선택 연결이 누락된다.
- 언어 선택: baseline이 원문/목표 언어를 받는다. renewal이 catalog/번역 계획/영상 제작에서 ko를 강제하는 소스상 차단을 재현했다. 영어·일본어 선택값이 번역/자막 도구까지 유지되도록 첫 RED→GREEN 2건을 통과했다. 아직 개발계 반영/범용 흐름 전체 완료는 아니다.
- 자막 SRT/SMI·원문/번역 트랙: baseline은 편집/결과 API와 화면 호출 경로가 있고 renewal에도 내부 계약이 있다. 공개 제작 에이전트가 SRT/한국어 번인만 강제하므로 선택/출력 연결을 보완한다.
- burn/soft/none·코덱/화질/해상도: baseline workflow API가 지원하며 renewal 내부 encode도 지원한다. 공개 제작 계획의 burn 강제·선행 번역 강제가 일반 영상 제작을 막는다.
- 자막 시각·문구 편집/검수·재내보내기: baseline PUT subtitle draft/SRT·SMI 결과 경로가 있다. renewal 기존 검수 backend와 공개 에이전트 작업 동선의 연결을 재확인한다. 실제 편집/내보내기 성공은 이번에 미실행이다.
- 큐·취소·오류·재시도 안내·작업 결과 받기: 양쪽 API/화면 경로를 대조하고 새 업무 구성에서 실제 상태/출력·원문 콘솔을 유지한다. 기존 사용자 작업 취소/재실행은 금지다.
- 모델/STT·fallback·저장소 설정: baseline 실제 설정 화면/API와 renewal registry/LiteLLM 연결을 대조한다. 모델/provider 목록 요청도 이번에 보내지 않았다. 전사 다중 후보는 현재 독립 실행 제한으로 남아 있다.
- 얼굴 합성의 장면 미리보기·전체/구간·이어 처리: baseline 배포 번들과 실제 API 경로 존재. renewal의 과거 제외/엔진 보존 및 공개 업무 연결 상태를 별도 항목으로 대조한다. 이번 GPU 실행·기존 합성 작업 조작은 하지 않는다.
- 무발화·번역 길이 확대·전사 다중 후보: 알려진 세 차단도 구현 범위에 포함하지만 전체 기능 목록을 이 세 개로 축소하지 않는다. intent/예산·취소·결과 불명 보류와 과거 snapshot은 보존한다.

### 허용 계약을 소스로 추가 확인한 결과
- 비교 근거는 실제 legacy API의 설치 소스다. `api/workflow_routes.py`의 엄격한 요청 모델과 `video_service/workflows.py`의 순수 정책을 함께 확인했다. 복사한 정책 함수만 메모리에서 72가지 입력 조합으로 실행해 30가지 허용/42가지 거절을 구분했다. 이는 API 신규 작업 생성·정상 처리·GPU/모델 실행 증거가 아니다. AST로 수집한 61개 route 항목은 각 APIRouter의 실제 prefix까지 붙여 대조했으며, 서버 전체의 처리 성공 개수로 사용하지 않는다.
- 여섯 업무는 `extract_audio`, `transcribe`, `transcribe_translate`, `translate`, `encode`, `full`이다. 번역만은 선택 자막이 필수이며, 인코딩은 `none`일 때 자막 입력이 없어야 하고 `burn/soft`일 때 있어야 한다. 선택 자막은 번역/인코딩/전체에서만 받는다.
- 기준의 오디오 재사용은 **같은 영상에 속하는 완료 작업의 `work/audio.wav`**다. 결과가 만료되지 않고 파일이 남아 있어야 한다. 임의 외부 MP3/WAV 업로드를 기준이 이미 지원한다고 해석하지 않는다. renewal의 오디오 파일 직접 입력 확장은 이 재사용 계약과 구분한다.
- 기준 자막 입력은 SRT 첨부 또는 완료 작업의 특정 원문/번역 트랙을 revision에 묶어 가져오는 경로다. 완료 작업 편집은 `save`만 허용하며 모든 트랙의 SRT, 원문 이외 트랙의 SMI를 갱신하고 `video_subtitles_outdated=True`를 기록한다. 완성 영상은 자동 재인코딩하지 않는다. 검수 대기 작업은 revision 일치 후 `save/render`를 지원하고, `render`는 `QUEUED`로 이어진다. 이는 모든 작업에 검수를 강제한다는 뜻이 아니다.
- 기준 큐에는 revision 조건부 일시정지·대기 순서 변경이 있다. 선택 대기 작업 일괄 취소는 별도 요청이며 revision을 받지 않고 소유자·비내부 작업을 검사해 대기 작업만 취소, 이미 시작한 작업은 건너뛴다. renewal의 개별 작업 취소·영속 발행 대기열은 이 세 기능과 동등하지 않다. `VideoWorkspace`의 큐 popover는 `!renewalBackend`에서만 보이고 renewal API에 `/api/queue` mount가 없어 현재 연결 누락으로 판정한다.
- 기준 저장소 설정은 조회 외에 `temporary/jobs`를 구분한 명시 작업별 정리가 있다. `temporary`는 완료 작업만, `jobs`는 종료 상태 작업만 허용한다. renewal은 `SettingsPage/StorageSettings` 대신 `SystemSettings`로 분기하고 대응 storage mount가 없어 현재 연결 누락이다. 시스템 조회·원본 목록 숨김은 정리 기능과 동등하지 않다. 실제 삭제/정리는 이 비교에서 실행하지 않는다.
- 기준 얼굴 합성은 session revision·대상 얼굴/원본 얼굴 선택·분석/미리보기/렌더 요청을 받는다. 전체 렌더는 현재 설정과 같은 fingerprint의 완료·유효 미리보기가 필요하고, 준비 실패/대상 미선택/미리보기 불일치를 거절한다. 번들의 구간/이어 처리 안내와 달리 요청 모델에는 사용자 지정 start/end 구간 필드가 없다. 실제 chunk 실행/이어 처리 및 renewal의 대응 session·미리보기 연결은 아직 미확인이다.
- renewal 원본 자막 목록 API는 현재 빈 목록을 반환한다(`renewal_routes.source_no_subtitles`). 별도 자막 트랙 검수 API는 존재하지만 검수 ID에 묶여 있다. 일반 에이전트 작업의 자막 첨부·완료 후 편집/새 revision 내보내기 동선이 연결됐다고 판정하지 않는다. 원본 상세를 다시 작업 설정 화면으로 만들지 않고 작업 입력/상세에서 제공한다.
- renewal의 기존 `FaceSwapDialog`와 `SubtitleEditor`는 파일/조건부 JSX가 남았지만 각각 여는 setter 동선이 없고, 작업 상세는 `RenewalJobDetail`로 분기한다. 대응 faceswap session·legacy 자막 draft mount도 없어 현재 공개 연결 누락이다. GPU 툴 코드나 검수 ID 기반 자막 API의 존재로 복원 완료 처리하지 않는다. 얼굴 합성은 기준의 원본 이미지·얼굴 선택·동일 설정 미리보기·세션 대기 한도·용량 검사까지 보존하는 후속 구현 대상으로 남는다.

### 현재 소스 검증과 배포 경계
- 일반 사용 흐름: 원문/번역 자막 파일, SRT·SMI, burn/soft 자막 영상, 모델 없는 영상 변환과 음성 추출을 공개 업무 목표·결과 받기 경로로 연결하는 소스를 구현했다. 실제 개발계 반영·새 CPU 결과 다운로드 수용은 아직 아니다.
- 부모 직접 검사: 일반성·명령 생성/실패 정착·실제 create/recover 메서드의 메모리 경계 회귀 93개 통과. 연속 번역 입력 언어와 실패한 목표의 대기 고착을 수정했고, 복구 자식은 부모 정책의 필드 부재·값·고정 입력/모델을 보존한다. 같은 계약이 아닌 재컴파일은 자식 생성 전에 거절한다. 과거 사용자 작업으로 복구를 실행하지 않았다.
- durable v2의 독립 정적 검토는 보안/논리 차단 없음이다. 이것을 LangGraph·SQL 동시성·실제 공급자 수용으로 확대하지 않는다. 새 일반 작업에만 내부 `role_policy_version=2`를 고정하며 기존 복구는 부모의 부재/1/2를 유지한다.
- 실행 이미지 빌드 검사에서 기본 graph-base의 LangGraph 누락과 runtime Dockerfile의 requirements 설치 누락을 확인해 보완했다. 고정 의존성·빌드 도구를 준비한 후보 이미지의 설치 모듈에서, fixture 수정 후 **순수 회귀 37개와 명시 그래프 검사 14개를 분리 실행해 통과**했다. 이전 혼합 실행의 16통과/1실패는 전체 그래프 개수로 사용하지 않는다. ContentStore의 기존 root 보호는 그대로다.
- 검증 도구로 보완한 이미지와 실제 shipping recipe를 분리해 확인했다. 실제 Dockerfile의 `--no-build-isolation` 때문에 발생하던 build backend 부재는 선언된 PEP 517 backend의 격리 준비로 수정했다. 빌드 도구를 미리 설치하지 않고 offline wheel index만 제공한 실제 recipe 빌드가 성공했고, UID10001에서 설치된 전사·번역 import도 통과했다. 그 실제 이미지 위에서 **순수 회귀 38개·그래프 14개**, 의존성 검사, 동결 소스 Python 160파일 SHA 및 원래 base 의존성 버전 보존을 확인했다. 별도 서비스나 사용자 작업을 시작한 결과는 아니다.
- SQL bridge의 실 PostgreSQL 동시 호출 cap/intent commit/취소 fence 수용과 실제 API/UI/다운로드 수용은 아직 남아 있다. 단순 도우미 검사와 source-only 결과를 일반 실행 완료로 보고하지 않는다. 별도 서비스·DB·브로커 검증 스택, 실제 provider/GPU 호출, 기존 작업 재실행은 시작하지 않았다.

### 우선 구현과 수용
1. 사용자 언어/자막 방식·형식과 불필요 단계 생략을 실제 업무 에이전트 계획에 전달한다. 툴 backend 존재만으로 기능 완료로 판정하지 않는다.
2. 선택 자막/오디오·추출/전사/번역/영상 단독 흐름의 입력·설정·결과를 기존 API/UI 동선에 연결한다.
3. 무발화, 큰 번역 출력, 전사 후보 체인의 durable 실행을 보완한다. 기존 원장·완료 구간을 다시 과금하거나 unknown을 자동 재시도하지 않는다.
4. 관련 회귀/빌드·독립 검토 후 기존 개발계에 설치하고 실제 화면/허용된 CPU 결과·다운로드를 확인한다. 기준5178은 교체하지 않으며 새 테스트 입력이 필요하면 최소 범위·정리 대상을 먼저 명시한다. 유료/provider/GPU·장편 처리는 별도다.

### 독립 목표의 제한 소스 구현 — 운영 미반영
- [x] 원문 ASR → 자막 파일 목표를 번역·인코딩 없이 컴파일하고 원문 참조를 번역 후에도 보존한다. 선택한 원문/번역, 언어, SRT/SRT+SMI, 번인/소프트 자막을 각 네이티브 도구에 명시 전달한다. 지역 번역 언어는 보존하며 자막 도구에만 지원하는 기본 언어를 전달한다. 자동 인식 언어를 감지했다고 표시하지 않는다.
- [x] 영상 변환은 encode(none)→validate_video만, 음성 추출은 analyze→extract_audio만 소유한다. 음성 결과는 기존 16kHz 모노 WAV이며 MP3/원본 오디오 보존 기능으로 표시하지 않는다. 모델 선택이 불필요한 목표를 별도 모델 입력으로 막지 않는다.
- [x] 새 snapshot은 요청한 출력 쌍만 동결하고, 실제 완료된 소유 도구의 타입·파일 참조가 유효할 때 목표 결과를 공개한다. 공개 결과에는 run/node/port/type 식별자만 두며 기존 인증 산출물 경로를 사용한다. 내부 도구 선택 없이 결과를 열고 받을 수 있는 UI를 연결하고 출력·로그 탭을 보존한다.
- [x] 새 출력 정책에서 사용된 파일과 공개된 최종 파일을 구분한다. 기존 snapshot·receipt·manifest·저장 행은 수정하지 않고 이전 분류를 유지한다. 저장/재열기/시작 화면에서 공개 옵션과 tool_settings의 역할 매핑·조건부 SAMI 포트를 일치시킨다.
- 검증: 비용 없는 합성 단위 데이터만 사용해 `test_workflow_generality.py` 29개 통과, 목표 UI/공개 캔버스 대상 테스트와 타입 검사·개발 빌드 통과. 지정 unit-venv의 Python 실행 경로가 없어 기존 Python 3.14와 해당 unit 패키지를 격리 조합했으며 추가 설치는 하지 않았다. 실제 DB·API·미디어 처리·다운로드 성공 증거가 아니다.
- 잔여: 전체 웹 suite의 기존 실패 7건, 전체 lint/format 부채를 별도 기록한다. 오디오 파일 외부 입력·첨부 자막 편집·전사 후보 체인·빈/큰 번역 출력은 이번 writer 범위 밖이며 위 전체 parity 계획에 그대로 남긴다. 기존5178 접근·새 작업/업로드·provider/GPU·서비스 변경·커밋/푸시/배포는 실행하지 않았다.


### 2026-11-12 정상 입력·고객 화면 보정 — 소스 수용, 배포/실사용 수용 별도
- 구현: SRT/완료 전사문과 같은 영상의 완료 원본 추출 WAV를 업무 시작 입력으로 선택한다. 파일만/자막 영상/선택 자막 번역/음성 재사용 전사는 명시된 단계만 사용한다. 전체 입력 한도는 실제 native 계약에 맞추고 모델 wire 분할 한도와 구분한다. 새 선택 자막만 cue 시각·ID·문구를 보존하며, 겹치는 화자도 순수 SRT로 보존한다. 번역·SAMI의 기존 제약과 과거 reflow/snapshot 의미는 유지한다.
- 보존: 선택자의 완료 receipt·실제 bytes/hash·원본 영상·custodian을 확인하고 preview token/create에 고정한다. 원래 command/입력/모델/출력 owner를 다시 쓰거나 source를 복사해 소유권을 바꾸지 않는다.
- 고객 화면: 휴대폰에서 파일명+상태를 함께 보이게 정리하고, 목록/상세의 같은 상태 표시·한글 언어명·누락 입력 표시·실제 개별 결과/JSON 목록 구분·실패 단계 로그 진입을 연결했다. canvas와 선택·비용·권한·실제 오류/콘솔은 유지했다. 로그인/서빙/처리 확인/설정의 중복 구현 설명을 줄였으며, 현재 노출되지 않는 옛 코드의 단어 검색을 결함으로 단정하지 않았다.
- 소스 수용 근거: 부모 직접 backend151/overlap 한정10/실제 ledger 함수6/소스·SSR 및 offline Edge24 그룹이 통과했다. 서로 겹치는 그룹이므로 합산하지 않는다. 실제 Source-native serializer와 실제 handler를 임시 데이터로 확인했으며 product DB/유료/GPU 수용이 아니다. 부모의 최초 전용venv6 missing-dependency 실패는 보존하고, 기존 설치 Python 환경으로 재검사했다. 설치/네트워크/새 서버는 사용하지 않았다.
- 독립 검토: 최종 복구, durable 정적 검토, 일반 입력의 실제 한도·시각 보존·custodian, 겹치는 전사/SRT 보정, 현재 PM UI·최소 목록 DTO 검토를 각각 통과했다. UI 검토 관측 파일 SHA가 현재 소스와 일치한다. 전체 웹 기존 실패7개와 무관한 lint 부채는 별도다.
- 기존 개발 PostgreSQL: 같은 제한 principal/DSN의 READ ONLY 실제 공유/취소/task 잠금과 세션 TEMP SQL bridge로 intent commit 실패 전 호출 차단·후보 선행실패/한도/unknown·완료 응답 재사용·용량 보류를 확인했다. 원래 job/run/role/budget/chunk 표 digest는 동일했다. 임시표/통제 어댑터이므로 운영 FK/공급자/실제 HTTP/다중 세션 행 경쟁 전체 수용으로 확대하지 않는다.
- 현재 화면: 기존5da2bdc의 실제 인증 PC/390px 캡처와 실제31 출력/로그 탭을 저장했다.31은 출력 없음·보존 console 없음이며 재실행하지 않았다.32는 이미 admission된 waiting/run0/dispatch0이라 draft용 Start를 추가하지 않는다. 현재 화면 캡처를 수정 후로 부르지 않는다.
- 반영 경계: 이 기록 시점은 source/index/refs 백업과 검토를 마친 릴리스 준비다. 기존 개발계 배포·실제 수정 후 PC/휴대폰 및 허용 CPU 결과/다운로드·실제 GitHub renewal readback은 이어서 확인한다. 새 cue 옵션은 실제 generate-subtitle 패키지에도 필요하므로 API/web 교체만으로 완료 처리하지 않는다. 기존 on-demand pool의 현재 이미지/템플릿과 원본 작업 보호를 먼저 확인했다.
- 전체 범위 잔여: 실제 전달 대기 목록/기존 취소 연결이 다음 최소 단계다. 전체 큐 pause/reorder, 완료 자막의 편집 revision 발행, 공유 CAS 안전 정리, 얼굴 합성 session/preview/render는 별도 미완료다. 목록 숨김을 물리 삭제로, 검수 API를 완료 편집으로, 보존 adapter를 실제 GPU 기능으로 부르지 않는다. 유료/provider/GPU와 사용자 장편/원본·기존 작업 재실행은 계속 별도 승인 범위다.

### 2026-11-12 실제 전달 대기 조회 — 소스 구현, 운영 미반영
- 기존 실행 관리 popover에 renewal용 읽기 경로를 연결했다. `GET /api/renewal/execution-waiting`은 실제 broker_dispatch_queue/node_runs/outbox/jobs를 한 번의 제한 SELECT로 읽는다. 일반 waiting/QUEUED와 admission된 run0/dispatch0 작업을 큐로 세지 않는다. 기존 `_view`의 관측 capture나 cleanup은 호출하지 않는다.
- 실제 pending/sending/sent/received/unknown을 작업별 상태·건수로 묶고 최대100작업과 추가 항목 존재를 표시한다. pending은 현재 admission/세대/claim·미발행 outbox가 일치해야 하며, unknown은 과거 세대/실패 상태만으로 숨기거나 자동 재전송하지 않는다. 공유 읽기와 자기 작업 관리 권한을 구분하고 snapshot/모델 요청/저장 locator/claim/worker/키는 응답에 넣지 않는다.
- 취소는 기존 작업 상세 링크에서 최신 권한/revision으로 확인한다. 새 취소 계약·일괄 취소·pause/reorder·replica 제어는 없다. loading/조회 실패/마지막 확인값/확정 빈 목록과 보낸 뒤 수신 대기/실제 처리를 구분한다. legacy 큐 경로와 기존 normal-input/cue/custodian/UI 보정을 보존했다.
- 소스 검사: 실제 handler/auth 의존성과 실제 SELECT의 메모리 SQL23개, 기존 popover/detail의 오프라인 PC/390px 포함 대상 웹10개, TypeScript/build·변경 파일 lint/format 통과. 독립 검토에서 발견한 sent/received 확정 실패의 잘못된 대기 집계를 보정하고 한정 재검토를 통과했다. 부모가 보정 SELECT를 기존 API의 원래 PostgreSQL 계정·DSN으로 읽기 전용 실행했으며0행·쓰기0을 확인했다. 이는 소스 조회 구문/기존 권한 확인이고 설치된 신규 HTTP 경로·실제 화면/전달·취소·배포 수용은 아니다. native binding42501은 해당 바인딩만 보류한다. Git 게시에는 기존 Windows 사용자 인증만 사용하며 App 전환·새 인증·전역 설정 변경·force-push는 하지 않는다.
- 이후 부모가 이 소스를 검토/반영하고 기존 화면을 읽어 확인한다. 전체 큐 pause/reorder, 완료 자막 편집, CAS 정리, 얼굴 합성 및 실제 유료/GPU 실행은 위 미완료 경계 그대로다.

### 2026-11-12 저장소 현황 — 부모의 기존 개발계 설치·화면·게시 확인 완료
- [x] 기존 시스템 설정의 공급자·모델·워크플로우 링크를 유지하고 저장소 현황 하위 화면을 연결했다. 인증된 `GET /api/renewal/storage-overview`는 원본 목록과 같은 공유/목록 제거 조건으로 count와 bytes만 집계한다. 원본 ID 중복의 기존 조회 충돌을 보존하며 CAS 중복 등록을 임의로 합치지 않는다. 큰 수는 십진 문자열로 전달한다.
- [x] 등록 논리 용량과 기존 `/api/system/resources` 수집 관측의 호스트·오브젝트 볼륨 용량을 구분한다. 두 조회의 로딩·실패·확정0·이전값·오래된/없는 관측을 독립 표시하고 각각 다시 확인한다. 새 화면에 수집기의 원시 이름/경로나 소유자·저장 locator를 노출하지 않는다. 기존 자원 DTO 전체를 개편하거나 기존 노출을 모두 제거했다는 뜻은 아니다.
- [x] 독립 검토의 구역 제목 충돌을 보정했다. 저장소 구역 제목은 일반 흐름 요소로 두어 전역 sticky header 규칙을 상속하지 않는다. 실제 전역 CSS의 computed position/z-index RED→GREEN과 PC1440/390px 재조회 버튼의 포인터 접근을 오프라인으로 확인했다.
- [x] 실제 handler/aggregate/auth의 메모리 SQL·ASGI12건, 기존 접근/PM UI 회귀8건, 실제 AuthGate/VideoWorkspace의 오프라인 PC1440·390px 메뉴/재진입/재조회 검사 통과. TypeScript/Vite build·변경 웹 lint/Prettier·Python syntax를 확인했다. 실제 PostgreSQL/기존 principal의 새 집계 권한·운영 수집기·배포 화면은 이번 검사에 포함하지 않았다.
- [x] 부모가 원래 API 계정·DSN으로 새 집계를 PostgreSQL READ ONLY에서 직접 실행해 등록 원본23개·34212632653 논리 bytes·쓰기0을 확인했다. 보정 후 대상 웹9건도 직접 통과했다. 별도 오프라인 실제 브라우저 비교에서 동결된 수정 전 소스는 스크롤254에서 sticky 제목이 상단 메뉴와 겹쳐 실패했고, 수정 후 소스는 PC1440/390px 실제 비영점 스크롤·재조회 버튼 hit·각66개 수치/시각 접근을 통과했다. 이 테스트는 합성 관측이며 실제 배포 화면을 대신하지 않는다. 전체 소스 검토와 header 차단의 한정 재검토를 통과했다.
- [x] 부모가 25669289bb2f의 기존 API/web 설치·실제 imports/HTTPS/원래 PostgreSQL 권한과 인증된 PC1440/390px 메뉴·원본 수/논리 bytes·실제 저장 공간 관측·비영점 스크롤·값 접근·각 다시 확인200을 확인했다. 기존 Windows USER Git/manager로 정상 FF 게시하고 transport/public API와 대상4파일 bytes도 확인했다. 새 인증/App/전역 설정/force는 사용하지 않았으며 native42501 바인딩만 별도 보류한다. 원래 범위는 읽기 기능으로 한정한다.

### 2026-11-12 SRT 문구 수정·별도 사본 받기 — 소스 구현, 운영 미반영
- [x] 실제 완료 run의 SRT 포트/type와 같은 job/run/node의 목표 출력을 확인해 기존 결과 파일/목표 결과/태스크 출력 옆에 `자막 수정`을 연결했다. 기존 언어별 subtitle-output manifest의 SRT에도 같은 편집기를 연결한다. 작업 전체가 실패해도 완료된 SRT는 이용하며 JSON/SAMI/미완료 run을 SRT로 취급하지 않는다. 원래 보기/받기·파일 목록/로그/그래프·모델/언어/비용·권한/취소 계약은 유지한다.
- [x] 기존 인증된 GET 파일 읽기와 UTF-8 파일 decoder를 재사용한다. 로컬 draft의 cue 문구만 바꾸고 `수정본 받기`로 별도 SRT를 만든다. 무수정은 원본 bytes, 한 cue 수정은 나머지 cue/ID/시각/공백/BOM/줄바꿈을 보존한다. ID는 문자열이며 정상 overlap과 전체121개 cue를 확인했다. 기존16MiB/10000cue 유한 예산을 사용하고 번역 wire100cue/16KB를 전체 입력에 적용하지 않는다.
- [x] 파일/열기·닫기별 새 draft와 AbortController 경계를 적용한다. invalid/empty/불완전 시각/중복 ID/조회 실패를 자료·문구 필드에 연결하고 HTML은 텍스트로 다룬다. 일반 제목 요소로 전역 header sticky 규칙을 피하고, native dialog의 Esc가 기존 태스크 패널까지 닫지 않도록 전파를 막는다.
- [x] 최초 실제 JobFiles 진입 누락 RED→GREEN, 캔버스 패널 Esc 전파 RED→GREEN. 새 parser/selector/read·직접 관련 기존 입력/목표/PM 회귀24건과 실제 AuthGate/VideoWorkspace·production CSS/설치 글꼴의 오프라인 PC1440/390px 검사1건 통과. Blob의 실제 다운로드 파일명/bytes, 원본 그대로/한 cue 변경, 늦은 응답/닫기/다른 파일, 실제 비영점 스크롤·값/버튼 hit를 확인했다. 다운로드 staging/사본은 기존 Hermes scratch 안에서만 사용 후 제거했다. 변경 파일 lint/Prettier·TypeScript/Vite build 통과. 합성 파일/오프라인 검사는 실제 제품 파일·배포 화면 수용이 아니다.
- [ ] 부모 검토와 실제 기존 개발계 배포/읽기 화면 수용은 별도다. 이번 수정본은 서버 accepted 결과가 아니며 영구 편집 revision 발행/원래 파일 저장/영상 재렌더는 미완료다. 기존 custody/model pin/history/NormalInputs/cue/MT/SAMI 정책을 수정하지 않고 서버 쓰기·새 API/권한/작업/실행·운영 접근·설치·Git 게시/배포를 수행하지 않았다. 정리/전체 pause/reorder/얼굴 합성도 별도 미완료다.

### 2026-11-12 직접 SRT 입력·문구/시각 편집·SRT/SMI 사본 — 소스 구현, 운영 미반영
- [x] clean18e89da의 기존 로그인/shell 주 메뉴에 `자막 파일 편집` → `#/subtitles`를 연결했다. 일반 계정도 서버 작업 기능·원본 영상·완료 job·모델 선택 없이 직접 SRT를 편집한다. 로컬 전용 URL만 허용하고 기존 관리자 화면/API 권한은 유지한다. SMI 입력 reader는 추가하지 않았으며 입력은 UTF-8 SRT만 표시한다.
- [x] 기존 파일 decoder/손실 없는 parser/serializer와 입력·Textarea·Pagination을 재사용했다. 문구·시작·종료를 따로 변경하고 실제 입력한 밀리초 시각을 보존한다. SRT는 무수정 raw bytes와 변경하지 않은 ID/시각/문구/공백/BOM/줄바꿈을 보존하고 overlap을 허용한다. 기존 literal/string/큰 정수/공백 전용 ID와 중복·제어문자·10000cue/16MiB 가드를 유지한다.
- [x] SMI는 기존 native SAMI의 순서/밀리초 이벤트·clear/BR·텍스트 escaping 의미를 따른다. 겹침/역순은 SMI만 이유를 표시해 막고 자동 retime/reorder하지 않는다. 비유한·음수·역전/불완전 시각·빈 문구는 해당 필드 오류로 막는다. 파일 교체/잘못된 파일/늦은 읽기는 문구·시각·파일명 draft를 새 자료와 섞지 않는다. 별도 파일명은 안전하게 처리한다.
- [x] 실제 shell 진입 누락 RED→GREEN. 새 직접 File/serializer/native SAMI 의미 검사와 공유 accepted-copy/접근 경계 회귀15건, 새 직접/기존 accepted 사본의 오프라인 브라우저2건 통과. 실제 production CSS·설치 글꼴/기존 AuthGate/VideoWorkspace의 PC1440/390px에서 허용된102-byte fixture 선택→문구·양쪽 시각 편집→실제 SRT/SMI Blob 다운로드 bytes/파일명, 121cue·비영점 스크롤·값/버튼 hit·정상 글자 크기·읽기 race·오류·SMI overlap 차단을 확인했다. fixture는 불변, 다운로드 staging/사본은 Hermes scratch 내부에서만 사용 후 제거했다. 변경 파일 ESLint/Prettier·이번 delta TypeScript/Vite 정식 build(1752 modules) 통과. 실제 HTTPS 제품 수용은 부모 범위다.
- [ ] 영구 저장/재열기·accepted revision 발행·영상 재렌더는 이번 브라우저 사본 기능에 포함하지 않는다. 기존 결과/이력/custody/model pin을 수정하지 않고 새 API/DB/schema/권한/collector/tool/node를 만들지 않는다. 부모가 독립 검사·exact commit·기존 web-only 배포·실제 HTTPS 파일 선택/편집/다운로드·기존 Windows USER Git 정상 FF 게시를 이어 확인한다. writer는 운영·모델/GPU·commit/push/deploy에 접근하지 않는다.

### 2026-11-12 SMI/SAMI 직접 입력 — 같은 편집기의 소스 확장, 운영 미반영
- [x] clean36b94187의 `#/subtitles`/로그인 경계를 유지하고 같은 파일 선택에 `.smi/.sami`를 추가했다. 기존 SRT reader·literal ID/바이트 보존과 두 exporter는 유지하며, SMI는 UTF-8/BOM의 단일 트랙 SYNC/P·clear/BR·엔티티를 안전한 문자열 parser로 기존 cue 모델에 넣는다. 시간은 실제 다음 SYNC로 종료하며 clear와 다음 자막 사이의 공백을 보존한다.
- [x] 여러 언어/문단·빈 자료·잘못된/없는 마지막 종료·미지원 인코딩/태그는 파일 오류로 표시한다. HTML/CSS를 DOM에 넣거나 외부 리소스를 읽지 않고, 새 출력은 기존 plain SRT/escaped SMI exporter를 사용한다. 언어 선택/스타일 편집·원래 SMI HEAD/스타일의 완전 복원은 지원하지 않는다. 원래 File은 불변이며 SMI 사본은 표준 형식으로 재생성된다.
- [x] 실제 File 입력의 SMI 미지원 RED를 확인했다. SMI/기존 직접 SRT/두 exporter의 관련10건과 실제 Python SAMI producer의 문구/clear 간격 왕복 검사가 통과했다. 같은 실제 편집기·production CSS/설치 글꼴·native File·Blob의 오프라인 브라우저1건(PC1440/390px)에서 문구/시작/종료 편집·SRT/SMI 파일명/bytes·원래 File hash·선택 race·오류 후 stale 다운로드 차단을 확인했다. 변경 파일 lint/format과 SMI delta의 TypeScript/Vite build(1754 modules)가 통과했다. GB36b의 기존 실제 수용/배포 검사는 반복하지 않았다.
- [ ] 부모의 기존 HTTPS PC390 파일 선택/다운로드·검토·배포/정상 USER Git 게시 수용은 별도다. 서버 저장/재열기/렌더·새 작업/accepted 결과를 만들지 않고 원래 작업/키/모델/감사 이력을 보존한다. source writer는 운영·모델/provider/GPU·설치/네트워크·commit/push/deploy를 수행하지 않는다.

### 2026-11-12 독립 자막 수정본 저장·목록·재열기 — 소스 구현, 제품 수용 전

- [x] 기존 직접 입력 편집기에 `수정본 저장`과 `저장된 자막`을 연결했다. `/api/subtitle-copies` POST/GET 및 ID GET은 기존 session/CSRF/origin 경계를 사용하고 maintenance는 계속 차단한다. 새 API는 원본·job/review·accepted 결과를 갱신하지 않는다. 제목·입력 파일명·저장 시각·cue 수의 공유 목록과 같은 편집기의 상세 재열기를 제공한다.
- [x] 수정된 SRT는 16MiB/10000cue·literal ID/시각/문구를 서버 검증한 뒤 기존 CAS에 보관한다. 기록은 별도 `subtitle-copies/{id}.json`에 IfNoneMatch 불변 생성하고 SHA·canonical JSON과 CAS bytes를 재확인한다. S3 목록은 20개씩 해당 namespace만 조회하며 기존 owner-CAS는 서버 작성자 감사와 함께 보존한다. 새 table/GRANT/credential/플랫폼을 추가하지 않는다.
- [x] 첫 서버 수직 검사 11실패·1통과 RED에서 GREEN으로 수정했다. 실제 편집기의 제목/저장 동선 부재 RED도 확인했다. 서버/ASGI·local CAS·fakeS3 관련16건과 프론트 helper2건·production CSS의 오프라인 PC1440/390px 저장/전체 reload/재열기/SRT·SMI 실제 다운로드 브라우저1건이 통과했다. 쓰기 거절/재조회 실패는 성공을 표시하지 않고 같은 요청의 명시 재시도만 같은 ID를 사용한다. 합성 검사는 실제 S3 권한이나 설치 제품 수용이 아니다.
- [ ] 부모의 설치 후 원래 API 자격으로 실제 immutable PUT/GET·인증 PC/390 저장/목록/재열기·원본 불변 및 정상 USER Git 게시 수용은 별도다. ListBucket 확인만으로 PUT/GET 권한을 주장하지 않는다. 실제403은 그 저장을 차단하고 권한을 바꾸지 않는다. 기존 결과 revision 발행·영상 재렌더와 운영 접근·모델/provider/GPU 실행·commit/push/deploy는 수행하지 않는다.

### 2026-11-12 새 Start 대기열 pause·resume·시작 순서 — 소스 검사, 운영 수용 전

- [x] 기존 configured ContentStore/S3ContentStore에 독립 owner 정책 `start-queues/{owner}.json`의 bounded canonical JSON·SHA/ETag·IfNoneMatch/IfMatch/revision CAS를 연결했다. 1000개 이하 membership과 서버 actor를 사용하고 새 DB/table/GRANT/credential/config를 추가하지 않는다. S3 오류를 local cache로 대체하거나 paused=false/빈 상태로 꾸미지 않는다.
- [x] 유효한 새 첫 Start 승인에만 버전 있는 claim request digest와 membership을 결속했다. 정책 기록을 PG claim commit 전에 쓰고, 실제 owner/job/claim/generation이 일치하지 않는 orphan은 목록·예약에서 제외한다. 기존 nonce 재조회와 과거 absent-policy claim을 보존하며 초안·과거 admitted runless 작업을 자동 편입하지 않는다.
- [x] `Execution.claim_next`의 첫 예약을 owner queue lock → job lock → 최신 정책/모델 조건 → 기존 capacity/run/outbox 순서로 보호한다. pause는 검토 캡처·capacity 등록·첫 예약보다 앞에서 막는다. ANY run 이후 후속 단계는 pause/order로 막지 않으며, 자원이 없는 앞 작업의 준비와 다른 가능한 슬롯 사용을 보존한다. 순서는 첫 시작 우선순위다.
- [x] 실제 인증 GET/PATCH `/api/queue`와 기존 admit/run/controller·결과 수신, 기존 API lifespan wakeup에 연결했다. 별도 daemon이 떠 있다는 가정이나 UI의 자동 Run 반복에 의존하지 않는다. GET은 정책·metadata만 읽고 기존 전달 관측 패널을 유지한다. strict body/CSRF/origin/no-store/maintenance 경계를 유지한다.
- [x] 실제 renewal 실행 관리에 pause·resume·맨 앞으로/위로/아래로 이동을 연결했다. 409·응답 유실 뒤 GET으로 확인하고 PATCH를 자동 재전송하지 않는다. 조회 실패·이전 revision·미확인은 빈 대기열로 표시하지 않는다. PC1440/390px의 실제 React/production CSS 오프라인 응답 fixture와 source domain/route/첫 예약·저장 adapter 합성 검사를 수행했다. 자막 수정본8a의 기존 검사·다운로드·실제 저장 검증은 반복하지 않았다.
- [ ] 부모의 독립 원문 대조·코드 검토와 원래 principal의 실제 PG/S3·저장 권한·예약 직렬화·pause/resume/order·정상 자원 준비·PC/390px 제품 수용은 별도다. 합성 검사를 실제 admission 성공으로 부르지 않는다. 기존 #20/21/30/31/32/33·원본·키/모델/이력·응답 불명 시도는 운영에서 접근하거나 변경하지 않았다. 설치·운영·provider/GPU·commit/push/deploy는 부모 범위다.


### 2026-11-13 임의 음성 원본 → 전사만 준비 — 소스 완료, 운영 미검증

- [x] 기존 원본 완료 경로에 실제 WAV(PCM16)·MP3 분류와 검증된 음성 asset 참조를 연결했다. 실제 SHA·바이트·길이·형식·샘플레이트·채널과 custodian을 보존하고 음성의 영상 썸네일/미리보기 생성을 건너뛴다. 기존 업로드 취소·prefix·offset·최종 해시·멱등 경계를 유지한다.
- [x] 새 명시적 음성 입력 프로필과 저장된 실제 ASR 목표 선택을 공통 준비 경로에 연결했다. 실제 asset/workflow FK, source owner, 모델 primary/fallback·버전·옵션·호출 예산을 고정한다. 단일 전사 에이전트의 preprocess_audio → transcribe와 같은 producer의 audio/timeline만 사용한다. 기존 영상·완료 WAV 재사용과 과거 absent-profile 해석은 유지한다.
- [x] 실제 Create·_plan·preflight·claim·모델 역할 serializer를 fake DB/registry/queue와 임시 CAS로 검사했다. 원본 압축 입력에 한정된 검증과 후속 strict PCM/clock 검증을 분리했다. 합성 WAV/MP3의 로컬 probe·정규화는 수행했지만 제품/native/provider 작업은 실행하지 않았다.
- [x] 원본 파일 선택·상세·기존 공통 준비 화면·편집기 저장 payload를 연결했다. PC1440/390px의 실제 React/AuthGate/production CSS 오프라인 응답 fixture에서 이어보내기 요청 계약, 재열기, 모델/언어 선택, stale/403/불완전 입력, 명시적 합성 Create 응답 불명 후 자동 재전송 차단과 모바일 카드/도구 좌표를 검사했다.
- [x] 새 범위 backend 30건, frontend unit 3건 + offline browser 1건 통과. 변경 파일 lint/format, TypeScript, VITE_RENEWAL_BACKEND=1 빌드, Python compile-only와 CR-at-EOL diff 검사 통과. 기존 MT/SMI/GB/queue/persistence의 수용 검사·전체 suite는 반복하지 않았다.
- [ ] 부모의 독립 검토·기존 개발 패키징/설치와 실제 PC390 입력 준비 수용은 별도다. 실제 PG/S3 권한·음성 PUT·native 스케줄링/정규화·Start·ASR/provider·결과 다운로드는 검증하지 않았다. writer는 운영 접근·원본/작업/키/모델 변경·commit/push/deploy를 하지 않았다.


### 2026-11-13 M4A(AAC) 원본 → 기존 전사 준비 — 소스/로컬 fixture 검사

- [x] 기존 uploader에 M4A 선택을 추가하고 실제 format_name·M4A 브랜드·AAC stream을 검증해 canonical m4a/audio/mp4로 등록·재검증한다. 일반 video는 기존 영상 경로이며 ALAC/raw AAC/FLAC/불명 브랜드를 음성 M4A로 채택하지 않는다. 기존 정책·용량/길이/정규화 한도와 여섯 필드 metadata를 유지한다.
- [x] 실제 tiny synthetic AAC/M4A의 probe·업로드 완료·CAS와 source custody, 실제 Create→_plan→preprocess v5 정규화→같은 producer WAV/timeline의 ASR 명령·역할 envelope를 fake SQL/registry/queue와 임시 CAS로 확인했다. 선택 fixture의 모델/언어/옵션·호출 상한1을 보존했으며 모델은 호출하지 않았다.
- [x] M4A 전용 backend 21건 및 변경 uploader helper 1건 RED→GREEN, 변경 프론트 lint/format·TypeScript·renewal 빌드를 통과했다. 원래 음성34건/기존 MT·render·GB·SMI·queue 전체 suite와 완료된 WAV/MP3 운영 여정은 반복하지 않았다.
- [ ] 부모의 독립 검토·기존 개발 패키징/설치 후 실제 M4A 등록·입력 준비 확인은 별도다. Windows 합성 AAC 디코드는 설치 Linux 이미지의 codec/PG/S3/native/ASR/provider/다운로드 성공 증거가 아니다. writer는 실제 API·DB·S3·업로드·jobs/Start·provider/GPU·서비스·권한·Git ref/commit/push/deploy를 변경하지 않았다.
