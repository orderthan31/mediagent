# 리뉴얼 실행·저장 계약

## 목적

격리 CPU 경로의 실제 책임·재현 진입점과 운영 전환 경계를 관리한다.

## 현재 상태

### 공통 캔버스 배치·연결선·전체 보기

- WorkflowCanvas를 그대로 공유하는 편집/renewal 실행 상세에 자동 정렬·연결선 정리·전체 보기와 배치 되돌리기/초기화 조작을 노출한다. 노드 폭210은 유지하고 제목/포트를 줄바꿈한다. ResizeObserver/실제 DOM 높이·포트 중심을 사용하여 긴 이름이나 여러 줄 포트도 경로와 일치시킨다. 출력 포트 높이를 고려한 위상 계층 정렬로 불필요한 분기 교차를 줄이고, 노드 장애물을 피하는 직각 경로와 타 연결과의 교차/중첩 비용을 적용한다. 같은 합류 노드의 후속 접근은 이전 선보다 안쪽으로 결속해 인접 입력 직전의 교차 결함을 RED→GREEN으로 보정했다.
- 편집은 기존 definition의 노드 position만 바꾸고 기존 개정 충돌 검사(CAS) 저장/재조회 계약을 사용한다. 되돌리기는 최대20회 위치 이력이며 현재 옵션·기본 모델/폴백 고정값·포트/연결을 되돌리지 않는다. 읽기 전용은 definition id/revision에 묶인 local view 위치만 바꾸고 초기화로 snapshot 배치를 복원한다. job/snapshot PUT/POST나 실행 동작을 추가하지 않는다. 연결선 경로는 표시 계산이므로 별도 경로 metadata/실행 계약을 저장하지 않으며 재조회에서도 저장된 위치/포트로 정리해 그린다.
- 전체 보기는 실제 노드와 정리된 선의 경계를 모두 포함하고 기존 확대·이동을 유지한다. 작은 화면에서는 개요를 먼저 보고 확대/이동해 상세를 읽는다. 편집 전용 높이 덮어쓰기를 제거해 새 도구 모음 뒤에도 PC/390px 캔버스가 화면 안에 들어온다. 정렬은 기존 x0..4000/y0..3000 상한을 지키며 100노드의 장축은 유한한 묶음 배치를 사용한다. 크기/탐색 복잡도 초과는 안내하고 정상 정리 성공으로 표시하지 않으며 연결/옵션을 잘라내지 않는다.
- 검증은 기존 API 이미지+clean source RO/renewal production build/별도 PG의 실제 정상 인증·정의 저장/재조회와 직접 seed한 불변 합성 draft를 사용했다. catalog의 긴 표시 이름과 TEST thumbnail만 명시 브라우저 응답 fixture다. 영상/공급자/모델/MQ/저장소 처리는 없으며 실제 운영 티켓 실행 수용이 아니다. PC1440/390px에서 되돌리기·저장 위치 재조회, 옵션/model_ref/fallback_refs/edge 불변, 텍스트 조각 범위와 노드/선 겹침, 포트 중심의 끝점, 전체 보기 경계와 read-only 수정 HTTP0/DB snapshot SHA·revision 동일을 확인했다. 같은 출력 분기의 공통 접점은 허용하고 다른 선 교차/중첩은0이다. 모바일 확대·키보드 이동과 배치 초기화도 확인했다.
- 최종 Node 기하5/production browser2·타입/build·변경 frontend lint/format 통과다. 실제 관측한 합류 교차와 모바일 높이 덮어쓰기만 좁게 보정했고 기존 Radix/Node Playwright 경고는 남긴다. 임시 API/PG는 각 SIGTERM143/0으로 종료·제거하고 preview port/임시망을 닫았다. 기존24 container의 설정/ID/mount/시작/실행/종료 상태·WIP21을 보존했다. 저장 묶음3aaec048은 PM 수용·App push 완료로 닫았으며 이번 캔버스 소스는 PM 검토 대기다. 운영 사이트/서비스/DB/키·012/019·원본17개·#5/DLQ·정상 접수/배포는 바꾸지 않았다.

### 새 티켓의 산출물 manifest·실제 저장 경로

- Execution.create는 snapshot.artifact_layout1을 고정한다. 이전 snapshot/원본/owner-CAS는 갱신하거나 옮기지 않는다. 새로운 구조는 기존 run result JSON receipt를 사용하며 새 migration/GRANT/키 저장소를 만들지 않는다. CPU/등록 모델은 기존 accept의 정확한 요청·세대·claim/lease·취소 검사 및 출력 검증 뒤 같은 결속을 사용하고, 제어/검수 완료·완료 receipt 재사용도 동일 저장 모듈을 거친다.
- 실행 계정 namespace 아래 기존 `blobs/<sha256>` CAS와 함께 `tickets/<job-id>/nodes/<sha256(node-id)>/attempts/<node-run-id>/outputs/<port>/<content-sha>`가 실제 바이트를 가리킨다. 준비된 WebM은 같은 경로의 previews에 결속한다. node_run_id는 wire command의 attempt_id이며 시도 번호/generation/실제 node-id/port와 원 CAS 참조는 manifest에 별도로 남긴다. 후속 연결이 있는 포트는 intermediate, 없는 포트는 final이다.
- local ContentStore는 검증된 CAS에서 동일 volume의 불변 hardlink를 발행하여 바이트를 복제하지 않는다. 경로/sha/크기/모든 부모 symlink를 확인하고 기존 파일은 덮어쓰지 않는다. hardlink가 불가능하면 채택이 실패하며 파일 복사로 몰래 바꾸지 않는다. S3ContentStore는 기존 CAS를 보존하면서 명시 prefix/owner/ticket object에 실제 바이트를 IfNoneMatch로 생성·재조회 검증한다. 이는 S3의 무복제 보장이 아니며 추가 object 바이트가 생길 수 있다. 캐시는 계속 hash-CAS로 공유한다.
- 매 채택 후 전체 완료 산출물 manifest를 `tickets/<job-id>/manifests/<manifest-sha>.json`에 불변 저장한다. node_run result.ticket_artifacts는 해당 포트 저장 결속과 manifest sequence/ref/count를 가진다. 최신 완료 receipt의 SQL commit이 정본 pointer다. 파일 쓰기 후 SQL 미채택/저장 실패로 남은 파일은 정상 산출물이 아니며 자동 승격/재실행/정리하지 않는다. 모든 manifest/파일 download는 완료 결과와의 결속·바이트/SHA를 확인한다.
- 인증된 기존 공용 읽기로 `GET /api/renewal/jobs/<job-id>/manifest`와 download=true를 제공한다. 기존 artifact download URL은 유지하되 새 작업은 티켓 경로의 실제 바이트를 읽는다. 예전 작업은 기존 CAS에서 읽고 manifest는 읽기 전용 projection으로 반환하며 새 파일을 만들지 않는다. 채택 전/격리만 있는 새 작업도 빈 projection이며 정상 파일 link를 만들지 않는다. 업로더/실행자 표시와 credential/admin/CSRF 경계는 바꾸지 않는다. 기본 유지보수 정책에서 새 manifest route도 업무 경로로 계속 차단된다.
- 실제 별도 PG/local CAS와 짧은 합성 입력으로 CPU 음성 추출/전처리·등록 Gemini adapter MockTransport 결과를 공통 accept에 통과시켰다. 두 티켓의 manifest·artifact 행·실제 경로가 분리되고 재조회·다운로드 바이트/SHA가 일치한다. 다른 사용자의 업로드를 사용한 실행 계정 분리/공용 읽기, 개인 설정403/익명401, legacy 무변경 읽기, 취소 후 quarantine 제외와 manifest 쓰기 실패 뒤 파일 미채택을 확인했다. 선택/검수 및 복구 재사용은 합성 자막만으로 저장 결속을 확인했다.
- 통과형 select/review 영상은 새 정상 티켓 결속을 검사한 뒤 기존 검증된 source WebM을 호환 읽기로 재사용할 수 있다. 전용 ticket preview가 없는 경우를 RED→GREEN으로 보정했고, manifest/hash 실패를 우회하거나 raw MP4로 대체하지 않는다. 원본/미리보기를 새로 변환하거나 옮기지 않는다.
- 최종 Python12(신규11+기존 저장 guard1)·실제 production UI PC1440/390px2 통과, 타입/build·변경 TSX/검사 ESLint/format 통과다. scoped Ruff는 신규0·부모에도 있는 API F4011을 보존했다. 기존 Starlette/httpx·Radix bundle·Node/Playwright 경고는 남긴다. S3는 network-none protocol double의 byte/object-key/reopen 확인이며 실제 S3/MinIO·브로커·공급자 품질/인증 수용이 아니다.
- 검증은 기존 API 이미지+clean source RO 및 별도 PG/CAS/compiled web의 격리 설치다. 초기 internal-only Docker망의 preview port 비공개와 시험 node label 착오, sticky header 아래 조기 capture는 fixture 문제로 분리했다. disposable API만 loopback publish/bridge 연결하고 최종 source를 새 API에 적재해 확인했으며 운영망·웹·DB·키는 바꾸지 않았다. 전사/영상/MQ 전체 여정 반복·운영012/019·원본17개 이관·#5/DLQ 복구·접수 재개/배포는 없다. 산출물 저장3aaec048e7bd64215797cc702711b82acfb63b07은 PM 수용·App push와 Windows 원격 SHA 일치를 확인하여 종료했다. 운영 배포는 아니다.

