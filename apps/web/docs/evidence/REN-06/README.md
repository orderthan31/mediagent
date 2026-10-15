# REN-06 · 현재 공급자/모델 설정·계정 메뉴 구현 리뷰 후보

## 기준·실제 적용

- renewal / c2b54c96e17ea802831467c74a6c0813b1787670 이후 미커밋 candidate다. 시작 시 branch/HEAD/clean·구체 경쟁 writer 미발견을 확인했다. 기존 별도 기획 http.server는 유지했다. Codex/코딩 Agent 없이 개인 Mac에서 직접 진행했다.
- SettingsPage에 이미 설치된 한결 Button/Input/Badge를 재사용하고 settings-renewal.css의 consumer scope로 원본 설정·공급자별 키 상태·전사/번역·폴백·조회/저장 행동을 구분했다. native select/datalist/checkbox와 현재 입력값/지원 목록은 유지했다. 새 패키지나 shared source/CLI 변경은 없다.
- 전사는 현재 Gemini, 번역은 기존 기본/폴백 공급자 선택과 모델 ID·조건을 지원한다. 긴 모델 ID는 입력 아래에 전체 값이 줄바꿈되어 읽힌다. 빈 폴백 모델의 미사용과 폴백 API 사용료 주의, 저장 후 다음 작업/재시도부터 적용되는 의미를 표시한다. Worker별 등록/발견·분산 serving·로컬 inference·새 인증/과금 backend를 구현한 것이 아니다.
- 등록 키/환경변수 키/키 없음과 공급자별 변경 대기·등록 키 삭제 예정/취소를 별도로 표시한다. 조회 버튼에 현재 공급자를 명시하고 기존 has_api_key/새 키 입력/삭제 예정의 조회 가능 조건을 유지했다. 모델 목록과 키 존재는 연결·추론 성공이 아님을 안내한다.
- 저장 실패 시 일반 설정/삭제 예정은 유지되고 비밀키는 초기화되어 재입력이 필요하다는 기존 정책을 설명한다. 저장 성공은 응답 후에만 표시한다. 새 입력/조회 때 과거 성공 notice를 지워 이전 성공을 현재 저장 완료로 오인하지 않게 했다. 모델 조회에 추가한 로직은 과거 notice 초기화 한 줄이다.
- AccountMenu만 한결 Button·명시적인 로그아웃 문구와 긴 계정명 배치를 적용했다. 승인된 REN-01 AuthGate 본체(로그인·연결/실패/만료 화면 포함)는 재구현하지 않았다.

## 기존 API와 보존 근거

- apps/api/app/api/settings_routes.py: GET/PUT /api/settings/llm, GET /api/settings/llm/models?provider=... 및 기존 session/origin/CSRF 경계를 조사했다. public 설정은 원래 키 값 없이 has_api_key/key_source/credentials 상태를 반환한다. 모델 조회는 서버에 저장된 해당 공급자 키 또는 환경변수 키를 사용한다. 실제 provider를 호출해 확인하지 않았다.
- packages/shared/video_service/llm_settings.py: 기존 model/provider/flag/revision·credential_updates 검증과 충돌, 등록 키 우선/환경변수 해석을 읽기만 했다. 설정 저장소/실제 환경변수 값·키 파일은 읽거나 변경하지 않았다.
- SettingsPage의 load/save handler가 HEAD와 byte-identical이다. revision/payload/credential_updates 생성, 일반 입력 유지와 비밀키 초기화 정책은 변경하지 않았다. AuthGate export 본체도 HEAD와 byte-identical이며, 계정 메뉴 JSX만 바뀌었다.
- API/auth-session/승인 공통·스토리지/검수/workflow 확인 UI·기존 설정/auth CSS·Vite/package/lock/설치기록 등 20개 파일은 HEAD bytes 그대로다. backend/shared와 설치된 한결 UI diff도 없다(protected-files.json).
- AuthGate의 기존 한결 Theme/TextField/Button·REN-01 승인 화면을 재사용한다. 기존 인증 흐름과 현재 계정 메뉴의 fixture를 좁게 확인했으며, 이전 AuthGate 전체 브라우저 검사를 반복하거나 승인 evidence를 덮어쓰지 않았다.

## 실제 실행과 화면

