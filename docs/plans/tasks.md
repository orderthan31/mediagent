# 현재 작업과 미완료 기능

## 목적

확정된 제품 요구의 구현과 실제 수용 여부를 구분한다. 과거 실행 로그와 검사 횟수를 누적하는 지시서로 사용하지 않는다.

## 현재 상태

사용자가 직접 개발·실행 재개와 기존 Gemini의 실제 시험을 승인했다. 혜지가 VPS에서 개발·CPU 검증을 수행하고, 기존 SSH로 Windows의 소스 갱신·GPU 검증까지 맡는다. 혜윤에게는 원격으로 해결할 수 없는 외적 제어만 묶어서 요청한다. 중단된 자동 후속 개발은 재개하지 않는다.

기존 비공개 브리지의 TLS 신뢰 교체와 전사·번역 두 역할의 등록정보 갱신, 당시 리뉴얼 서비스 반영은 확인했다. 새 소유 시험에서는 실제 Gemini 전사·번역과 검수를 마쳤으나 검수 후 같은 작업의 재개가 막혔다. 검수 결과를 재사용한 별도 번인 작업은 완료했으며, 이를 단일 작업 전체 완주로 합산하지 않는다.

청크 진행·로그 표시·입력 기준 자동 호출량 산정은 승인된 구현 커밋 `c2ab0602c221fd07ce12ef00a8cd73a3c6b9b7c8`으로 운영 반영했다. DB 변경 035, 리뉴얼 API·화면·두 모델 브리지·컨트롤러·번역 결과 수신기와 번역 워커 프로필을 갱신하고 서비스 상태·실제 배포 자산·기존 작업의 읽기 전용 진행 조회를 확인했다. 실제 PostgreSQL의 새 작업 등록부터 결과 채택까지의 격리 시험은 공급자 어댑터 대역을 사용했으며, 이번 반영에서 유료 호출이나 기존 작업 재실행은 하지 않았다. 인증된 실사용자 화면과 일본어 원본의 단일 작업 전체 완주는 별도다.

로그의 캡처 초기화 실패와 여러 줄 본문 노출은 출력 경계 보완과 독립 SPEC·QUALITY 검토 후 반영했다. 기존 비공개 로그 원문과 수집 출처는 보존하고, 화면에서는 출처가 확인되지 않은 본문과 자유형 출력을 숨긴다. 직접 OS 파일 디스크립터 출력이나 계측되지 않은 자식 실행까지 수집한다고 주장하지 않는다. 사용자의 후속 정리 승인으로 취소된 #35의 원 명령을 모델 실행·결과 재발행 없이 식별 확인 후 폐기하고, 구 전사 인스턴스를 제거했다. 신규 전사 워커 프로필과 전사·CPU 결과 수신기도 같은 구현으로 갱신했다. 기존 상태 볼륨·로그·호출 이력과 미정산 관측값은 수정하지 않았으며, 새 수요가 없을 때 실행 워커가 없는 것은 정상이다.

시험용 워크플로우 6개·원본 등록 9개와 시험 작업 7개 및 취소된 #35를 라이브러리 목록에서 제거했다. 이는 원본 바이트·감사 기록의 물리 삭제가 아니다. 가짜 공급자 연결 2개와 시험 모델 등록 4개는 사용 중지했고 실제 원본과 기존 Gemini 연결·모델은 유지했다. 웹 UI `e0846400d9732550d09bfb512bc80d22489d617c`는 중지 항목을 기본 목록에서 숨기되 ‘사용 중지 포함’으로 열 수 있게 하며, 기존 비활성 항목의 상세·편집·고정 연결은 보존한다. 새 모델 등록에서는 사용 중지한 공급자를 선택지에서 제외한다.

작업 추가 화면은 웹 구현 `ab98239e0d14b6c9ed51c1585a5b10032f80cf4e`로 생성 응답을 받으면 바로 같은 작업 상세를 열고, 최초 명시 클릭의 시작 절차를 이어가도록 반영했다. 상세 조회가 끝나기 전에도 준비 단계와 오류를 표시하고, 중복 생성·중복 시작을 막는다. 독립 SPEC·QUALITY 검토, 오프라인 브라우저와 실제 HTTPS 자산 검증을 완료했다. 대용량 원본의 실행 전 검증 시간 자체를 줄인 변경이나 인증된 실제 공급자 전체 완주 검증은 아니다. 브라우저 새로고침으로 유실된 시작 권한을 자동 재생하지 않는다.