### 접속 화면의 유지보수·로그인·통신 오류 구분

- VideoWorkspace의 capabilities 요청은 HTTP503과 ApiError.message의 정확한 `maintenance_admission_closed`가 함께 맞을 때만 **유지보수 중 · 작업 이용 제한**으로 안내한다. 다른503/네트워크 실패/HTML 응답/다른 상태 코드는 **작업 공간 응답 확인 불가**이며 DB 연결 상태는 미확인이라고 표시한다. capabilities가 작업 기능을 광고하지 않아도 DB 미연결로 추정하지 않는다.
- 401의 기존 authenticatedFetch→expired→AuthGate 재로그인 경로는 그대로다. 캐시된 CSRF token이 없어 expired 이벤트를 내지 않는401도 **로그인 필요**로 구분한다. 인증/CSRF·서버의 유지보수/관리자 allowlist·업무 admission을 바꾸거나 진단 endpoint를 만들지 않는다.
- clean source의 renewal production build와 명시적인 브라우저 응답 fixture로 PC1440/390px의 상태 구분16개·기존 auth-session 단위3개를 확인했다. 정상 계정을 생성/변경하거나 운영 로그인을 우회한 것이 아니라 UI 응답 계약 fixture다. 실제 DB/관리자 서버 응답·운영 가용성 검증으로 확대하지 않는다. 타입/build·변경 frontend lint/format 통과, 기존 Radix bundle 경고와 Node Playwright deprecation 경고는 남는다.
- 전사/영상/MQ 전체 시험은 반복하지 않았고 운영 서비스/DB/키·정상 접수·012/019·대상/원본/#5/DLQ는 변경하지 않았다. 화면 보정839f65eaa32b6a322412db6b7b73300746c4c4e7은 PM 수용·App push 완료와 Windows 원격 일치를 확인하여 종료했다. 접속 사이트에 설치한 상태는 아니다.

### 등록 모델 API 전사의 개발 계약

- **수용 상태:** `75793b1ae81b165f4492cdc9767f41b852747e8d`는 PM 수용·App push 완료이며 Windows의 원격 renewal SHA도 일치한다. PM은 제출 PG/브라우저 증적 검토와 별도 합성 MockTransport adapter 검사를 구분했다. 전사 묶음은 종료하며 운영 설치·실제 공급자 인증/인식 품질은 미확인이다.
- 전사 규격은 model_profile.supports_transcription으로 텍스트 번역과 분리한다. audio 입력/text 출력/speech_recognition 선언이 필요하다. Gemini는 네이티브 음성 포함 generateContent와 구조화된 start/end 숫자 초·text 응답, OpenAI/호환은 whisper-1의 multipart `/audio/transcriptions`/verbose_json/segment timestamps만 지원한다. 일반 gpt-4o-transcribe JSON/텍스트 및 Anthropic/TTS는 이 시간 구간 계약 미지원이다. 선언/규격 지원은 실제 공급자 가용성·인증·정확도 증명이 아니다.
- 원본을 기존 Intake로 검증하고 CPU extract_audio/preprocess_audio off 결과의 PCM16/mono/16kHz WAV를 보낸다. 실제 WAV bytes/duration/hash와 timeline SHA를 결과에 보존한다. 최대60초/2MiB·100구간/16KB이며 장시간 분할은 없다. 제공된 시각을 parse_segments와 음성 길이로 확인하고 기존 audio_clock에 따라 원본 시각으로 대응한다. 시각 누락/문자열 시각·범위 초과·형식 오류를 임의 시각/성공으로 보완하지 않는다. 범위 밖 음성/clock은 HTTP 전 실패 receipt로 정리한다.
- 기존 TranslationRuntime의 순서 후보 runner를 공통 `_run`으로 추출해 재사용한다. TranscriptionRuntime는 사용 가능성·오디오 adapter·timed decode만 선택한다. 후보는 기본1+선택3/각1회, HTTP 전 started intent 영속·정확한 delivery 재실행 차단/사용 불가·429·5xx·형식 오류만 다음 후보/거부·불명·취소 중단을 유지한다. model/connection revision과 원문 언어는 snapshot과 command에 고정하고 CredentialStore.model/resolve를 일시 재사용한다. 원격 API 모델 이름 whisper-1이지 로컬 Whisper 실행이 아니다.
- 기존 Execution/consent/claim/결과 채택/CAS 및 공용 DTO에 transcription 기록만 추가한다. 성공 전사 CAS가 번역 입력과 정확히 같고 source clock을 보존한다. 취소 후 뒤 전사 후보/번역 신규 HTTP가 없으며 반환된 결과는 기존 quarantine에 남고 정상 산출물로 채택하지 않는다. 이미 전송한 외부 HTTP 자체의 공급자 측 중단을 보장하지 않는다.
- create_app의 transcription_runtime는 같은 credential store/content store/명시 local delivery와 승인 origin을 요구하며 maintenance/broker_factory와 함께 활성화하지 못한다. controlled_http는127.0.0.1만, external은 기존 후보 전체 비용 동의→plan/claim→동결 paid_authorized를 요구한다. 기본 네트워크 transport는 없고 운영 bootstrap/브로커 전달·egress 설치는 하지 않았다.
- 검증 입력은 Windows System.Speech로 오프라인 생성한4.755초 합성 음성이다. 실제 CPU 음성 추출/별도 PG·CAS/실제 loopback HTTP에서 Gemini 단독 성공·Gemini실패→OpenAI성공·전부 실패·시간 누락 거부·진행 중 취소/후속 번역0을 확인했다. 발급 뒤 head/key 교체에도 원 model/connection/key revision 요청을 사용하고 HTTP decode audio SHA와 CAS가 같다. 응답은 통제 fixture여서 실제 인식/번역 품질 검증이 아니다.
- 최종 관련 Python16 pass(신규ASR9+공통 runner/Gemini guard7), 실제 production frontend→정상 auth→모델/폴백/언어 저장→티켓→전사→번역/다운로드 및 화면 취소2 pass, PC390px를 확인했다. Node53/타입·build·format/변경 frontend lint는 통과, scoped Ruff는 신규0·기존 API F4011이다. 기존 전체 영상/MQ/UI 수용 여정을 재실행하지 않았다. 초기 option disabled 판정은 DOM disabled 속성으로 분리해 fixture를 보정했고 실제 잘못 허용되던 UI RED와 구분했다.
- 기존 API 이미지에 clean source RO/PYTHONPATH와 production frontend를 연결한 격리 앱이며 새 wheel 설치/운영 배포가 아니다. 임시 API/PG만 정상 exit0/삭제·UI port 폐쇄, 기존24개 container 설정/시작/실행 상태와 WIP21 hash를 보존했다. 운영 DB/키·유지보수/중지 상태·012/019·대상/원본/#5/DLQ는 변경하지 않았다.

