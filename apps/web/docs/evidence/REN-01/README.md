# REN-01 · AuthGate Indigo checkpoint

## 실제 변경

- 기존 `renewal` checkout에서 Codex 없이 직접 구현했다. 한결 공유 소스·CLI는 수정하지 않았다.
- 보존된 `0.0.1` 발행본과 별도로 `0.0.2-adapter.1` 미발행 후보를 vendor 상대 file devDependency로 설치했다. 패키지·lock·실제 bin·무결성은 engineering receipt와 provenance에서 구분한다.
- Vite의 기존 callback/loadEnv/proxy/allowedHosts는 유지하고 Tailwind import/plugins 두 줄만 추가했다. 실제 init/add가 owner 기록과 로컬 Theme/TextField/Button/Input/FormField·Pretendard를 생성했다.
- 기존 AuthGate 로그인·연결·재시도 화면을 한결 토큰 기반 중앙 카드로 정리했다. 로그인·연결 대기·오류·busy를 구분하고, 오류에는 danger 색상, 주 행동과 focus에는 Indigo를 사용한다.
- 기존 accept/login/logout/effects 및 signed-in gate prefix는 원본과 byte-identical이다. native username/password required·maxlength·autocomplete·Enter 제출과 실패 후 password clear를 보존했다.
- 기존 두 전역 스타일을 `legacy` layer로 함께 묶어 원래 순서와 파일을 보존했다. 설치 UI utilities가 기존 generic button/input/label 규칙에 덮이지 않도록 했다. Theme 적용은 unauthenticated AuthGate에 한정했다. 로그인 뒤 workspace를 한결 리뉴얼 완료로 표시하지 않는다.
- 새 로컬 editable UI 6개 TS/TSX 파일은 기존 앱 ESLint/Prettier 계약에 맞게 arrow/braces/format만 조정했다. 원본 설치 기록 hash는 변경하지 않았고 doctor가 local source edits를 info로 표시한다. 공유 원본·artifact는 그대로다.

## 확인된 것

- 실제 installed bin version/inspect, init dry-run/init, add dry-run/add, doctor, tokens validate, 한결 lint 수행.
- 앱 lint·format·production typecheck/build, browser tests 별도 typecheck 통과.
- 기존 인증/코딩규칙 관련 Node 테스트 7개 및 Chromium AuthGate 브라우저 테스트 4개 통과.
- development/production/adapter-empty에서 Vite가 읽은 server config를 원래 callback과 비교해 같음을 확인했다. scratch 원본은 module resolution만 절대 경로로 연결했다.
- 실제 HTTP로 로컬 Pretendard 요청 200 및 browser font loading을 확인했다.
- 1440px desktop·390px mobile에서 로그인 렌더와 가로 overflow를 확인했다. 브라우저 pageerror는 없었다. 직접 screenshot을 보고 필수 표시는 레이블과 같은 줄로 보완했다.

## 화면과 검증 경계

- `login-desktop.png`, `login-mobile.png`: **명시적 API fixture**의 로그인 상태를 실제 앱에 렌더한 화면. 실서버 인증 성공 증거가 아니다.
- `connecting.png`, `connection-error.png`, `login-error.png`: 명시적 fixture의 상태 렌더. 연결 긴 오류, retry, native required, Enter, busy, 실패 password clear, 로그인 성공 후 기존 workspace 및 세션 만료 재진입을 확인했다.
- `actual-disconnected.png`, `actual-disconnected.json`: **API fixture 없음**. 실제 로컬 Vite proxy의 `/api/auth/session`이 500으로 실패했고 기존 API 서버는 실행하지 않았다. 이 실제 실패와 재시도 버튼을 한결 UI로 표시한 증거다. 서버 인증 성공/백엔드 기능/미디어 실행을 검증했다고 주장하지 않는다.
- 기존 `npm test`의 Node22 `--test-isolation=none` 실패, Packages E401, audit high 경고는 과거 Notion 기록에 보존한다. 대체 좁은 test 결과를 기존 npm test PASS로 바꾸지 않는다.
- 기본 shell Node16으로 preview 시작이 한 번 실패했고 explicit Node22 binary로 정상 실행했다. 사용자의 기본 shell 설정을 바꾸지 않았다. 실제-profile browser 도구는 기본 브라우저 지원 제한으로 실패하여 별도 headless Chromium을 사용했다.
- 한결 lint는 실제 Tailwind compiler/diagnostics=[]로 종료했지만 shadcn bundled grammar 관련 경고를 출력했다. 이를 전체 CSS/접근성 인증으로 보고하지 않는다.

## 실행

Node22.22.2/npm10.9.7을 선택한 shell에서:

```sh
npm ci
./node_modules/.bin/hangyeol inspect
./node_modules/.bin/hangyeol doctor
npm run lint
npm run format:check
node --test tests/auth-session.test.mjs tests/conventions.test.mjs
node node_modules/@playwright/test/cli.js test tests/browser/auth-gate.spec.ts
npm run build
```

브라우저 테스트는 Chromium 설치가 필요하며 고정된 dev port 5179를 사용한다. screenshot 재실행은 evidence의 PNG를 덮어쓴다. 원문 실패/trace는 scratch와 Notion에서 별도로 보존한다.

## 남은 것

- 혜지의 목적·동선·정보 위계·실제 UI 기획 검토.
- 실제 서버 계정 인증·업로드/미디어 실행·다른 화면 전수 회귀·스프린트 수락은 이번 checkpoint의 완료 증거가 아니다.
- 후속 태스크는 자동 착수하지 않는다. 기본 브랜치 병합/force push/운영 배포/registry 발행/GPU·유료 실행은 하지 않았다.

소스 기준 HEAD: `57d34e9995edf5e322dfa26acdd899513f4038d5` (시작점). 이번 결과는 **미커밋 candidate**이며 exact candidate files/digest는 receipt에 기록한다.

태스크: https://app.notion.com/p/3f971e5d553e81349e37d91f4ed7b1a7