저장 워크플로우에 남은 옛 전사·번역 `128` 기본값도 확인했다. 기존 워크플로우 3개의 해당 설정 6곳만 정상 버전 저장 경로로 `auto`로 바꾸고 최신 작업용 조회·컴파일 결과를 확인했다. 과거 워크플로우 버전과 이미 생성·실행 중인 작업의 고정 한도·스냅샷은 바꾸지 않았다.

Vertex AI 서비스 계정 JSON 연결은 구현 `a9090e3de9c1baee37d3a578522140616e5ffd2e`로 2026-11-14 운영에 반영했다. DB 변경 036과 리뉴얼 API·웹·전사/번역 브리지·컨트롤러·결과 수신기 3개, 향후 전사/번역 워커의 이미지와 프로필을 함께 맞췄다. 결과 수신기도 같은 설정과 후속 실행 경로를 사용하므로 교체 전 해당 큐의 ready/unacked가 모두 0임을 확인했다. 기존 private 배포 정의에 버전별 정책·프로필과 복구용 이전 컨테이너를 보존했다. 실제 기동 경로의 모듈 바이트, HTTPS 자산 22개, 인증 없는 설정 조회 거부, 기존 35개 migration 이력과 업무·호출 이력 28개 테이블, 기존 큐 관측값과 레거시·공유 기반 서비스의 불변을 확인했다. Google OAuth와 Vertex global/us-central1의 명시 origin만 추가했으며 공개 연결·인증·권한은 확대하지 않았다.

서비스 계정 파일은 최대 32 KiB의 UTF-8 JSON을 검증해 암호화 저장하고 프로젝트·리전을 연결 revision에 고정한다. 모델 목록·전사·번역 런타임 연결과 실제 SDK는 합성 자격증명·대역 HTTP 및 격리 PostgreSQL로 검증했다. 실제 Google 키 인증·모델 목록 조회·유료 추론과 인증된 운영 화면의 새 키 등록은 이번 배포에서 실행하지 않았다. 실 공급자 수용은 별도이며 기존 공급자의 키·모델 선택과 고정 이력은 유지한다.

#41은 96개 호출 중 95개 완료·1개 `invalid_response`로 역할이 `held`이고 작업 표시가 `running`인 상태다. 실패는 8번째 구간이며 고정 128회 상한에 도달한 것이 아니다. 실패 응답 본문이 남아 있지 않아 세부 원인은 미확정이고, 제거된 당시 워커의 stdout을 복구한 것으로 표시하지 않는다. 이번 반영으로 #41의 결과·한도·상태를 변경하거나 재시도·취소·재발행하지 않았다.

## 주요 내용

### 구현하고 격리 실행한 기능