### 등록 모델 번역·선택형 폴백의 개발 계약

- **Gemini 응답 보정:** 명시 promptFeedback.blockReason 차단은 candidates 접근 전에 request_rejected로 반환하여 폴백하지 않는다. STOP 응답의 Part는 최종 text만 결합하며 thought=true는 제외하고 thoughtSignature/partMetadata 등 문서화된 메타데이터는 텍스트로 복사하지 않는다. 도구/미디어 union 및 혼합된 data Part도 채택하지 않는다. 최종 텍스트 없음·자막 배열 형식 오류는 기존 invalid_response다. 별도 network-none MockTransport fixture5개로 차단→후속 호출0, 서명 포함 최종문 채택, 생각/서명/도구/미디어 미채택과 두 거부 경계를 확인했다. 기존33/브라우저2 등 수용 증적을 반복하지 않았고 운영 변경/공급자 호출은 없다. translation.py의 끝 빈 줄만 함께 정리했다.

- `TranslationRuntime`는 기존 CredentialStore의 불변 model/connection 개정과 일시적 키 resolve를 재사용한다. Gemini는 `/models/{model}:generateContent`와 header-only `x-goog-api-key`, OpenAI 계열은 기존 `/chat/completions` adapter다. Anthropic은 실행 미지원으로 제공한다. 저장/실행 가능 표시는 실제 인증/품질 성공이 아니다.
- `translate.model_ref`와 선택 `fallback_refs`(고유 모델 최대3개)를 기존 정의에 저장한다. 원문/대상 언어·모델/연결 개정·순서를 기존 job snapshot과 exact command hash에 고정한다. 뒤에 model head/connection key를 바꿔도 티켓을 retarget하지 않는다. 기존 로컬 engine 경로를 등록 모델 대신 몰래 선택하지 않는다.
- 후보 dispatch마다 owner/활성/불변 내용/능력/키/승인 origin을 재확인한다. 후보 시작 intent는 기존 agent_deliveries의 started 행에 별도 transaction으로 HTTP 전에 commit한다. 전달 불명은 자동 재실행하지 않으며 기존 exact-delivery fence/취소·세대·claim·lease/늦은 결과 격리를 유지한다. 성공/실패와 취소의 후보 기록은 공용 DTO에서도 키/endpoint 없이 조회한다.
- 사용 불가·429·5xx·잘못된 완성 응답만 다음 후보로 간다. 인증/요청 거부·HTTP 전달 결과 불명·취소는 중단하고 같은 후보를 자동 재시도하지 않는다. 최대4개/각1회다. HTTP 진행 중 취소 버튼은 별도 요청으로 동작하고 반환된 결과는 정상 채택하지 않는다. 이미 보낸 HTTP 자체가 provider 쪽에서 중단됐다는 보장은 아니다.
- 기존 video 입력 DAG 외에 `{transcript: transcript}` 정의는 기존 원본을 출처로 선택하고 입력한 자막 JSON을 CAS/snapshot에 고정한다. 자막100개/16KB 이내, 시각/화자 보존·같은 개수/순서의 텍스트 응답만 채택한다. 이 제한을 넘어서는 분할·장문 최적화나 전사는 이번 범위가 아니다.
- API 생성 시 명시 `translation_runtime`/동일 credential store/기존 content store/local execution이 필요하다. 기본 transport는 없고 maintenance와 broker_factory 병용은 거부한다. `controlled_http`는 승인 origin이127.0.0.1만 가능하다. `external`은 생성 시 비용 동의→동의된 plan/claim→각 후보의 동결된 paid_authorized를 요구한다. 외부 호출 보호나 bootstrap/브로커 설치가 자동 활성화되는 것은 아니다.
- 실제 별도 PG/CAS/loopback HTTP에서 폴백 없음·A실패/B실패/C성공·모두 실패·전송 중 취소와 늦은 결과 미채택을 확인했다. 발급 뒤 model head/키 교체에도 기존 요청을 사용했다. 최종 Python33 pass/기존 opt-in browser1 skip, 실제 production UI2 pass/Node53/타입·build·format이다. scoped lint 신규0·기존 Python F4011/frontend effect-order1이며 전체 lint 통과가 아니다. NTFS bind의 EXE002는 archive와 같은 파일시스템 진단이라 분리했다.
- 브라우저 fixture의 저장 문구/로그인 완료 대기·새 fixture state·barrier release JSON 누락과 초기 viewport capture 실패는 따로 보존했다. 최종 fresh fixture에서 release 응답200·API exception없음과 mobile 후보3개 표시를 확인했다. 시험 서버의 합성 응답을 공급자 인증/번역 품질로 보고하지 않는다.
- 운영은 유지보수 API/중지 sender·encode/host267 그대로다. 별도 임시 API/PG만 사용하고 정리한다. 운영 DB/키·012/019·대상 교체·원본 이관·#5/DLQ 복구나 외부 유료 호출은 미실행이다.


### 운영 체크포인트 — 018 API 선행 설치와 안전 정지 분리

- **수용된 API 선행 설치:** `28c14fd3e85f59f02222719bd35bfe1056eb2364`의 API만 명시 maintenance/control·`handover=false`로 운영 설치했다. 공유 c106 `api.json`을 바꾸지 않고 전용 정책/기존 DSN의 두 RO 파일 mount를 사용한다. API의 content RW mount만 제거하고 미디어 volume·기존 파일은 보존했다. 이전 normal API는 TERM1회·timeout=-1 대기 뒤 실제 exit143·listener/init/Python 종료 및 영속 기록 대조 후 교체했다. 기존 HTTPS/vault 로그인·session/지정 관리자 조회200·업무503과 쿠키 Secure/HttpOnly/Strict를 확인했다. 외부 `/healthz`200은 web 응답이지 API 모드 증거가 아니다. web reload는 필요 없어 실행하지 않았다.
- **다음 독립 승인으로 실행한 Stop0:** 기존 논리 슬롯 `81831977b4214488b19fb78fca17c213`, 이전 boot `18e0ba6ba253bef0052f1953495344e9`, target `fd6d07677ac6929cd75b6b7f6f0ec0da79fb1f5f3bdc69251416df1d900be1f5`를 그대로 대조했다. ready/현재 작업 없음·충돌 제어/새 미발행 명령/managed 미완료 전송 없음을 확인한 뒤 정상 HTTPS·CSRF·개정7/고유 요청으로 Stop0를 보냈다. 요청 `dcccf6fb8bd04f7684178f46163e8bd1`은 개정8/succeeded, action `dc4cb60c7bd447d1abd2cb25b5f89693`은 confirmed/issue_count1이다. 실제 host267 ACK reader가 HMAC·원 요청/boot/contract·정확한 target/image/native return0을 검증했고 물리 대상도 정상 종료0이다. capacity1·desired0·disabled·pending 없음이며 재신호/시작/복구는 없다.
- **그 뒤 송신3개만 정지:** 실제 설치된 `app.dispatch`는 진행 tick 후 loop를 마치고, 두 `app.operator` 수신기는 신규 소비 취소→진행 handler의 accept/후속 dispatch 완료→ACK→thread/connection 정리 순서다. `dispatch-encode`·`results`·`engine-results` 각각 정확한 ID에 TERM 한 번/timeout=-1로 대기했고 모두 exit0/PID0·OOM/재시작 없음이다. 사전 결과 channel의 unacked/unconfirmed/uncommitted/acks_uncommitted·send_pend0, 사후 두 결과 consumer/connection 소멸과 업무/outbox/inbox 해시 동일을 함께 확인했다. 뒤늦은 Docker lifecycle event 조회는 빈 결과라 신호 횟수 증거로 쓰지 않으며, 실행 전 저장한 서비스별 단일 stop 명령·반환값·실제 종료 상태를 근거로 한다. broker 안의 진단 CLI는 PID 제한 오류가 나 같은 정확한 이미지/기존 cookie volume RO의 임시 CLI로 읽기만 했고 broker 재시작·제한/인증 변경은 없다.
- **보존·미승인 경계:** #5 raw running/needs_review·원 발행/수신 이력, 미발행 accepted-result20·encode DLQ ready1과 기존 제어/ACK 행은 그대로다. 새 Stop0 제어 기록만 추가했고 삭제/완료 처리/재발행으로 수를 맞추지 않았다. 유지보수 API·웹·host267·나머지 실행 역할·DB/MQ/S3는 계속 실행하며 다른16개 container의 ID/image/StartedAt/config/목적지별 mount를 보존했다. host267의 원 소유권은 아직 반납하지 않았고012/019·GRANT·host 코드/실행 이미지·대상 전환·원본17 이관·#5/DLQ 복구·정상 접수 재개는 미실행이다. 다른 역할의 결과 발행까지 전역 차단한 상태나 전체 작업 완료로 해석하지 않는다. 기존 업무 UI의 일반 조회 오류는 유지보수 차단이며 새 유지보수 UI 수용은 아니다.

