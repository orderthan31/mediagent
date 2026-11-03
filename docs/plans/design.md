# 미디에이전트 디자인 기준

## 확정 추가 범위: 에이전트 전용 워크플로우와 실제 소스 계층

- 만들 것: 전사 → 한국어 번역 → 자막 영상 제작의 업무 에이전트만 저장/편집/실행 캔버스에 둔다. 분석·오디오 준비와 구간 처리는 전사 내부 도구, 자막 생성·번인·검사는 영상 제작 내부 도구다. 오케스트레이터는 에이전트 간 순서·배정·준비를, 에이전트는 자기 도구 선택·순서·결과 확인을 책임진다.
- 사용: 영상과 등록 모델을 고르고 시작한다. 에이전트 상세에서 하위 도구의 진행·출력·실제 콘솔을 본다. 오류는 붉은 노드/이유로, 다음 실행기 실제 준비는 연결선의 ‘다음 단계 준비 중’과 대상 노드의 ‘준비 중’으로 구분한다. 내부 도구 준비는 에이전트 내부 진행이다.
- 소스: 기존 모노레포 안에서 오케스트레이터 구현·업무 agents·tools/툴허브·runtime/컨트롤넷을 실제 이전한다. 기존 import/CLI의 필요한 경계는 구현 없는 호환 모듈로 유지하며 원본 구현을 복제하지 않는다. 패키지·Docker·실행 진입점과 전후 트리를 함께 검증한다.
- 확인 경계: 새 작업·30/31 재실행·실모델/provider·유료/GPU 호출·새 검증계 없이 기존 개발계 빌드/시작과 화면, 네트워크 없는 결정/상태 회귀를 검증한다. 과거 작업 snapshot·실행·결과·불명 원장은 그대로 보존하고 과거 화면의 집계 투영과 새 실제 에이전트 실행 계약을 구분한다.
- 외부 통신: 승인 1565553471640572038의 범위로 전사/번역 연결부만 기존 API 외부망에 연결했다. DNS·인증서 검증 TLS 1.3은 양쪽 성공, HTTP 요청 0, 기존 작업/실행/호출 원장 동일. 이는 전사 완주·품질 검증이 아니다.
- 미검증/미결정: 실영상 새 흐름 완주와 콜드부트 전환의 신규 실행 실증은 승인 범위 밖이다. 없는 과거 HTTP 상태·콘솔을 만들거나 불명 호출을 자동 재호출하지 않는다.


## 최신 정정: 콘솔 원문과 멈춘 작업 표시

로그 탭은 시작·종료 이벤트가 아니라 실행기·모델 연결부의 실제 stdout/stderr와 예외를 보여준다. 태스크별로 구분하고 인증정보를 가린 뒤 컨테이너 밖에 보존한다. 과거에 출력·저장하지 않은 로그는 없다고 표시하며 재실행으로 만들지 않는다. 완료·오류·대기 태스크 모두 출력/로그 탭을 유지한다. 확정 오류와 응답 불명 보류를 작업·태스크 화면에 구분해서 보여주되 원래 실행 기록과 재호출 방지는 보존한다. 시험 작업은 생성 근거로 현재 목록에서만 삭제하고 사용자 작업 20·21·30·31과 불명·감사·결과 기록은 남긴다. 새 시험 작업이나 모델 호출은 하지 않는다.

## 태스크 상세의 출력과 로그

태스크를 클릭하면 기본으로 출력 탭을 연다. 기존 결과와 다운로드를 유지한다. 로그 탭에서는 선택한 태스크의 처리 시각·모델 요청·오류를 확인한다. 태스크를 바꾸면 이전 기록을 비우고 새 기록을 읽는다. 기록이나 시각이 없으면 없다고 표시하며, 인증정보나 원문 응답을 보여주지 않는다. PC와 휴대폰에서 탭을 전환하고 긴 내용을 스크롤할 수 있어야 한다.

## 무엇을 보여주는가