- [x] 업무 에이전트의 타입 지정 포트, 분기·선택·다중 부모 합류·사람 검수·제어 신호를 기존 durable 그래프로 연결한다.
- [x] 영상 없는 UTF-8 SRT/단일 언어 SMI 원본을 기존 등록·CAS에 연결한다. 음성 원본의 후속·병렬 에이전트를 허용한다.
- [x] 검수한 자막을 재생성하지 않고 영상 제작에 연결한다. 실제 CPU 인코딩·검증과 인증된 산출물 다운로드를 실행한다.
- [x] Gemini structured-audio 요청의 호환 schema와 로컬 응답 제한을 분리한다. 특정 모델명을 코드에 고정하지 않는다.
- [x] 실행 기본값을 채울 때 워크플로우가 명시한 모델 호출 한도를 확대하지 않는다. 미선택 기본값과 기존 batch 설정은 유지한다.
- [x] 실제 등록 Gemini의 새 음성 전사·한국어 번역 결과로 한국어 MP4를 만들고 브라우저 재생·탐색을 확인한다. 운영 브리지 전체 경로 수용과 구분한다.
- [x] 실제 NVIDIA CUDA VAD에서 확인한 디지털 무음 잔류를 보정한다. 원시 신경망 점수·적용 정책을 보존하고 PCM 기반 재검증 후 파형·원본 시각 맵을 생성한다.
- [x] 새 전사·번역 기본값을 실제 입력 단위와 고정 후보 수에 따른 자동 호출량으로 바꾼다. 기존 명시 숫자 한도·스냅샷·불명 무재시도와 빈 번역의 무호출을 보존한다.
- [x] 새 v2 작업의 정상 등록 경로에서 선택한 전사 폴백을 연결하고 실제 PostgreSQL의 승인·고정 명령·도구 호출 기록·전사/번역 결과 채택을 격리 검증한다. 공급자 대역과 실제 유료 호출을 구분한다.
- [x] 검증된 준비 계획에 따른 청크 집계와 실행 기록·콘솔 표시를 구분한다. 과거 기록 부재·미확정 상태·느린 갱신·빈 작업을 정직하게 처리한다.
- [x] 새 작업 생성 직후 상세로 이동하며 최초 명시 클릭의 시작을 한 번만 이어간다. 느린 응답·단계별 오류·불명 접수 결과·중복 클릭·권한과 재열기에서 암묵적 재실행이 없음을 격리 검증하고 웹에 반영한다.
- [x] Vertex AI를 별도 공급자로 연결하고 서비스 계정 JSON 파일의 검증·암호화·고정 프로젝트/리전·모델 목록·전사/번역 런타임을 구현한다. 실제 SDK·격리 DB·브라우저 검증 후 관련 운영 서비스와 정책·미래 워커 프로필을 반영한다. 실제 키 인증·유료 추론 수용과 구분한다.

### 공통 구간 복구 운영 반영

전사·번역의 실패/미시도 구간을 선택 재시도·명시 제외·수동 입력으로 해결하는 후보를 구현했다. 성공 결과와 기존 호출·고정 예산은 보존하고, 추가 호출은 별도 승인과 새 시도 이력으로 기록한다. 부분 재시도에서 새로 성공한 구간과 저장한 수동 입력은 다음 결정·화면 재열기에도 유지한다. 실제 CPU 준비·격리 PostgreSQL·원래 역할 그래프/브리지·복구 브리지·같은 작업의 결과 채택·정상 다음 단계 준비를 합성 입력과 공급자 대역으로 검증했다. 운영 공급자 호출 수용과는 다르다.

독립 SPEC PASS·QUALITY APPROVED를 받은 구현 `3ed7c0e9cd451d54afbccb5be28c77480837181c`를 사용자 운영 반영 지시에 따라 기존 설치에 적용했다. DB 변경 037과 새 복구 테이블 두 개의 최소 SELECT/INSERT·상태 컬럼 UPDATE, API의 기존 전사/번역 브리지 토큰·CA 읽기 전용 연결, API·웹·두 private 브리지를 반영했다. 기존 테이블 권한·DSN·인증·공개 연결·원래 모델/업무 이력은 유지했다. 같은 호스트의 native backup을 별도 offline DB에 복원해 기존 73개 테이블·36개 migration 이력 보존과 037 및 최소 권한을 검증한 뒤 전환했다.

실제 활성 API에서 #41의 성공 95개·실패 1개와 8번째 구간의 retry/skip/manual 조작 가능 상태를 읽기 전용으로 확인했다. 실제 HTTPS 자산 22개가 승인 빌드와 일치하고, 새 복구 API의 무인증 조회는 401, private 브리지는 TLS 호스트명 검증과 무인증 403을 유지한다. 기존 업무·호출 이력 19개 테이블과 레거시·컨트롤러·결과 수신기·공유 기반 서비스는 보존했다. 기존 handover 보조 컨테이너 두 개의 자율 재시작은 전환 전부터 존재하는 별도 상태이며 변경하지 않았다. 운영 로그인 화면은 확인했지만 저장된 로그인 정보가 없어 사용자 계정으로 직접 조작하지 않았다. #41의 결정 저장·결과 채택·다음 단계·실제 유료 호출은 실행하지 않았으며 사용자의 구체적 선택과 필요한 호출 승인을 유지한다.

