# REN-07 연결 데모 · 기존 앱 bytes 보존

- 기준 `renewal` / `50e1342311879062d31713ccd950a0b936183b01`. Codex·코딩 Agent 없이 개인 Mac에서 직접 진행했다. 시작 당시 clean/index empty와 구체 경쟁 writer 미발견을 확인했다.
- **앱 source·저장소 tests·패키지·Vite/검사 설정·backend/shared는 변경하지 않았다.** 새 scratch 데모 harness와 해당 사본·동선 JSON·화면·영상·실행/실패 근거만 추가했다. 증거 디렉터리는 미커밋 candidate이며, 새 제품 기능/문서/태스크를 만들지 않았다.
- `connected-demo.mp4`는 실제 성공 브라우저 실행의 원본 WebM을 H.264로 변환한 연속 녹화다. `journey.json`의 번호/route/viewport/동일 ID와 순서대로 대응한다. 과거 화면을 재사용하거나 서로 다른 티켓을 한 실행처럼 합성하지 않았다.

## 요구–동선/화면–적용–새 실행 근거

1. **인증→탐색/업로드→같은 원본 상세**: 기존 AuthGate 로그인, 정상 빈 보관함, native file input과 기존 queue의 dummy 8-byte 전송을 사용했다. fixture가 첫 등록을 400으로 거부한 뒤 재시도하여 동일 asset의 목록·상세로 이동했다. 100% 전송과 등록 실패를 구분했다. 실제 파일 등록/전송 서버나 미디어 디코딩 성공이 아니다.
2. **같은 원본/입력→workflow→fixture 티켓**: 해당 asset의 API fixture가 명시적으로 제공한 첨부 자막을 선택했다. 입력을 UI로 재사용하며 실제 plan의 유료 단계 표시·확인 전 버튼/form 요청 차단·옵션 변경 후 확인 초기화를 확인했다. 확인 후 동기 이중 submit은 첫 요청 하나만 보냈다. fixture 503 실패 뒤 같은 설정 재시도는 동일 request_id를 유지했고, 성공 callback으로 같은 job route에 이동했다. server idempotency/ownership 검증이나 실제 유료 실행은 아니다.
3. **진행/부분 결과→검수→저장→최종 결과 탐색**: 같은 job의 TRANSLATING 진행과 부분 결과를 표시했다. harness가 명시적으로 AWAITING_REVIEW fixture로 바꾼 후 새로고침/번역 트랙/기존 검수 모달로 이동했다. 507 저장 실패에도 수정 입력·revision7이 유지됐고, 같은 revision7 재시도 응답8을 확인했다. harness가 COMPLETED/결과 fixture를 제공한 뒤 동일 job의 SRT 결과 링크를 확인했다. 단계 전환은 실제 모델·렌더 처리 완료가 아니며 링크 클릭/다운로드·재생 성공도 주장하지 않는다.
4. **390px 같은 자막/원본/티켓→설정·계정/인증**: 저장한 번역 자막을 완료 티켓의 기존 편집 모달에서 읽고 내부 스크롤을 확인했다. 티켓 입력 링크로 같은 원본과 작업 기록에 돌아가 GNB 작업 목록→같은 티켓→설정으로 이동했다. 긴 이름/model ID·키 출처·현재 위치/주행동을 확인했다. 모델 목록 fixture 조회는 연결/추론 성공이 아니다. 설정 재조회 401→기존 세션 만료 AuthGate→fixture 재로그인→계정 로그아웃을 연결했다.
5. **한결/Indigo·현재 위치/상태 의미**: PC와 작은 화면에서 공통 GNB/현재 위치, 원본/티켓 주행동, 긴 fixture 이름·자막·모델 ID, 기존 모달/스크롤과 부분/검수/완료 상태의 시각 표현을 새 실행 화면으로 확인했다. Pretendard/한결 설치·소비 source는 기존 승인 bytes를 유지했다. 새 computed-font 전수 검사나 전체 모바일 편집 동등성 검증은 아니다.

## 새 실행과 기존 근거 재사용의 구분