화면은 사용자가 선택하고, 진행을 확인하고, 결과를 받고, 오류를 해결하는 데 필요한 내용을 보여준다. 작업 지시나 개발 완료 보고를 화면 설명으로 옮기지 않는다.

## 사용자는 어떻게 확인하는가

전사·번역 에이전트의 목록·상세에서는 맡은 일, 현재 상태, 사용 가능한 도구와 작업 기록을 확인한다. 진행 표시는 '전사 중', '번역 중', '완료'처럼 업무를 기준으로 쓴다. 실제 응답을 확인하지 못했으면 정상이나 처리 중으로 추측하지 않고 '확인 필요'로 표시한다.

## 실제로 확인한 범위

기존 개발 환경에서 전사·번역 목록과 상세, 완료 작업으로 이동하는 링크를 PC와 좁은 화면에서 확인했다. 시험 응답으로 만든 결과는 실제 모델 결과와 혼동하지 않도록 표시한다.

## 남은 것과 화면에 넣지 않는 것

도구의 워크플로우 노출과 추가 메뉴 개편은 결정하지 않았다. 설명을 위해 새 옵션이나 버튼을 만들지 않는다. 코드 이름·버전·긴 식별자·개발 검증 문구는 문서의 기술 근거에 두고, 사용자에게 필요한 비용·오류 정보는 숨기지 않는다.

## 목적

디자인 철학과 시각 표현·UI/UX의 판단 기준을 관리한다.

## 현재 상태

한결디자인 consumer 소스와 Indigo 제품 테마를 사용한다. 화면 보정과 실제 기능 수용은 구분한다.

## 주요 내용

- 27인치 FHD/1920×1080 데스크톱의 정보 밀도를 기본으로 하고 폰·폴드급 좁은/중간 화면에서 재배치한다.
- 진한 테두리·카드 중첩보다 조용한 회색 구분선, 정렬, 간격과 타이포 위계를 우선한다. 공유 디자인 시스템 정본이 아니라 제품 토큰에서 밀도를 조정한다.
- GNB는 탐색 맥락과 페이지별 검색/주요 행동, LNB는 작업·원본·워크플로우·에이전트·서빙·시스템·계정 관리에 사용한다. 생성/상세/편집은 하위 동선이다.
- 일반 사용자에게는 원본·작업 동선을 제공하고 나머지 관리 메뉴와 화면은 관리자 전용으로 제한한다. 관리자 화면 URL 직접 접근도 제한하며 메뉴 숨김만을 권한 구현으로 취급하지 않는다.
- 목록은 공통 divider 행과 페이지 이동을 사용한다. 작업 목록은 티켓/원본/워크플로우/상태/일시를 한 줄로 유지하고 제어·오류 본문은 상세에 둔다.
- 노드 설정은 관리자의 workflow 작성 시점, 검수 자료와 결과는 작업 시점에 제공한다. 원본 상세는 읽기 전용으로 유지한다. 관리자 전용 에이전트 상세는 처리 정보와 활성화·비활성화·실행 인스턴스 수의 운영 관리를 제공하는 방향으로 확장하며, 현재 구현은 정보 조회만 지원한다.
- 반복 소개문·내부 개발 설명을 기본 화면에 붙이지 않는다. 입력 제약·실패·과금/실행 동의 등 필요한 행동 맥락은 유지한다.
- 선택 노드와 폼은 실제 휠·터치 스크롤, 긴 텍스트, 하단 행동과 겹침을 확인한다. 에뮬레이션을 실기기 수용으로 보고하지 않는다.

## 미확정 사항

제품 CI는 확정되지 않았다. 임시 M 로고 제거를 유지하며 임의 대체 로고를 만들지 않는다.

## 관련 문서

- [제품 기획](specs.md)
- [구현 태스크](tasks.md)

## 이번 우선 제품 흐름 — 기존 전체 작업과 연결 편집