### 작업 실행 화면·로그·결과 정리 운영 반영

구현 `2f3f224b2b7ff33929b0d282ec1e532230e91c39`를 기존 `renewal`에 게시하고 기존 API·웹 두 서비스에 반영했다. 설정용 캔버스는 유지하고 작업 상세에는 별도 실행 모니터를 연결했다. 현재 처리 중인 태스크를 우선 표시하며, 처리 중인 태스크가 없으면 실패·보류 지점을 강조한다. 노드 안에서 현재 내부 단계와 실제 처리·성공·실패 수를 구별하고 사용자 선택·스크롤을 polling으로 되돌리지 않는다. 초기 자동 추적으로 상세를 열지 않으며 사용자가 선택할 때만 연다.

결과 파일의 보기·다운로드를 한곳에 모으고 태스크 출력·언어별 결과·영상 미리보기의 중복 조작을 제거했다. 중간 파일은 접어서 제공하며 서로 다른 요청 언어·형식과 SRT 수정 사본은 보존한다. 로그 탭은 실제 보존된 stdout/stderr만 표시하고 상태·요청 수·구조화 진단을 원문처럼 보여주지 않는다. #41의 과거 원문은 pre-tee 정책으로 보존되지 않았으므로 복원했다고 표시하지 않는다. 기존 비밀정보 차단 정책은 유지한다.

복구 미요청 안내·실패 구간 우선 표시·재시도/무시/직접 입력 버튼과 공급자 추가 메뉴도 함께 반영했다. 무거운 복구 GET은 원본 검증을 잠금 밖에서 수행하고 다시 잠가 문맥을 재검증하며, mutation·승인·재실행 방지 경계는 유지한다. 이를 반복 I/O 제거 또는 관찰된 503의 확정 원인 해결로 표현하지 않는다.

동일 동결 소스의 독립 SPEC·QUALITY 검토와 웹 단위 165개, 관련 UI/브라우저 45개, 실제 PostgreSQL을 포함한 복구 회귀 117개 및 별도 진행 투영 13개 검사를 통과했다. 운영에서는 실제 모듈 바이트와 HTTPS 자산 22개·health 200·작업/복구/로그 무인증 401을 확인했다. 기존 업무·호출·복구 이력 21개 테이블, migration 37개 이력과 모든 기존 ACL, 레거시·브리지·컨트롤러 등 비대상 서비스는 보존했다. 이전 컨테이너와 새 native backup·롤백 절차를 남겼다. #41은 여전히 96개 중 성공 95·실패 1이고 8번째 구간의 복구 선택만 읽기 전용 확인했다. 실제 복구 선택·유료 호출·인증된 사용자 브라우저 조작은 수행하지 않았다.

### Windows 자원 수집 창 반복 표시 수정

자원 화면의 1분 주기 스냅샷 수집은 유지하고, 기존 예약 작업의 실행 동작만 콘솔 없는 Windows GUI 실행기로 교체했다. Windows 기본 .NET Framework로 빌드하며 별도 상주 서비스나 Python/WSH 의존성을 추가하지 않는다. 기존 실행 계정·로그온 방식·권한·주기·중복 실행 정책·수집 스크립트·출력 경로는 유지한다. 실행기는 `UseShellExecute=false`, `CreateNoWindow=true`로 PowerShell을 호출하고 실제 종료 코드를 예약 작업에 전달한다. 예외 대화상자를 띄우지 않으며 최근 실행 진단을 제한된 파일로 남긴다.

Windows에서 GUI 실행 형식·PowerShell/네이티브 자식 콘솔 미표시·공백 경로·오류 코드/진단·누락 입력 거부·양쪽 출력 drain과 진단 크기를 6개 사례로 확인했다. 실제 예약 작업의 자연 실행 2회가 정상 종료하며 수집 파일을 갱신했고, 운영 API의 읽기 전용 관측 파일도 최신임을 확인했다. 기존 컨테이너 21개의 ID는 유지했고 앱 재배포·재시작·작업 재실행·유료 호출은 하지 않았다. 이전 예약 작업 XML과 설치 정보를 호스트에 보존했다. 소스/설치/테스트 스크립트는 `ops/windows/ResourceObserverLauncher.cs`, `install-resource-observer-launcher.ps1`, `test-resource-observer-launcher.ps1`이다.