아래는 구현 계약과 선행 검증의 범위다. 운영 현재 상태는 위 체크포인트를 우선한다. API 선행 설치와 안전 정지는 PM 수용됐으며 이후 설치 승인은 별개다.

검증 업로드·불변 workflow/티켓·PostgreSQL 상태·독립 CPU 프로세스·로컬/S3-compatible CAS·검수/승인/취소/복구·WebM과 이중 다운로드를 구현했다. renewal 관리자 경계와 실제 로컬 CPU fleet에 이어 opt-in RabbitMQ adapter·독립 수신기·결과 제어기와 공통 이미지 build graph를 추가했다. SDK/채널 대역과 실제 격리 TLS RabbitMQ 4.2.9·source-pinned MinIO·독립 CPU 두 process·결과 소비 process·PG의 합성 영상 완료/ACK/DLQ/결과 SHA를 구분해 수용했다. 컨테이너 fleet 제어·다중 머신·GPU/provider·운영 전환은 미검증이다.

## 주요 내용

### 공급자 연결 등록 — 개발본 검증, 운영 미반영

- 기존 공급자 목록의 OpenAI는 `https://api.openai.com/v1`/`openai`, Gemini는 `https://generativelanguage.googleapis.com/v1beta`/`gemini`, Anthropic은 `https://api.anthropic.com`/`anthropic`을 명시 선택할 때 채운다. 사용자 지정 서버는 빈 주소/`openai_compatible`에서 직접 입력한다. 기존 저장 개정을 읽을 때 preset을 적용하지 않으므로 사용자 지정 주소·방식·개정은 그대로다. 새로 입력 중인 키는 다른 공급자 선택 시 지워 자동 이전하지 않는다.
- 막힘은 Gemini 선택만 변경하고 필수 endpoint와 protocol은 바꾸지 않던 폼에 있었다. 기존 Registry·CredentialStore·관리자/CSRF·개정 CAS·불변 revision·암호화/키 참조 계약은 재사용했다. 이름만 수정하면 기존 키 참조가 유지되고 명시 키 교체는 새 불변 개정에 연결된다. 과거 참조를 덮어쓰거나 키를 응답/재조회 폼에 돌려주지 않는다.
- 실제 설치 API와 별도 PG에서 production frontend의 Gemini 입력→API 저장→재조회·이름 수정→키 교체와 사용자 지정 주소/키 연결 보존을 확인했다. 저장 후 원문 비노출·ciphertext 비평문·이전/현재 키 참조의 실제 복호화 일치도 확인했다. API/backend 등록 구현은 변경하지 않았으며 설치된 관련3개 모듈 bytes가 기존 소스와 같다. 이는 합성 키의 등록·저장 검증이지 실제 공급자 인증·연결·모델 추론 검증이 아니다. 화면의 연결 확인은 계속 미확인이다.
- 운영 유지보수 API·중지한 encode/송신3개·host267·운영 DB/키는 이 개발에서 변경하지 않았다. 공급자 등록을 이유로 normal 재개·provider egress·유료 호출을 허용하지 않는다. 전사/번역 adapter와 유한 동적 폴백은 위 별도 구현·격리 검증 수용 범위이며 실제 공급자 인증/품질·운영 연결은 미완료다.

### 실행·데이터 보호

- API는 명시 DB/콘텐츠 저장소만 받는다. DSN fallback·startup migration·queue scan·실모델 import/call이 없다.
- 작업 snapshot과 정의 revision은 불변이며 동의는 현재 입력/설정/검수와 결속한다. 동의 저장·실행 요청·사람 검수 저장/확정을 분리한다.
- DB delivery reservation 뒤 지정 명령 하나만 실행한다. 독립 에이전트에는 DB/전체 workflow/후속 노드/세션을 보내지 않는다.
- S3 attempt marker는 조건부 쓰기(If-None-Match)를 사용한다. 완료 receipt가 없는 중복은 결과 불명으로 막고 자동 재실행하지 않는다. 결과 ack는 애플리케이션 DB commit 뒤에만 호출한다.
- 취소·lease 만료·이전 generation 결과는 격리한다. 복구는 새 draft 자식 작업이며 검증된 완료 결과만 재사용하고 새 실행 승인을 요구한다.
- 미지원 모델·Loop/Fallback·추가 입력 binding은 편집 지원과 구분하여 실행 승인을 닫는다.

### 저장소와 WebM

- 원본 상한 256 MiB, chunk 4 MiB. `ContentStore`는 private local CAS, `S3ContentStore`는 기존 bucket의 명시 prefix/owner/CAS를 사용한다.
- S3 adapter는 bucket 생성/나열/삭제·서명 URL 발급을 하지 않는다. 신규 배포는 명시 private credential/config 파일을 직접 읽으며 기존 환경변수 이름 CLI는 infrastructure 호환용이다. 별도 operator만 명시 빈 bucket을 초기화한다. 명령/정의/DB에 raw transport credential을 넣지 않는다. 원격 HTTPS(테스트 loopback HTTP 예외), 직접 SHA/byte 검증, 불변 참조를 사용한다.
- private cache는 로컬 작업공간일 뿐 정본이 아니다. 앱/에이전트는 공유 볼륨 없이 별도 cache에서 S3 HTTP로 원본/결과를 교환한다.
- 업로드 원본과 처리 결과 원본은 보존한다. 별도 `webm-vp9-opus-v1` 파생본(VP9/Opus, 최대 1280×720)을 생성하고 원본 SHA와 연결한다. 원본을 WebM으로 바꿔 저장하지 않는다.
- `/api/videos/{id}/stream`은 WebM 재생, `/download`는 업로드 원본이다. `stream?download=true`는 WebM 첨부 다운로드다.
- 작업 산출물 endpoint는 결과 원본이며 `/preview`가 WebM이다. 양쪽 `?download=true`는 해당 파일 첨부 다운로드다. 고정 영상 입력 플레이어도 `/preview`를 사용한다.
- WebM 생성 실패 시 원본은 다운로드 가능하며 실패 상태를 보존한다. GET에서 변환하거나 지원 여부를 모르는 원본으로 플레이어를 자동 fallback하지 않는다. 현재 WebM은 bounded CPU 처리이며 장시간 미디어의 비동기 스케줄링은 잔여다.