- 레거시 비교 기준은 실제 원격/로컬 `master=57d34e9995edf5e322dfa26acdd899513f4038d5`. `main`은 존재하지 않는다. 구현 기준은 `renewal=214f1fe313772e10117dab73725a09dcc9886cdb`이며 구형 Worker를 재기동하거나 모놀리스를 복사하지 않는다.
- 얼굴합성을 제외한 음성추출 → 선택 전처리/VAD·원본 시각 복원 → Gemini 포함 등록모델 전사 → 번역 → 원문/번역 자막 → 선택 검수 → 인코딩을 실제 편집·저장 가능한 워크플로우로 제공한다. 정의/모델 선택만으로 전체 실행 완료를 주장하지 않는다.
- 전사 호환은 공식 음성입력/구조화 출력 근거, 실제 목록, WAV/숫자 타임스탬프 어댑터 계약의 교집합으로 판단한다. 기존 등록/과거 모델 개정·키는 보존하고 전사 프로필은 명시 선택한 새 등록/개정으로만 연결한다. 기존 60초/2MiB 단일 호출을 긴 영상 완료로 세지 않는다.
- 캔버스 동작 참고는 n8n `2.43.5`의 공식 고정 소스 `d811f5e87dfc164999f34d75b17017876d41a54a`이다. Canvas/CanvasControlButtons/CanvasEdge/CanvasEdgeToolbar를 읽어 BottomLeft 공통 도구와 40px 상호작용 폭을 대조했다. 인증된 n8n 캔버스 조작을 수행했다는 뜻이 아니며 자동화/credential/실행을 수정하지 않는다.
- 현재 React 공용 캔버스와 라이브러리를 유지한다. 정렬·선 정리·전체보기·확대/축소·되돌리기는 캔버스 안 하단 고정, 화면 크기 기준 클릭 영역으로 제공한다. Vue 앱/스타일/상표를 통째로 복사하지 않는다.
- 선택한 선은 명확히 강조한다. 선 가까운 지속 도구모음에서 연결해제, 입력/출력 바꾸기, 호환 포트 목록/직접 탭, 취소를 제공한다. 재연결은 이 제품 요구이며 n8n에서 모두 직접 확인했다는 주장이 아니다.
- 재연결 완료 전 원선을 보존한다. 자료 유형/중복 입력/불법 순환을 거부하고 명시 Loop.next 계약을 보존한다. Esc·취소와 연결 되돌리기는 노드 옵션/모델핀을 과거 상태로 덮지 않는다. 텍스트/선택 입력 중 삭제키는 선을 지우지 않는다.
- 편집/이동/연결 제스처를 분리하고 읽기전용 상세는 원 정의/작업을 수정하지 않는다. PC 및 실제 390px에서 잘못된 선 선택 → 해제/다른 포트 연결 → 취소/되돌리기 → 실제 저장/재열기와 하단 도구 접근성을 확인한다.
- 실제 유료 호출은 모델·입력길이·호출상한·예상비용을 따로 승인한다. 승인 대기는 해당 호출에 한정하며 나머지 구현/검증을 멈추지 않는다.


## 긴 전체작업 실행의 판정 경계