### 실행 관측과 통합 데이터 배치 — 운영 반영 완료 (2026-11-16)

- [x] 에이전트·툴의 실제 이벤트 생성·보존·제한된 조회를 연결했다. 수집 로그·원본 stdout/stderr·과거 실패 상태를 구분하고 없던 시각·등급·원문을 만들지 않는다.
- [x] 작업 전체의 로그를 인증된 기존 공유 읽기 경계 안에서 조회한다. 실행·툴·구간/후보를 결속하고 INFO/WARNING/ERROR, 실제 예외와 관련 데이터 이동을 제공한다. 보류·불명 응답의 WARNING이 오류 필터에 가려지지 않도록 보류는 전체 등급, 실제 실패는 ERROR부터 연다.
- [x] 작업 상세를 진행·데이터/결과·로그와 공통 실행 요약으로 정돈했다. 원본·단계 입력·중간 결과·전체 언어/형식·최종 파일을 모으고 검수·복구·SRT 수정 사본 및 명시 실행 경계를 보존했다.
- [x] 기존 운영 환경에 설치하고 실제 모듈·자산·현재 데이터·인증 경계를 재조회했다. 이전 서비스 복구와 원래 작업·호출 기록을 보존하며 보호 작업 재실행·유료 공급자 호출은 하지 않았다.

구현 커밋 `30e3c3ec8b637afebc7ed1458f360f023080dacc`, 검토 트리 `e8d2b24409ed61cbaad3bcb316dede86bc9354f7`를 기존 `renewal`에 게시했다. API·웹·전사/번역 브리지를 교체하고, 컨트롤러 바이너리는 유지한 채 전사·번역 두 미래 실행기 템플릿의 이미지·환경 경로·출처 라벨과 해당 등록 해시만 함께 전환했다. CPU 템플릿과 정책·한도·원본 연결 설정은 유지한다. 실제 공급자 실행은 하지 않았고 새 모델 실행기 인스턴스는 생성하지 않았다.

운영 HTTPS 자산 22개가 동결본 해시와 일치하고, 내부 API `/healthz` 200 및 기존 인증 없는 작업/로그 조회 401을 확인했다. 공개 `/api/healthz`는 기존에 노출되지 않은 경로로 404이며 이를 위해 ingress를 바꾸지 않았다. 설치된 API·브리지 모듈, 기존 보관기의 새 진단 형식 보존, 네트워크 없는 실제 이미지의 진단/비밀정보 차단을 확인했다. #41의 실제 보존 기록은 388개·4개 실행 출처였고 조회 상한 생략 없이 8번째 구간의 저장된 `invalid_response`를 찾았다. 과거 원본 본문을 복원했다는 의미는 아니다.

동일 소스에서 웹 단위 167개와 PC/390px 브라우저 10개를 통과했다. 관측 경로의 관련 백엔드 102개 및 별도 SPEC/QUALITY 검토를 통과했다. 기존 21개 업무 테이블(복구 결정/시도 포함)의 지문, 37개 마이그레이션 이력·ACL과 비대상 서비스 16개를 보존했다. #41의 작업 조회 본문은 배포 전과 같고 95 성공·1 실패 및 별도 선택 가능한 재시도/제외/수동 복구를 읽기 전용으로 재확인했다. 네이티브 백업·이전 컨테이너와 제한된 복구 절차를 보존했다. 실제 사용자 로그인 후 조작, 유료 영상 전체 재실행과 기존 전체 백엔드 회귀 미통과는 별도 미완이며 이 완료에 포함하지 않는다.

### 기존 워크플로우 캔버스와 명시적 복구 재개 — 운영 반영 완료 (2026-11-16)