### renewal 관리자 경계와 명시 CPU fleet

- 일반 사용자 허용 동선은 원본 목록/상세·작업 목록/시작/상세다. 나머지 직접 URL은 차단하고 관리 API는 현재 세션의 관리자 권한을 서버에서 확인한다. 세션 확인/본인 로그아웃은 관리 기능과 구별한다.
- `/api/settings/*`, 계정과 `/api/admin/agents/*`는 관리자용이다. 일반 작업 선택은 별도 `/api/work-entry/{workflows,catalog,inspect,preview,create}`를 사용한다. 관리자 제공 workflow의 출처와 revision은 작업에 불변 저장하며 원본·작업 소유자는 실제 사용자다.
- migration `007_agent_fleet.sql`이 목표 설정/revision·변경 이력·실제 인스턴스와 노드 배정을 저장한다. 운영 DB에 자동 적용하지 않는다.
- `--allow-cpu --manage-cpu`는 private local ContentStore 전용이며 S3/다른 executor와 중복 연결하지 않는다. 서버 시작이나 조회는 프로세스를 켜지 않는다. 관리자 configuration PUT 후 실제 ready handshake를 받은 CPU 프로세스만 준비로 집계한다.
- 종류별 0~8개, 전체 활성/드레인 포함 최대 16개, 인스턴스당 1개로 제한한다. DB 잠금으로 명령을 예약하고 idle 인스턴스의 마지막 배정 시각을 기준으로 분산한다. 중복 controller는 advisory ownership lock으로 차단하며 다른 controller PID를 채택/종료하지 않는다.
- 비활성화·축소는 신규 배정을 막고 이미 예약한 명령을 마친 뒤 종료한다. 자동 작업 검색/소비/재실행은 없다. 자리가 없으면 명시 작업은 대기 상태를 유지하며 후속 명시 호출 또는 향후 scheduler가 필요하다.
- 독립 instance는 private stdin/stdout의 제한 JSON 명령과 owner/CAS 참조만 받는다. DB·웹 세션·provider 키·workflow traversal을 받지 않는다. CPU 결과의 요청 digest와 attempt/generation을 검증한다.
- 연결되지 않은 얼굴교체/모델 실행환경은 미연결로 표시하고 활성화 요청을 거부한다. 실제 얼굴교체 on/off가 구현됐다는 뜻이 아니다. 컨테이너 adapter·health·자원 정책은 별도 잔여다.
- 기본 API는 agent package/Torch/FaceFusion을 설치하지 않는다. 구형 API 호환 target과 GPU/VAD overlays는 제거했다. API 직접 upload/preview FFmpeg는 남으며 CPU/GPU 선택 이미지는 분리한다. 이미지 빌드·GPU engine 설치·컨테이너 수용은 미실행이다.

### 선택 RabbitMQ 전송과 공통 이미지

- shared의 `amqp` extra는 `pika==1.4.4`만 추가하며 CPU의 `amqp` extra가 S3/AMQP 의존성을 선택한다. 기본 CPU/API 이미지에는 broker SDK를 설치하지 않고 선택 `amqp`/`broker` target에서만 추가한다. CPU 실행 subprocess에는 broker URL·DB·provider 환경을 넘기지 않는다.
- 설정 JSON은 `namespace`, `url_env`, 선택 `allow_loopback`/`ca_file`만 받는다. URL·비밀번호는 별도 명명된 프로세스 환경변수에만 둔다. 명시 vhost·인증·원격 AMQPS/인증서 검증이 필요하고 plaintext AMQP는 명시 허용한 loopback 테스트에만 한정한다. 연결 오류는 고정 코드로 치환하고 CLI의 Pika 진단 로그는 끈다.
- 연결과 namespace 내 역할별 명령/결과/격리 큐 선언을 분리한다. startup/조회에서 연결·queue declare/scan/consume을 하지 않는다. `declare-topology`만 durable classic 큐·direct exchange·DLX를 생성한다. 기존 운영 큐나 namespace를 재사용하지 않는다. classic topology의 장애·HA 보장은 아직 수용하지 않았다.
- API의 명시 `/run`은 승인된 해당 작업의 outbox만 발행한다. 매 요청이 자기 I/O thread의 새 연결을 사용하며 local fleet/executor와 중복 연결하지 않는다. publisher-confirm·mandatory 확인 전에는 outbox를 발행 완료로 표시하지 않고, 실패 후 동일 attempt를 재전달할 수 있다. 만료된 미발행 명령은 거부한다.
- CPU 수신기는 자신의 역할/owner/artifact/설정만 해석하며 별도 private cache의 S3 CLI로 처리한다. 결과 receipt의 확인 발행 뒤 명령 ACK, 결과 제어기의 DB commit·후속 dispatch 뒤 결과 ACK 순서를 유지한다. receipt/inbox가 완료 중복을 재사용하고 결과 불명/poison은 자동 실행하지 않는다.
- Pika I/O는 소유 thread에서만 수행하고 CPU/DB 처리는 작업 thread로 분리해 heartbeat를 계속 처리한다. prefetch는 1이다. SIGTERM은 신규 수신을 취소하고 진행 중 작업·결과 확인/ACK를 마친다. 연결 실패 시 자동 reconnect·작업 retry는 하지 않는다.
- 현재 명령 TTL은 60초, 기존 node lease는 120초다. 결과 큐에는 TTL을 두지 않는다. 긴 큐 대기·장시간 작업의 lease 갱신, cancel의 원격 실행 중단, DLQ 보관/재처리·재연결·HA와 원격 fleet 제어는 별도 잔여다. 취소/이전 generation/lease 만료 결과의 DB 격리는 유지한다.
- root Dockerfile의 `media-base`가 FFmpeg/FFprobe·폰트를 한 번 선언한다. `agents/cpu`와 `agents/gpu`는 named build context로 상속하고 API는 같은 파일의 stage를 상속한다. `docker-bake.hcl`이 build graph를 묶는다. Compose의 base helper는 장기 실행 서비스를 제공하지 않으며 역할별 profile은 독립 실행 단위다.
- `agents/cpu/compose.amqp.yaml`은 선택 network transport 레시피다. 명시 private env file·기존 external network·개별 tmpfs cache만 사용하고 공유 원본 bind mount·고정 container_name·Docker socket·broker service·자동 restart를 추가하지 않는다. 동일 역할의 복제는 Compose 실행 관리자의 책임이며 웹 fleet과 자동 연결하지 않는다. 이미지 빌드·컨테이너 자원 한도 수용은 미실행이다.

다음은 배포 승인 후 사용하는 진입점이며 현재 운영에 실행하지 않았다.

```sh
# 공통 base 의존성이 포함된 build graph 조회만 수행한다.
docker buildx bake -f docker-bake.hcl --print api cpu cpu-amqp api-broker gpu

# broker 설정은 namespace/url_env만, 실제 값은 별도 private 환경에서 제공한다.
python -m app.broker_server declare-topology --enable-broker --broker-config-env MIDEAGENT_BROKER_CONFIG
mideagent-cpu-amqp --enable-broker --agent analyze --broker-config-env MIDEAGENT_BROKER_CONFIG --object-config-env MIDEAGENT_AGENT_OBJECT_CONFIG
python -m app.broker_server consume-results --enable-broker --broker-config-env MIDEAGENT_BROKER_CONFIG --dsn-env MIDEAGENT_DATABASE_DSN --object-config-env MIDEAGENT_APP_OBJECT_CONFIG
```