- 새 전체작업 초안은 기본 검수를 보존하며 no-review는 명시 선택이다. SRT/SMI는 별도 정상 출력으로 제공하고 SMI를 SRT 이름으로 내려주거나 HTML로 실행하지 않는다. 기존 정의·모델·연결·키/티켓 개정은 자동 변경하지 않는다.
- 단일 공급자 호출의 60초/2MiB와 번역 100구간/16000 UTF-8 bytes는 유지한다. 분할별 원본/입력 SHA, PCM-frame 또는 자막 index, 원 clock SHA, 언어, 후보순서/모델·연결개정을 고정하고 호출 전 SQL intent+단조 예산을 commit한다. 완료 CAS 참조만 재사용하고 응답/commit 불명은 held·자동 재호출/후보 전환을 막는다.
- provider 응답 수신과 정상 구간 완료를 구분한다. 결과 CAS 검증과 완료 참조 commit 전에는 response_received이며 취소 뒤 다음 구간/후보/번역은 시작하지 않는다. 자막 ID/순서/시각과 정확 프레임 coverage를 유지하고 누락·중복·원길이 밖 시각을 성공으로 숨기지 않는다.
- 전체 판정은 저장 정의→정식 티켓/독립 실행 경로→분할 전사→번역→자막→영상 결과다. 121초·독립 프로세스/실 PG/TLS MQ/S3·통제 응답의 기본 경로 실증은 공급자 품질, 실제 운영, 전체 6시간/4GiB 처리 또는 선택 전처리/VAD/검수·다국어 동등 수용과 구분한다.
- 기본 경로 소스 e25831b36e와 CPU 무음 전처리 9392b123은 PM 수용/App publish 완료이고 운영은 미반영이다. 후속 silence_pack_v3는 새 명시 profile/revision3의 CPU 전처리이며 master의 10/5/3초 무음 임계·-45dB·0.2초 padding과 정확 프레임 복사/기존 원시각 복원을 사용한다. legacy_v1/off·과거 티켓은 자동 교체하지 않는다. NVIDIA VAD, 보호/보컬 구간·긴 clock·검수/다국어는 별도 잔여다.
- NVIDIA 후속 nvidia_regions_v4는 CPU silence profile의 별칭이 아니다. regions 입력은 원본 audio SHA/PCM frame 수에 묶인 CAS 결정이며, master와 같은 보호 확장·전체 veto·원본좌표 제거 뒤 NVIDIA 확률에서 재산출한 유지구간을 마지막에 교차한다. CUDA 요청/실제 device 표기·model SHA·duration·확률/구간 일치를 검증한다. 입력 결정 적용과 자동 탐지/독립 재확인, 통제 응답과 실제 GPU inference를 구분한다.
- NVIDIA wrapper를 registered ASR에 넘길 때 audio SHA/명시 profile/source frames/구간 범위를 먼저 검증한다. old list clock/전역 300초 한도는 유지한다. 통제된 wrapper 소비의 단일·분할 ASR/번역 검증은 실제 GPU→ASR 전체 여정의 증거가 아니다. legacy packed 교차문장 분리/trace는 아직 잔여다.
- fd5b455b의 NVIDIA 명시 계약/구간 적용은 소스 수용·App publish 완료이고 GPU 실실행/운영은 미반영이다. 후속 audio_regions_v1 검수는 원본 audio/frame을 읽기 고정하고 보호/제거 결정만 수정·확정한다. 확정 시 CAS를 만들되 실행하지 않으며 새 동의 후 regions_pack_v4/revision4 CPU 또는 명시 NVIDIA 입력으로 전달한다. 일반 검수와 기존 프로필은 그대로 유지한다.
- 제품 검수 배열의 표시 순서는 JSONB 속성순서에 기대지 않는다. 새 음성 구간 폼에만 시작→끝/보호→제거→확인 순서를 명시하고, 그 외 폼의 기본 배열/표시 한도는 유지한다. 메타데이터 source/player는 읽기 전용이며 검수 저장 실패 시 편집을 보존한다.
- 자동 보컬 도메인 프로토콜과 실제 등록 모델 실행을 구분한다. 전자는 원본 frame 문맥/의미 보존·독립 확인·veto/취소·호출 수 제약을 통제 응답으로 검증하지만 기본 모델·HTTP·키·제품 활성화 경로가 없다. 목적 호환 proof/영속 intent/unknown·비용 승인이 연결되기 전 실제 호출할 수 있는 runtime로 수용하지 않는다.
- 6d811597 수동 검수/결정 소비는 소스 수용·App publish 완료이며 운영 미반영이다. 다음 packed_projection_v2는 새 명시 전사 옵션에만 적용한다. 단어별 timing이 없으므로 제거 gap마다 문장 전체를 반복하는 master 정책을 명시하고, 원문/원 literal ID/packed 시각/원본 pieces/child ID 및 sub-ms drop을 trace로 남긴다. 기본 legacy envelope 경로와 과거 티켓을 바꾸지 않는다.
- projection은 검증된 PCM frame clock을 모델 HTTP 전에 검사하고, parsed packed transcript를 CAS에 보존한다. 후처리 실패를 provider 실패로 재시도/fallback하지 않으며, 성공 trace를 transcript/audio/timeline SHA에 묶는다. 새 trace는 metadata 산출물로 내려받을 수 있지만 실제 단어별 정렬 품질이나 운영 실행 증거는 아니다. 긴 source/packed clock 및 새 역할별 예산은 다음 명시 계약으로만 확장한다.
- 03ace76d의 projection-only는 소스 수용/App publish 완료이고 운영 미반영이다. 후속 audio_long_v5는 별도의 snapshot 정책과 역할 command 예산을 고정한다. 원본 보관4GiB와 오디오 pipeline 영상 입력256MiB는 다른 경계다. 파생 PCM은1GiB, source/packed는 각각6h의 실제16k frame 상한, JSON/trace/각 자막은16MiB로 제한한다. CPU native-process/command/lease 및 모델의 선택 call-derived deadline을 각각 검사한다. 검수의 사람 대기는 worker lease로 포장하지 않는다.
- 새 producer는 version5 clock의 source/audio SHA·source/packed frame 수·정책 SHA를 저장한다. 새 소비는 명시 media budget/packed_projection_v5와 정확한 동결 역할 예산을 요구한다. 기존 reader는 이를 받아들이지 않으며 구신 consumer 혼합/운영은 별도 게이트다. 실제 frame 기준 최소 ASR call 수와 canonical100/16KB 번역 분할 최소 수를 해당 HTTP 전에 확인하여 불가능한 cap으로 일부 호출만 과금하는 경로를 막는다.
- 321초/6 ASR chunk/2 translation chunk의 통제 실행은 6h 완주/공급자 품질/독립 MQ·S3·GPU·운영 증거가 아니다. 기존 analyze/encode/validate 선택과 그 구형 예산은 유지하고, 큰 원본·긴 encode/GPU 예산은 다음 명시 계약/승인 대상으로 남긴다. source/packed frame뿐 아니라 실제 serialized output/trace bytes도 별도로 제한한다.
- 기존 audio-clock 300초/CPU 역할 한도를 전역 확장하지 않는다. 필요한 긴 전처리/clock/역할별 예산은 별도 명시 버전과 새 티켓에 결속한다. 유료 호출만 모델·길이·호출/비용 상한 승인을 분리하고 나머지 비유료 구현을 계속한다.