구현 `2947316c75fa2f650c5800e5e7340ff51e7b2308`, 트리 `a24368aa4897fae509544a3f346430694fecdefb`를 기존 `renewal`에 게시하고 기존 API·웹에만 반영했다. 앞선 별도 카드형 실행 화면을 주 화면에서 제거하고 실제 `WorkflowCanvas`에 저장된 노드·연결·배치를 그대로 사용한다. 설정 편집은 유지하며 작업 보기에는 저장 콜백 없이 실제 상태·현재 내부 단계·구간 진행·선택 태스크 상세를 덧붙인다. 중복 실행 요약 사이드바는 제거하고 기존 통합 로그·데이터/결과·SRT 수정 사본을 유지한다.

복구 동선은 **무시 등 구간 선택 → 선택 내용 확인 → 선택 확정 → 복구 적용·이어서 실행**이다. 선택 확정은 결정 저장과 승인된 구간 처리까지만 수행한다. 추가 호출 0인 제외·수동 결과의 확정에서는 기존 실행 중 노드를 완료 처리하지 않으며 다음 단계를 시작하지 않는다. 기존 `/unit-recovery/continue`가 결과 채택뿐 아니라 후속 enroll/dispatch까지 수행하고 풀 tick도 완료 의존성을 진행할 수 있음을 독립 검토에서 확인했다. 따라서 이를 채택 전용 경로로 취급한 최초 후보는 기각하고 배포하지 않았다. 유료 후속 모델 호출 가능성을 명시한 별도 **복구 적용·이어서 실행** 조작에만 해당 경로를 연결했다. 이미 적용된 결과에는 기존 동일 작업 `/run`을 별도 명시 조작으로 사용하며 새 작업·claim·승인 우회는 만들지 않는다.

두 재개 경로는 동일한 실행/복구 영수증 frontier의 세션 저장 잠금을 공유한다. 미확인 응답을 새로고침·재마운트나 다른 재개 버튼으로 재전송하지 않고 GET으로만 상태를 확인한다. 새로 완료된 후속 frontier에는 다시 명시 조작을 요구한다. 원래 실패한 역할·호출 기록은 유지하되 읽기 전용 상태 투영에서 완료/취소된 NodeRun을 과거 held/unknown 역할 때문에 다시 실패로 표시하지 않도록 수정했다.

최종 후보는 독립 SPEC·QUALITY 승인을 받았고 웹 단위 175개·실제 React 브라우저 42개, 최종 build/typecheck·관련 lint를 통과했다. 실제 API 라우터의 격리 spy 회귀에서 확정 중 채택/enroll/dispatch 없음과 별도 continue 후 한 번의 채택/enroll/dispatch를 확인했다. 해당 라우트·상태 회귀 묶음은 15 passed·32 subtests, DB 환경 의존 4 skipped로 구분한다. 이 테스트는 실제 유료 공급자 실행 증거가 아니다.

운영 HTTPS 자산 22개의 해시, API 내부 health 200, 무인증 작업·로그 조회 401과 실제 설치된 상태 투영 모듈 바이트를 검증했다. API·웹의 정확한 이미지/리비전, 정상 기동·재시작 0, 기존 비대상 실행 서비스 19개와 업무·호출·복구·schema/ACL 불변을 재조회했다. 기존 컨트롤러·브리지·모델/CPU 템플릿·권한·ingress·initializer는 변경하지 않았다. native 백업 목록 검증·이전 컨테이너·명시적 비자동 복구 절차를 보존했다.

반영 후 #41을 기존 API principal로 읽었을 때 성공 95·실패 1, 저장된 복구/선택 0이었고 로그 388개·실행 출처 4개가 유지됐다. 사용자의 무시 선택을 저장 또는 실행된 것으로 추정하지 않는다. 운영자에 의한 #41 변경·재개·유료 호출은 0이다. 로그인된 실제 사용자 조작과 공급자/GPU를 포함한 영상 전체 실행, generic no-broker fallback 및 기존 검수 후 claim/enrollment 결함의 완전 수용은 이번 완료에 포함하지 않는다.

### 전체 수용까지 남은 기능