API launcher는 `--allow-cpu --object-config-env <app-config> --broker-config-env <broker-config>`를 선택할 수 있다. `--agent-config-env`/`--manage-cpu`와 동시 사용하지 않으며 기존 `--dsn-env`/`--origin`을 명시한다. 브로커는 API startup이 아니라 명시 작업 dispatch 때 연결한다.

### 독립 CPU 진입점

Python 3.12+와 FFmpeg/FFprobe가 필요하다. `packages/shared[postgres,models,objects]`, `apps/api`, `agents/cpu`를 격리 환경에 설치한다. CPU 에이전트 자체는 PostgreSQL 패키지나 API 연결 없이 동작한다.

- `mideagent-analyze`, `mideagent-extract-audio`, `mideagent-generate-subtitle`, `mideagent-encode`, `mideagent-validate-video`: 각 고정 역할의 JSON stdin/stdout 명령. `--input-root`/`--output-root`는 명시 private root다.
- `mideagent-object-agent --agent <role> --owner <owner-id> --config-env <explicit-name>`: 원격 CAS를 사용하는 단일 명령. 설정은 endpoint/bucket/region/prefix/cache_root와 access_key_env/secret_key_env 이름만 포함한다.
- `python -m app.renewal_server --dsn-env <name> --origin http://127.0.0.1:<port> --content-root <root> --allow-cpu`: 로컬 전용 launcher.
- 같은 launcher의 `--manage-cpu`를 명시해야 관리자 상세에서 로컬 CPU fleet을 조작할 수 있다. CPU package를 같은 승인된 환경에 설치해야 하며 이 옵션 없이 조작 가능으로 표시하지 않는다. 실제 운영에 이 명령을 자동 적용하지 않는다.
- S3 실행은 content-root 대신 `--object-config-env <app-config-name> --agent-config-env <agent-config-name>`을 사용한다. 앱과 agent config의 private cache_root를 다르게 지정한다. 이 launcher는 공개 production server가 아니다.
- 구형 혼합 media 패키지·파일 queue·workflow executor·SQLite 계정/설정 API와 일회성 scripts는 제거했다. CPU/GPU는 실제 폴더에 package-dir를 매핑한다. FaceFusion/VAD 엔진 소스와 process-tree·transcript/decision/model-reference 공통 파서는 별도로 보존했다.

### 설정·wire 정본

- [MQ request/response 계약](agent-protocol.md)의 versioned schema를 패키지에 포함한다. 결과의 정확한 필드·포트·자료 유형과 request digest/세대/attempt를 runtime에서도 검사하며 raw 진단·추가 credential 필드는 거부한다.
- root Compose의 LLM/provider/model 환경변수 주입은 제거했다. `app.server --bootstrap-file`은 DB 접속 파일·콘텐츠 root·listen·origin/cookie 설정만 받고 startup에서 migrate/worker를 실행하지 않는다. 모델/provider/key 필드는 bootstrap에 허용하지 않는다. private runtime UID 읽기 조건은 루트 README를 따른다.
- 관리자 DB credential/revision resolver→주입 text wire와 레포 opt-in 설치 구성·실제 격리 broker 수용은 구현/검증했다. 실제 model agent/address-pinned network transport, GPU contract/consumer/engine, 원격 fleet·MagicDNS 운영 배포는 남아 있다. [배포 절차](../../rules/deploy.md)의 신규 설치/복구와 실행 승인 경계를 따른다.

### 검증과 남은 부채

- 정리 후 renewal 전체 회귀는 84개 통과(skip 없음), web 단위 44개와 production build도 통과했다. 소스/스키마 계약과 기존 네 브라우저 경로를 포함한다. AMQP는 실제 Pika property/실패 loopback handshake·채널 seam과 실제 CPU/S3/PG 검증이며 실제 RabbitMQ 서버 수용은 아니다. 추가 파일-bootstrap 서버/보존 자막 회귀 8개도 통과했다. 실제 파일 기반 서버 기동·liveness·관리 API의 인증 차단·DSN 비노출을 확인했다.
- 실제 CPU 기동 실패·종료, ready handshake 후 DB 기록 실패의 기존 검증도 유지한다. 변경 Python lint/format, 타입/build, Compose 역할 profile 11개와 Bake graph 정적 구성을 확인했다. Compose/Bake 검사는 이미지 빌드·스택 실행이 아니다.
- 테스트는 명시 disposable PostgreSQL의 임의 schema와 합성 미디어만 사용한다. S3 테스트는 임시 loopback 프로토콜 에뮬레이터이며 종료 후 서버를 닫는다.
- 코덱 지원 Chrome만 사용하는 우회와 구분한다. H.264/AAC 미지원 Chromium에서도 WebM 원본/산출물 재생, 재생 시간 진행·영상 크기, 원본/WebM 실제 다운로드와 SHA를 확인한다. FHD/cover/unfolded는 브라우저 에뮬레이션이지 실기기 수용이 아니다.
- 삭제된 구형 구현 전용 legacy suite는 같은 정리에서 폐기했다. 이전 legacy 27 failures를 해결했다는 뜻이 아니다. 보존한 pure 회귀와 renewal의 실제 CPU/S3/PG·브라우저 회귀를 별도로 실행한다.
- 전체 web lint는 기존 오류 80개, format은 기존 파일 네 개 부채가 있다. 에이전트 목록의 기존 컨벤션 오류 7개를 함께 정리했으며 변경 runtime 화면 lint·web 단위 테스트·타입/build 검사와 분리한다. 검사를 삭제하거나 실행 승인 보호를 낮추지 않는다.
- 실제 제품/다중 머신에서는 최소권한 bucket prefix 정책, 인증/허용 명령 범위, 브로커 topology, 장애/중복/취소 및 성능을 다시 수용해야 한다. 현재 S3 fixture는 IAM/실 MinIO 적합성을 증명하지 않는다.

## 미확정 사항

실제 제품/배포 분할·인증/브로커·GPU/실모델·대용량 비동기 실행은 별도 단계다.

## 관련 문서

- [구조](../../plans/architect.md) · [태스크](../../plans/tasks.md) · [격리 테스트](../../../tests/renewal/README.md) · [배포 경계](../../rules/deploy.md)

## 논리 슬롯1의 감사 가능한 대상 교체 (미배포)

019는 기존 control source 열/요청/ACK를 보존하고 계약 버전·후보·계획·교체/이벤트를 추가한다. 이 기능의 native 검사·완료는 새 host 실행 코드가 필요하다. 기존267 호스트/설정을 운영에서 바꾼 것은 아니다.

절차는 다음과 같다. 기존 제품 제어로 신규 배정을 막고 같은 boot 정상 종료0·signed ACK·미해결 제어 없음/발행 guard 자유를 확보한다. 기존 host를 정상 종료해 원래 exclusive lock을 반납한 뒤 정확한 candidate manifest를 준비한다. host 전용 `python -m video_service.target_handover --config-file <기존 host.json> --candidate-file <별도 manifest.json> --operation prepare --enable-handover`가 native inspect/서명을 검증하고 후보ID를 발급한다. manifest는 `agent`, `old`, `new`만 가지며 각 descriptor는 정확한 `container_id`, `image_id`, `labels`, `worker_id`다. 등록 슬롯은 늘리지 않는다.

관리자는 `/api/admin/agents/{agent}/target-handover`에서 준비된 후보와 이력을 읽고, `/preview`에 `candidate_id`, `/decisions`에 `plan_id`, `decision_id`, 10자 이상 `reason`, `acknowledge:true`를 정상 세션/CSRF로 보낸다. API는 임의 container/image/socket을 입력받지 않는다. 호스트는 같은 파일과 `--operation apply --transition-id <decision_id> --enable-handover`로 명시 실행한다. apply에는 기존 exclusive lock과 sender guard가 필요하고 이전/새 정확한 물리 정지·서명·권한·CAS를 다시 확인한다. 실제 전환은 계약 버전 추가·current epoch 갱신·applied 기록을 한 transaction에 반영한다. 이벤트에는 DB session actor/PID와 시각을 남긴다.