#### Model-free preserved transcript reprojection
The original failed transcription is not a resumable success. Require its completed delivery envelope and exact committed inbox hash, matching sanitized held-transcript metadata and no uncertain chunk attempt before offering recovery. Additive023 owns immutable preview/context and one-shot admission/outcome rows only; original jobs/runs/model budgets remain unchanged. Pin the original saved transcript/audio/clock refs and policy, actual verified frames/bytes and the current projector code SHA. Explicitly preview and acknowledge before storing a separate transcript/trace artifact; do not call registry/model transports, create a child job or dispatch descendants. A response/commit-unknown source remains blocked, and an uncertain recovery admission is not automatically replayed. Serving this feature needs its own migration/rollout approval; source acceptance of8167ca87 did not authorize that activation.


### 모델 선택·요청 옵션 전달
- 워크플로우의 모델 ID/revision을 그대로 저장·재열기한다. 선택한 노드에서 요청 옵션 JSON을 설정하며 키·공급자 주소·모델·transport·재시도/fallback을 옵션으로 덮어쓸 수 없다.
- 새 작업 생성은 선택한 버전과 옵션을 snapshot에 고정하고 모델 툴의 실제 SDK 인자에 전달한다. SDK가 선택 모델이나 지원되지 않는 설정을 바꾸거나 버리는 경우의 방어 검증은 운영 승격 전 필수다.
- 실제 시각이 없는 전사문, 비정상 JSON·비완료 응답, 시각 겹침은 정상 자막 입력으로 포장하지 않는다. 원래 상태/원장과 결과 불명 보류·취소·키 redaction 경계를 유지한다.