- [x] 시작 클릭을 서버의 내구성 있는 접수로 이전했다. 일반 입력은 불변 작업 스냅샷을 만들기 전의 접수 기록을 먼저 저장하고, 프론트는 단일 명시 POST와 GET 상태 조회·응답 유실 복구만 담당한다. 구현 `dad53a7463db28fd1beb5236c10b881306ebdf48`은 독립 SPEC·QUALITY 검토 후 기존 API·웹에 반영했다. 동일 실행 코드의 격리 브라우저 종료·API 강제 재시작·같은 접수 재개·합성 CPU 결과 다운로드를 검증했고, 운영 설치 모듈·HTTPS 자산·읽기 전용 PC/모바일 화면과 기존 데이터·큐·서비스 보존을 재조회했다. [구현 계획과 수용 범위](2026-11-17-server-owned-start.md). 실제 운영의 새 접수 처리·원본 전사/번역·공급자 추론은 이번 검증에서 실행하지 않았으며 기존 #41/#42도 재개하지 않았다.
- [ ] 새 업무 에이전트 workflow의 AI 판단과 미연결 제어 유형을 확정 계약에 따라 구현·실행한다. 규칙 기반 분기를 AI 판단이라고 표시하지 않는다.
- [ ] 선택 모델·옵션을 고정한 운영 제품 경로로 전사 → 번역 → 검수 → 자막 → MP4 다운로드·재생을 완주한다.
- [x] 승인된 기존 비공개 브리지의 TLS 신뢰를 복구하고 인증서·호스트명 검증 및 인증 없는 요청 거부를 확인한다.
- [x] API·화면·도구 브리지·수집 컨트롤러·번역 결과 수신기와 새 번역 워커 프로필을 운영 반영한다. 서비스·자산과 실제 진행 조회를 확인한다. 후속 승인으로 구형 전사 워커를 재실행 없이 퇴역시키고 신규 전사 프로필과 전사·CPU 결과 수신기도 갱신했다.
- [x] 비공개 모델 로그의 여러 줄·분할 출력, 캡처 초기화·기록 실패, 기존 본문 재노출을 하나의 출력 경계에서 차단한다. 실제 진단의 수집과 원래 도구 결과·예외를 보존하고 독립 검토 후 배포한다.
- [ ] 검수 후 동일 작업의 claim/enrollment 재개 결함을 기존 증거·의무·권한을 보존하는 정상 경로로 해결한다. 직접 DB 상태 변경이나 과거 결과 재발행으로 우회하지 않는다.
- [x] 전사·번역 등 여러 구간을 처리하는 작업의 공통 복구 조작을 소스 후보에 구현·격리 검증한다. 성공한 구간은 재사용하고 실패 구간마다 선택적 재시도·명시 제외·수동 입력 후 같은 작업의 후속 단계를 준비한다. 후보별 호출과 논리 구간을 구분하며 전사 시간축과 번역 자막 ID·순서·시각을 보존한다.
- [x] 구간 복구를 기존 작업 상세와 실제 API·저장·실행·결과 채택까지 연결하고 운영에 설치한다. 수동/제외 출처와 추가 호출 범위를 표시하고, 초안 저장·화면 재열기·불명 응답으로 모델을 자동 실행하지 않는다. 과거 호출·실패·고정 한도는 보존하며 새 재시도는 별도 유한 승인과 이력으로 남긴다. #41은 실제 기존 증거의 읽기 전용 지원까지 확인했으며 사용자 선택 전 상태 변경·호출은 하지 않았다. 사용자 로그인 후 실제 조작 수용과 구분한다.
- [x] 후보 소진과 결과 불명·활성 호출을 구분하고 취소·늦은 원래 결과·중복 클릭·오래된 화면이 복구 결정을 덮어쓰지 못하도록 격리 검증한다. ASR/MT의 공통 계약을 구현하며 미지원 역할에 작동하지 않는 버튼을 표시하지 않는다. 추후 다른 역할의 어댑터는 별도 구현 범위다.
- [ ] 전사만·자막 번역만·파일 생성·자막 영상·변환·전체 처리의 저장·재열기·실행 동선을 PC/휴대폰에서 확인한다.
- [ ] 작업이 있는 대기열의 일시정지·순서·재개와 실제 후속 실행을 확인한다.
- [ ] 대용량 원본의 실행 전 반복 검증 지연을 별도로 계측·개선한다. 무결성 검사·동의·고정 입력 검증을 생략해서 속도를 높이지 않는다.
- [ ] 변경된 경계의 원자성·취소·늦은 결과·독립 결과 보존을 확인하고, 전체 회귀의 미통과·환경 의존을 구분한다.
- [x] 기존 Windows checkout을 구현 커밋으로 fast-forward하고 교체한 서비스의 이미지·모듈·화면 자산을 검증한다. 레거시의 이전 이미지·기동 시각은 유지한다. 후속 승인의 전사 워커 퇴역, 새 프로필, 웹 UI 커밋과 배포 기록의 문서 전용 후속 커밋을 각각 구분한다.

