# 현재 구현 태스크

## 목적

구현·검증 완료와 운영 미검증을 구분한다. 부분 구현을 GPU 잔여만 있는 상태로 보고하지 않는다.

## 현재 상태

### 등록 모델 전사·번역의 실제 설치 진입점 — 구현·격리 설치 확인 완료, 운영 미반영

- [x] 정식 `app.server`에 기본 꺼짐인 `--enable-registered-models`를 연결했다. normal admission/명시 broker/S3/private 정책·기존 암호화 키 resolver가 함께 있어야 하며, API는 모델을 동기 실행하지 않고 전용 등록 모델 큐로 전달한다. `app.operator consume-registered-models`는 독립된 신뢰 애플리케이션 프로세스로 같은 Execution의 실행·intent/receipt·채택을 재사용한다. CPU/GPU 물리 에이전트에 DB/모델 키를 전달하지 않는다.
- [x] 기존 local delivery 조건을 지우지 않고, 같은 credential/database와 명시 S3·등록 broker factory/runtime·정책 SHA의 결속을 검사하는 별도 전달 경계를 추가했다. MQ에는 owner/job/attempt/request SHA만 보내며 수신기는 commit된 outbox와 원 요청을 확인한다. 모델/연결/키 개정·언어/후보 순서를 실제 요청까지 유지하고, 정상 정책은 승인 origin/공인 IP에만 HTTPS Host/SNI/인증서 검증으로 연결한다. 프록시·리다이렉트·다른 IP 자동 재시도는 없다. loopback HTTP는 격리 정책+명시 시험 flag+disposable 환경 모두가 있을 때만 허용한다.
- [x] 별도 PG·실제 TLS RabbitMQ/MinIO·서로 다른 API/results/model 캐시·새 격리 CPU consumer와 통제 HTTP로 정식 설치 명령→CPU 결과 수신→등록 모델 전달→전사/번역→채택/티켓 manifest·파일 다운로드를 확인했다. 발급 후 head/endpoint/key를 바꿔도 이전 개정의 실제 주소·모델·키/언어·후보 순서를 사용한다. 정상 모델 출력2개의 실제 S3/ticket 바이트·API 다운로드 SHA가 같고, 새 프로세스의 같은 완료 참조 수신은 HTTP를 반복하지 않는다.
- [x] 호출 중 취소 뒤 503이 반환돼도 후속 후보/번역 요청은0이며 늦은 receipt1은 quarantine/정상 모델 manifest0으로 남는다. 틀린 SHA/존재하지 않는 attempt 참조2개는 격리 전용 dead queue로 거부하고 기존 완료 manifest/receipt/HTTP 횟수를 바꾸지 않는다. 기존 adapter/영상/MQ 전체 회귀는 반복하지 않았다.
- 설치된 site-packages 실제 코드9모듈 SHA를 대조했다. installed 단위9·실제 설치 경계4 통과이며 frontend 변경/화면 시험은 없다. scoped Ruff는 Git mode0644/full-tree 조건에서 신규0·부모에도 있는 I0012다. 기존 Starlette/httpx 경고는 남긴다. API 자식의 실제 SIGTERM -15와 application/CPU consumer0, PG/MQ/S3 0을 구분해 기록하고 임시 container/network를 제거했다. 기존24개 container 설정/실행 상태·WIP21 hash를 보존했다.
- 이 묶음은 **소스 수용·App push 검토 대기**다. 의존성 보존 후보 이미지의 정식 CLI/격리 요청·실행 연결 검증이며 실제 공급자 인증·인식/번역 품질·공인 egress 승인이나 여러 컴퓨터 설치 수용이 아니다. 운영 배포·서비스/DB/키·012/019·원본17개·#5/DLQ·정상 접수 재개는 수행하지 않았다. 기존 native lifecycle/고정 호스트와 다른 실행 역할도 그대로다.

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
- [ ] 순수 제품 UI의 모델·언어 선택→티켓→승인→실행→결과의 최종 사용/운영 연결. 공통 캔버스의 편집·renewal 실행 상세 자동 정렬·연결선 정리·전체 보기는 위 구현·격리 확인 완료 범위이며 운영 반영과 구분한다.
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
- [ ] 공용 원본 이관, 순수 UI-only 고정 모델 언어 선택 및 기타 미수용 범위는 별도로 남긴다. 개인 소유권 배정은 현재 요구가 아니다.

## 미확정 사항

스토리지 제품·배포 위치, 외부 실행 관리자, drain 제한시간/강제중지와 장애 후 소유권 인계는 [미확정 기획](ideation.md)에서 별도 결정한다. 원본·작업 이외의 관리 기능과 서버 전체 에이전트 제어는 관리자 전용이다. 현 CPU 기본 동작은 강제 종료가 아닌 drain이다.

## 관련 문서

- [구조](architect.md) · [실행 계약](../references/high/runtime.md) · [미확정안](ideation.md)