재기동할 host는 원래 config와 별도 `--handover-bindings-file`을 사용한다. 바인딩 JSON은 `{agent: 승인된 exact descriptor}`이며 DB에 기록됐다는 이유만으로 자동 채택하지 않는다. desired0을 유지하고 새 target을 자동 시작하지 않는다. 새 등록 상태와 관측을 확인한 뒤 별도의 명시 Start가 필요하다. 중단된 applying은 held로 남고, 오류 해소만으로 자동 재개되지 않는다. held의 해제/새 판단은 이번 범위가 아니다. 기존 Native adapter를 root 권한으로 직접 호출하는 것은 제품 host/요청 권한 경계 밖이며 이 기능이 범용 Docker administrator를 통제한다고 주장하지 않는다.

역할 권한은 새 테이블에도 분리한다. API는 후보/계약/이력 SELECT, 계획·planned 결정 INSERT와 group의 revision/pending_handover 입장 쓰기만 추가한다. 계약/후보 등록·phase 완료/이벤트 직접 쓰기·native 권한을 주지 않는다. 기존 host 전용 역할은 필요한 control/ACK/전송 근거 SELECT와 accounts의 id/role/active만 읽으며, 후보/불변 계약 INSERT와 승인된 transition phase 및 group current-pointer 갱신만 수행한다. events는 보호된 trigger가 append한다. 계정 비밀번호·원본/키/backup 쓰기 권한은 추가하지 않는다. 실제 운영 역할별 GRANT/이미지 설치는 별도 검토·승인 후 수행한다.

검증은 새 교체 경계의 실제 PG와 통제된 native adapter/인증 ASGI, 별도 실제 idle native 컨테이너/CLI·signed ACK 범위다. native 시험의 PG 상태 보고를 운영 MQ/제품 영상 E2E로 확대하지 않는다. 기존 MQ 영상·A/B 여정·#5 복구는 재실행하지 않는다.

## 운영 교체 전 설치 연결 리허설과 조건부 설치 순서

수용 `9ae90c4fe61edd3e2ea83c34fdba2a27aa6bd194`의 설치 이미지에서 별도 API·host LOGIN 역할로 실제 정상 흐름을 확인했다. 이는 SET ROLE로 owner를 가장한 시험이 아니라 각 프로세스/CLI가 서로 다른 전용 DSN으로 접속한 결과다. 관리자 승인 이벤트는 API session, applying/applied는 host session이었다. 두 역할 모두 superuser/createdb/createrole/replication/bypassrls가 아니며 schema CREATE/전체 table GRANT를 주지 않는다.

API는 정상 인증을 위해 accounts SELECT와 계정 발급의 지정 INSERT 열, 기존 계정 관리/row lock에 필요한 active/role UPDATE, sessions/login_limits의 필요한 동작, control 자료 SELECT·request/plan/planned decision INSERT 및 group admission 열만 사용한다. host는 accounts의 id/role/active만 읽고, control/ACK/관측과 전송 상태의 지정 읽기·고정 group 등록/관측·journal/서명 evidence·불변 후보/계약 INSERT·승인된 phase/current-pointer의 필요한 쓰기만 사용한다. API의 contract/phase/후보/이력 변조와 host의 password_hash 읽기·계정 변경 권한은 주지 않았다. 구체 table/column 목록과 실제 privilege audit은 리허설 제출 자료에 두며 운영 role에 포괄 권한으로 적용하지 않는다.

기존9ae 설치 연결 리허설의 일반 API는 private content root를 미리 준비해야 했고, 최초 누락 실패를 uid10001/mode0700 tmpfs로 해결했다. 새 유지보수 모드는 미디어/credential/broker initializer를 아예 호출하지 않으므로 content root를 생성하거나 새 공용 입력 route를 열지 않는다. 일반 normal 모드의 content root 조건은 그대로다. API는 private API leaf RO만, host는 config/DSN/key leaf RO·receipts RW와 지정 daemon socket만 가진다. host는 uid10001과 daemon group으로 실행했다. fixture 상태 발행자는 별도이며 PG 보고를 실제 MQ 처리로 확대하지 않는다.

### 명시 유지보수 기동 계약 — 구현·격리 확인 및018 API 운영 선행 설치 수용

- `app.server --bootstrap-file … --admission-mode maintenance --enable-control`과 bootstrap의 `admission_policy`가 반드시 일치해야 한다. normal도 `--admission-mode normal`과 `{"mode":"normal"}`을 명시한다. 기존 bootstrap/Compose를 그대로 쓰면 새 HTTP 서버가 기동을 거부하며, 이를 normal fallback으로 해결하지 않는다. background operator/dispatch/result의 설정 소비와 API의 입장 정책은 별개다.
- 유지보수 객체는 정확히 `{"mode":"maintenance","agent_id":"<기존 등록 agent>","slot_id":"<그대로 보존한 32hex worker slot>","handover":false}`다. 단일 capacity/slot 일치를 DB에서 읽기 전용 확인하며 enroll/provision·계약 수정은 하지 않는다. HTTPS origin·Secure cookie, control opt-in을 요구하고 broker 실행 opt-in은 거부한다. 설정 오류/DB preflight 실패는 sanitized error와 exit2, listener 미개방이다.
- `handover:false`는018에서 기동하고019가 필요한 GET/preview/decision을 닫는다. 019가 적용되거나 오류가 해소돼도 자동으로 바뀌지 않으며 같은 설정으로 재시작해도 닫힌다. 별도 승인된019/역할 계획 이후에만 `true`를 명시해 재시작한다. 해당 기동은019의 target table/epoch/pending catalog를 확인하며 미준비면 열지 않는다. migration 실행이나 API 역할의 schema_migrations SELECT/DDL GRANT를 추가하지 않는다.
- 유지보수 허용은 **GET `/healthz`, GET `/api/auth/session`, POST `/api/auth/login`·`logout`, GET `/api/admin/agents/{고정 agent}`, PUT 그 agent의 `/configuration` 중 strict `enabled=false/replicas=0/request_id/revision`**, 명시019 단계의 관리자 target-handover GET/POST preview·decisions뿐이다. 일반/관리자 모두 나머지 업로드/chunk/완료·원본 선언·작업 생성/승인/실행/복구·계정/모델/연결 변경과 미분류 경로·HTTP method는 body 수신/업무 DB·파일·외부 호출 전에503으로 닫는다. `/admin`·GET·OPTIONS 전체 허용은 없고 capabilities/media UI route도 열지 않는다.
- 허용 URL 자체는 인증 우회가 아니다. 기존 로그인·세션·권한/CSRF·origin·Secure cookie와 사유/개정/CAS 검사는 그대로며 Stop0도 기존 등록 slot을 같은 DB row lock 안에서 다시 대조한다. Start/증설/다른 slot과 등록 slot 변경은 차단한다. 최소 조회는 원격 mailbox만 읽고 일반 Fleet/미디어 조회에 필요한 권한을 추가하지 않는다.
- 기존 AuthGate는 auth/session→login으로 접속할 수 있으나 업무 화면은 닫힌 상태다. 이번 인터페이스는 기존 인증과 최소 관리자 API이지 새 유지보수/교체 UI가 아니다. 허용된 GET을 읽기 전용 감사 전역 보장으로 확대하지 않는다. 일반 작업/처리 확인 GET의 case capture 등은 허용 목록에 넣지 않았다.
- 설치본 새 경계20개(실패/오류/skip0, 기존 의존성 경고1)와 내부 TLS peer→실제 app.server 재시작을 확인했다. 이는 공개 ingress 추가 없이 network namespace 안의 시험 peer다. 기존267 host+018에서 실제 isolated target 종료0·signed ACK 뒤,019/명시 phase 전환→같은 HTTPS 세션의 preview/decision→host CLI apply/조회도 연결됐다. 새 target은 created/미시작, desired0이며012는 이 fixture에 없다. 이전47/MQ 영상/A-B는 반복하지 않았다.
- fixture 재현 중 이전 setup.py에 없고 수용된 최종 권한 inventory에는 있는 API의 dispatch 3열 SELECT를 빠뜨려 preview503이 났다. 계획0·transaction rollback을 확인하고 **기존 수용 inventory의 같은3열만** fixture에 복원했다. 새 제품 권한이나 운영 GRANT를 추가한 것이 아니다. 서버 자식 SIGTERM은 실제 -15도 기록하며 종료0으로 꾸미지 않는다. 실제 API container/old267 host/native stop은 각각 종료0이었다. 오프라인 build 시 runtime base에 setuptools backend가 없어 실패한 기록도 보존했고 이전 검증과 같은 pip 격리 build로 로컬 package를 재설치했다.
- 종전9ae 첨부의 lint 정본은 신규0/기존4 그대로다. 이번 변경 경로 lint는 신규0, 해당 경로의 기존2(I001/UP017), NTFS EXE0026건은 별도 환경 진단이며 전체 lint pass가 아니다. 비교는 같은 repo Ruff 설정의 archived baseline과 했다.