- **이번 새 실행**: Node `v22.22.2`, 설치된 Playwright/Chromium, scratch `playwright.config.cjs`의 단일 연결 시나리오. 실제 결과 `1 passed (21.9s)`. 18개 캡처 시점은 한 시나리오의 동선 표식이지 18개 테스트가 아니다. 원 로그 `connected-run.log`, assertion/실제 API 순서 `execution.json`, 동선 `journey.json`, 재현 사본 `*.cjs.txt`.
- 성공 실행은 API 요청을 전부 local fixture로 처리하고 다른 origin을 차단했다. 알 수 없는 API/외부 요청 및 uncaught page error는 없었다. DELETE·실제 설정 저장은 수행하지 않았다. 비-GET 인증 후 요청의 CSRF header는 fixture 세션 값과 대조했으나 실제 서버 CSRF/ownership 집행을 증명하지 않는다. console의 400/503/507/401 및 미디어/thumbnail 404는 의도한 fixture 오류로 `execution.json`에 그대로 남겼다.
- **재사용, 새 PASS로 더하지 않음**: REN-03 queue/verification/파일 및 업로드 UI, REN-04 revision 충돌/실패·입력 보존/검수, REN-05 입력/재사용/request_id/늦은 응답/명시적 확인, REN-06 auth-session 3개·Chromium 3개와 settings conflict 재조회 근거를 참조한다. 기존 screenshot 정규화/국소 실행도 기존 기록과 분리 유지했다. 관련 후보의 현재 bytes는 `reused-evidence-parity.json`에 직접 해시 대조했다.
- REN-03의 `hangyeol.json`만 이후 승인된 REN-04 textarea 추가로 달라졌으며, 현재 파일은 REN-04 후보와 일치한다. REN-03 당시 전체 후보가 현재와 모두 같다고 확장하지 않는다. upload queue/API/verification·인증 등의 보존 코드와 최신 생산 파일은 현재 HEAD의 tracked blob parity도 대조했다.
- 저장소 `apps/web/AGENTS.md`의 pre-commit lint/format/npm-test/build 규칙을 확인했다. **이번에는 commit도 생산 코드 변경도 없으므로** 변경 없는 앱의 REN-06 lint/format/타입 포함 build/browser types/doctor 및 선행 관련 결과를 재사용하고 같은 전체 검사는 반복하지 않았다. 이후 공유 마감은 별도 승인/규칙에 따른다.
- Node22 원 `npm test`의 `--test-isolation=none` 실패와 기존 Node24 원 실행26 PASS, registry E401·audit/lookup·Radix 경고·원 RED/교정 전 실패를 그대로 유지한다. 이번 연결 PASS로 이를 지우거나 Node22 원 npm-test 전체 PASS라고 바꾸지 않는다.

## 이번 harness 교정/원 실패

- `failed-executions/attempt-1.log`: 최초 workflow plan은 자막 선택 전 `subtitle_artifact_id:null`인데 harness가 선택 후 ID만 허용해 실패했다. 실제 초기 null/선택 후 artifact 두 요청을 구분하도록 **fixture만** 교정했다. 실패 teardown 때 pending 요청의 Vite→미실행 localhost API proxy ECONNREFUSED도 원 로그에 보존했다. 실 API/모델 호출 성공은 없었다. 이후 abort-on-error/page-close 정리로 teardown 요청이 실제 backend에 넘어가지 않게 했다.
- `failed-executions/attempt-2.log`: 브라우저 실행 중 프로젝트 안에 journey JSON을 저장하면서 Vite watcher reload가 발생해 in-memory file/queue가 재마운트됐다. trace의 반복 auth/session과 queue→불완전 세션 전환을 확인했다. **live 산출물을 scratch로 격리**하고 Vite 종료 후 증거를 복사했다. proxy/allowedHosts/HMR/앱 로직을 약화하거나 변경하지 않았다. 같은 시나리오의 최종 attempt-3이 통과했다. 앞선 실패를 새 테스트 수로 더하지 않는다.
- 원 실패 로그·harness 사본·trace를 함께 보존했다. 이 교정은 제품 회귀 수정이 아니며, 새로 발견되어 앱을 고친 회귀는 없다.

## 안전 경계·운영 가안·리뷰 요청

- 이름/자막/계정/응답은 모두 명시적 안전 fixture다. 실제 비밀번호·API 키/token·운영 설정·사용자 원본/자막은 사용/기록하지 않았다. 화면의 `서버 연결됨`, `키 있음`, 모델 목록/저장 성공도 local API fixture 상태일 뿐 실서버 인증/공급자 연결/추론 성공이 아니다.
- 실서버/실모델·실미디어 clock mapping/integrity·재생/다운로드는 미검증. dummy 8-byte의 프로토콜 동작 확인은 실미디어 검증을 대체하지 않는다.
- REN-05 frontend 명시적 유료 확인 UI/handler 보완은 유지됐다. **서버 과금 확인 집행·직접 API 우회 방지·서버 계획과 확인의 원자적 일치는 별도 미구현/미검증**이다.
- 실제 키 등록/삭제·운영 설정 변경·provider/GPU/유료 호출·사용자 데이터 삭제 없음. Codex/다른 코딩 Agent·공유 한결 원본 변경·기본 브랜치 merge/force push·배포/registry 발행 없음.
- 운영 가안: 연결 실행/관련 확인 완료 → 혜지 기획/UI 검토 → 필요한 국소 보완만 → 승인 후 증거 공유 마감/전체 종료 별도 판정. 확정 마감일을 발명하지 않는다.
- **REN-07은 진행 중/리뷰 대기 요청**이며 S1도 진행 중이다. REN-07/S1 자동 완료·후속 feature 전체 착수는 하지 않는다.