FaceFusion은 위 완료 목록에서 제외한다. 실제 공급자, 격리 제품 실행, 실제 GPU 추론, 소스 게시, 운영 배포는 별도 상태다. 일부 통과를 전체 제품 완료로 보고하지 않는다.

## 미확정 사항

승인된 기존 비공개 브리지 밖의 CA 변경, 운영 권한·공개 연결 확대, 기존 불명 작업 재실행은 포함하지 않는다. 런타임 계정의 권한을 확대하거나 관리자 DSN으로 우회하지 않는다. 템플릿 등록값을 바꾸는 경우 승인된 프로비저닝 경로를 사용하며, 기존 initializer의 강제 정리는 별도 승인 없이는 수행하지 않는다. 미승인 변경은 분리하되 독립적인 개발과 검증을 중단시키는 이유로 사용하지 않는다.

## 관련 문서

- [제품 요구사항](specs.md)
- [구조](architect.md)
- [실행 계약](../references/high/runtime.md)


## 2026-11-16 — Requested execution UX and temporary single-user candidate (source-only)

- Preserve the saved read-only WorkflowCanvas. Remove the page-tab outer card and the standalone subtitle-editor navigation; retain contextual SRT editing and results.
- Recovery: explicit `제외하고 계속` internally previews, saves zero-call choices, applies and continues with the shared durable frontier fence. Latest user correction removes paid/billing notices from the UI; this does not remove explicit execution/retry approval or authorize extra calls. Paid retries retain separate explicit approval. Existing advanced preparation remains non-dispatching.
- Logs: render only genuinely collected console text in an inert terminal pane; never render stored-failure prose as captured stdout/stderr or manufacture missing originals. Keep private pre-tee provenance and withheld-body policy.
- System and workflow inputs: purpose-first labels, aligned resource/storage rows and no duplicate LNB destinations. Preserve input IDs, saved graph, wires, model revisions and upload contracts.
- Model selection: distinguish provider and connection while preserving explicit pins and fallbacks; fence catalog results to connection/revision. Read-only operating inspection found Vertex Gemini 3.8 revision 1 saved without speech capability, whereas AI Studio revision 2 explicitly includes it. Historical revisions and frozen jobs are not rewritten.
- Provider adapter: pinned SDK offline wire regression removes only SDK-injected Gemini 3.8 sampling defaults. This is not proof of the historical #41 provider failure; its producer timeout and ledger invalid_response remain separate evidence.
- Producer source defaults/validates registry MT tool wait against the admitted provider ceiling plus bounded overhead (135 seconds). Existing explicit 25-second configurations fail closed in the new CLI and must not be silently deployed unchanged. Existing held workers and #41 are not restarted, retried or replayed by this candidate. Future-template configuration/readback is a separate operating gate.
- Optional single-user mode binds an existing active account, retains role/owner/CSRF/Origin/Host checks, and leaves normal login as default. Frontend hides and fences logout only in that explicit mode. Authorized skygg-context observation confirmed the existing Serve HTTPS-to-loopback route is tailnet-only; operating activation remains pending exact-candidate review and readback.
- All implementation is currently a source candidate, not an operating completion. No inference, original-data deletion, grant, new public ingress, unknown-work replay or initializer cleanup is authorized/performed by these verifications.