같은 별도 운영 복원 DB에서 migration loader가012와019만 적용함을 확인했다. 기존51개 업무 table의 원래 열 값, 기존 migration 행,6개 작업의 snapshot/원 origin fallback, #5 running과 제어/ACK 이력을 대조했다. 복원은 --no-owner/--no-privileges이므로 실제 운영 역할/ACL 적용 검토는 별도다.

### 승인 후에만 사용할 설치 순서

1. 원본/DB/설정·키/WIP·운영 image/target·Serve 경로와 기존 요청을 보존한다. **012/019보다 먼저 입장 차단을 설치·확인한다.** 기존 HTTP API의 신규 연결을 닫고 종료 전 이미 들어온 요청/transaction을 graceful drain해 정리 여부를 대조한 뒤,018 호환 유지보수 API만 `handover=false`로 기동한다. 오래된 normal API를 겹쳐 남기거나 timeout을 이유로 강제 종료/요청 초기화하지 않는다. 기존 HTTPS·정확한 origin·vault/세션·CSRF·Secure cookie를 그대로 사용하고 liveness의 mode/phase와 관리자 정상 접속·업무 차단을 확인한다. 누락/불일치/기존 listener 잔존/차단 미확인이면 여기서 중단한다. **이 닫힌018 API 선행 설치만 공용 기능의 API-only 공개와 구분하는 예외**이며 현재 이 선행 단계는 운영 수용됐다. Stop0는 다음 독립 승인 단계다.
2. 정책 적용 이전에 이미 들어온 요청과 결과 수신·DAG 후속 발행은 입장 차단으로 취소/완료/중지되지 않는다. 기존 pending/sending/unknown·outbox/receipt·진행 노드와 각 송신 프로세스를 따로 대조하고 drain한다. 승인된 host267 제어로 지정 encode Stop0를 접수해 새 배정을 막고 진행 작업 처리/ACK·동일 boot 정상 종료0·signed native ACK를 확인한다. 현재 이 Stop0는 위 새 원 요청으로 성공했다. #5/미확정 요청은 보존하며 자동 재발행·TTL 변경으로 통과시키지 않는다. 안전 정지/전송이 불명확하면 해당 교체를 보류한다.
3. 결과 수신과 후속 발행 정리 뒤 승인된 `results`·`dispatch-encode`·`engine-results`만 정상 종료한다. 현재 세 서비스 정지는 완료됐지만 **host267은 이번 승인에서 유지했고 원 exclusive session을 반납하지 않았다.** 다른 실행 역할도 계속 실행한다. 입장 정책이 별도 송신기를 멈췄다거나 전체 송신/작업이 끝났다고 간주하지 않는다. host267 정상 종료·소유권 반납, 필요한 백업/별도 복원과012/019·역할 설치는 각각 다음 승인 범위이며 자동 진행하지 않는다. 이 작업에서 수용 복원/영상 시험을 다시 반복하지 않았다.
4. 별도 승인된012+019와 이미 검토된 지정 table/column 역할 계획을 적용한다. 앱4·CPU/model/GPU reader·웹의 origin 계약을 함께 맞추고 새 공용 입력을 정상 API만 먼저 노출하지 않는다. encode 후보는 같은 logical worker/역할·정확한 image/labels/mount·restart=no로 생성하되 미시작이다. API는 maintenance 유지와 명시 `handover=true` 재기동만 허용하고,019 catalog/역할 검토가 안 맞으면 미개방 상태로 멈춘다. auth/origin/cookie를 낮추거나 포괄 GRANT·새 ingress로 해결하지 않는다.
5. **호스트 코드 교체:** 새 host 코드를 준비하지만 daemon을 먼저 띄우지 않는다. host.json·DSN/key·ACK leaf를 보존하고 별도 manifest로 host CLI prepare→정상 HTTPS 관리자 preview/승인→같은 host CLI offline apply를 명시 실행한다. 원 host/session·sender가 소유 중이면 거부하며 group은 desired0이다. 중단된 applying은 held, 완료 응답 유실은 같은 기록 조회만 한다.
6. 승인된 exact descriptor만 든 별도 binding으로 새 host 진입점을 기동하고 계약/관측/desired0·새 target 미시작을 확인한다. **유지보수에서는 Start도 차단된다.** coordinated 설치·기존 기록·송신 fence와 복구 경계가 별도로 수용되기 전에는 유지보수/미개방 상태를 유지한다. 정상 접수 재개는 별도 승인 후 explicit normal bootstrap+기동 요구를 함께 바꾼 재기동으로만 하며, 오류 해소나 호스트 기동이 normal/Start를 뜻하지 않는다. 이후 Start 역시 별도 정상 인증/CSRF·개정에 따른 명시 조작이다.

### 중단·복구·롤백 경계

- 후보 준비/계획만으로 전환하거나 시작하지 않는다. applying 전 확인 실패는 거부/held이며 원 target 계약·작업은 그대로다. durable applying 중단은 다음 명시 호출에서도 held로 남고 자동 재시도·재신호·시작으로 이어지지 않는다. held 해제/취소는 수용 기능에 없다.
- pointer+applied transaction은 원자적이다. commit 뒤 응답 유실은 같은 decision의 완료 기록만 읽는다. 바인딩 누락/불일치로 daemon 기동이 막혔다고 DB 계약·원 config를 덮어쓰거나 old host를 다시 자동 채택하지 않는다. 승인된 exact 파일과 새 host 설치를 대조하는 복구만 별도 승인 아래 진행한다.
- 새 공용 작업이 생긴 후 old-reader/옛 owner FK로 단순 복귀하지 않는다. 최신 snapshot/원본/산출물/판단을 지우는 전체 DB 복원·owner 변경 대신 신규 접수/실행 보류와 origin-aware forward repair/별도 승인 복구를 사용한다. 이전 image가 남아 있어도 새 container ID에는 다시 정확한 감사 대상 전환이 필요하다.
- 이전9ae 설치 연결 리허설은 기능 확대 없이 최소권한 정상 연결·실제 entrypoint/binding·한 복원본012+019 확인만 수행했다. 수용된47개·MQ 영상·A/B 여정은 반복하지 않았다. lint 정본은 신규0·기존4이며 전체 lint 통과가 아니다. 운영012/019·host/image/pin·원본17개·#5는 변경하지 않았다.