- checks.json: lint·format-check·타입 포함 production build·browser test TypeScript·doctor 통과. 기존 auth-session 검사 3개 PASS(쿠키/CSRF, 401/로그인 실패 구분, 늦은 401이 새 로그인에 영향을 주지 않음).
- Chromium 관련 3개 흐름 PASS: 키 출처/변경·삭제 취소·조회 대상과 조건/409 충돌·재입력/저장 응답 적용, 초기/모델 조회·저장 대기/503 실패·필수 입력, 계정 메뉴·로그아웃 503/204·로그인 실패/비밀번호 초기화·세션 만료.
- 사진의 sticky header가 문서 중간에 찍히지 않도록 screenshot 직전 scrollTop을 정규화했다. evidence-checks.json의 후속 실행도 같은 3개 흐름이며 추가 테스트 수로 합산하지 않는다. 생산 소스는 변경하지 않았고 해당 test의 타입/lint도 통과했다.
- revision-checks.json은 동일 첫 흐름만 국소 재확인한 기록이다. 409를 같은 revision 재전송으로 해소하는 듯한 fixture 기대를 피하고, 충돌 직후 입력 보존 → 명시적 새로 불러오기(revision 8/입력·삭제예정 초기화) → 재입력 후 PUT revision 8/응답 revision 9로 실제 계약에 맞췄다. 생산 조회/저장 handler는 바꾸지 않았다. 이 실행을 새 흐름 수로 더하지 않는다.
- settings-desktop.png: 현재 공급자·키 출처/조회·긴 모델 ID·Gemini 전사/번역/폴백과 비용 안내.
- conflict-mobile.png, save-failed-mobile.png: 390px 충돌/저장 실패·일반 입력 보존·비밀키 재입력/삭제 예정.
- loading-desktop.png, load-failed-desktop.png, saving-desktop.png: 실제 미확인/조회 실패와 저장 대기(완료 아님).
- saved-mobile.png: fixture 저장 응답 후 초기화/키 상태·다음 작업/재시도 적용 안내. account-mobile.png: 긴 계정명/로그아웃과 설정. expired-mobile.png: 기존 AuthGate 세션 만료와 빈 비밀번호 재입력 화면.
- settings-red.log는 기존 UI의 상태/주의 표현 부재를 확인한 RED다. 이후 source/fixture 실패는 없었으며 원 RED와 초기/최종 실행을 보존했다. 최종 build의 기존 Radix use-client 무시 경고를 원문 보관했다. 과거 E401·Node22 원 npm-test 옵션 실패/Node24 결과·audit/lookup 제약을 해결됐다고 보고하지 않는다.

## 비밀정보·실행 경계

- API 설정/모델 조회·저장/키 변경·삭제 예약·로그인/로그아웃/세션 만료는 전부 명시적 API fixture다. password/key/token은 fixture-only로 식별된 가짜 상수만 사용했다. 실제 비밀번호/API 키/token·운영 설정 값은 읽거나 첨부·로그에 넣지 않았다. 비밀키 입력은 password type이며 본문 텍스트로 출력되지 않음을 검사했다. screenshot의 입력값도 가짜 값/마스킹 또는 초기화 상태다. raw trace ZIP은 제출하지 않는다.
- 실제 키 등록/삭제·운영 설정 변경·provider/모델 목록 HTTP·GPU/유료 호출·사용자 원본/자막 삭제는 하지 않았다. 모델 목록과 키 상태를 실제 연결/인증·추론 성공으로 보고하지 않는다. 실서버/실모델·clock mapping/input integrity·재생/다운로드는 계속 미검증이다.
- REN-05의 frontend 명시적 유료 확인 UI/handler 보완은 그대로 유지한다. 서버 과금 집행·직접 API 우회 방지·서버 계획과 확인의 원자적 일치는 별도 미구현/미검증이며 이번 설정 UI로 해결됐다고 하지 않는다.
- 운영 가안은 이번 제출→기획/UI 리뷰→필요 국소 보완→승인 후 공유 마감이다. 확정 작업일/마감일은 새로 만들지 않았다. commit/push·REN-06/S1 완료·REN-07 이후 착수·기본 브랜치 merge/force push·공유 한결 원본 변경·배포/registry 발행은 하지 않았다.
