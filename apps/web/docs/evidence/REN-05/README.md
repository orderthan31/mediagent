# REN-05 · 실제 워크플로우 설정/명시적 확인 UI 리뷰 후보

## 기준과 변경 범위

- `renewal` / `b82ed476a6f012a757c910673f297ccd1f384e69` 이후 **미커밋 candidate**다. 시작 때 clean·구체 경쟁 writer 미발견을 확인했고, 기존 별도 기획 http.server는 그대로 유지했다. 개인 Mac에서 Codex/코딩 Agent 없이 직접 구현했다.
- source/test 후보는 WorkflowDialog.tsx, 새 workflow.css, workflow-confirmation.spec.ts다. 이미 설치된 한결 Button/Badge/Textarea를 실제로 재사용했다. native select/checkbox·dialog/form은 기존 값·접근성/선택 동작을 유지하고 consumer scope의 토큰 스타일로 연결했다. 새 UI 패키지나 공유 원본을 설치/수정한 것은 아니다.
- 적용 원본·입력/옵션·요청 단계/재사용·계획 대기/실패/누락·유료 단계 확인과 시작 행동을 구분했다. 긴 자막 이름은 native select 아래에 전체 이름/언어/개수/기존 revision을 따로 표시한다.

## API/기존 계약 조사

- 실제 plan endpoint: `apps/api/app/api/asset_routes.py`의 `/api/videos/{asset_id}/workflow-plan`. 입력 소유권/자막·음성 유효성을 확인하고 shared workflow_plan을 호출한다. 기존 request body의 template/subtitle_artifact_id/audio_job_id/subtitle_mode를 유지했다.
- 실제 생성: `apps/api/app/api/workflow_routes.py`의 `/api/videos/{asset_id}/jobs`. WorkflowCreate는 request_id/template/subtitle_artifact_id/audio_job_id/options를 받고 extra 필드를 금지한다. 같은 request_id에 다른 asset/identity이면 409, 같은 identity이면 기존 결과를 반환하며 plan을 서버에서 다시 계산한다. 이 스키마나 backend는 수정하지 않았다.
- `packages/shared/video_service/workflows.py`는 현재 6개 template와 순차 stages/reused를 지원하고, stages 중 transcribe/translate를 paid_stages로 반환한다. 이번 UI는 실제 응답을 표시하며 자체 가격·새 유료 분류 규칙을 만들지 않았다.
- 장기 node canvas/병렬/합류/Decision/검수 노드 engine은 이번 template UI에 구현한 것이 아니다. 가짜 노드나 설정 저장 성공을 만들지 않았다.

## 명시적 확인 UX

- stages/reused/paid_stages가 유효한 배열인 계획을 받은 뒤에만 시작 가능하다. plan 대기/HTTP 실패/paid_stages 누락은 무료 확정이 아니라 생성 차단으로 표시하며 계획 재확인을 제공한다.
- 유료로 표시된 실제 단계를 보여주고 별도 required checkbox로 확인받는다. 버튼 disabled뿐 아니라 같은 form의 submit handler도 현재 계획·입력 유효성·동기 in-flight lock·확인 스냅샷을 검사한다. 직접 SubmitEvent를 보내도 확인 전 요청은 나가지 않는다.
- 확인은 asset/base와 생성 payload 전체(입력·모든 옵션), 계획 응답과 요청 generation에 묶었다. template/자막/음성/옵션/설명·원본 전환과 계획 재확인은 기존 확인을 승계하지 않는다. 변경 handler는 즉시 활성 계획/확인 ref를 폐기하고, abort/sequence로 늦은 이전 응답을 무시한다.
- 같은 설정의 생성 실패 재시도에는 기존 request_id를 유지하고, 실제 전송 payload가 달라지면 새 request_id를 쓰는 기존 계약을 유지했다. 동기 in-flight lock으로 같은 이벤트 턴의 이중 submit도 막는다. 자막 가져오기 body의 job_id/track/revision 및 artifact_id 선택·음성 초기화도 유지했다.
- paid_stages가 명시적으로 빈 배열이면 해당 계획에 유료로 표시된 단계가 없다고만 안내한다. 비용이 없다는 보장은 하지 않는다.

## 실행 결과와 실패 기록

- `checks.json`: 앱 lint, format-check, 타입 포함 production build, browser test TypeScript, doctor PASS. CSS와 새 browser test는 명시적 Prettier write로도 정리했다.
- Chromium **4개 관련 흐름 PASS** (`browser-final.log`), pageerror 수집 검사 포함:
  - 확인 전 submit 요청 없음, 확인 후 이중 submit 1회, 같은 payload 재시도의 request_id 보존.
  - 모든 현재 옵션/설명·음성·원본 전환·계획 갱신의 확인 초기화, 변경된 payload의 새 request_id.
  - 계획 대기/실패/paid_stages 누락 시 submit 차단, 늦은 이전 무유료 계획 응답이 새 유료 계획을 대체하지 않음.
  - 자막 필수 선택·가져오기 409/재시도와 revision body, artifact 재사용, 빈 paid_stages 계획과 기존 생성 callback→티켓 route 연결.
- 첫 RED는 기존 화면의 명시적 유료 확인 UI 부재다(`confirmation-red.log`). `browser-flows.log`의 3개 실패는 native select의 getByLabel exact 기대와 StrictMode의 초기 중복/abort 요청 개수 가정이었다. accessible combobox 조회와 보류 응답의 전체 해제로 fixture를 교정했고 생산 입력 이름·기존 엔진은 바꾸지 않았다.
- `remaining-flows.log`의 preview pageerror는 새 fixture가 실제 `/jobs/{id}/preview` 대신 잘못된 `/subtitles/preview`를 가로챈 문제였다. 실제 route로만 교정한 뒤 최종 4개가 통과했다. 실패 원문과 teardown 중 ECONNREFUSED 로그를 삭제하거나 실제 서버 성공으로 바꾸지 않았다.
- 최종 build에는 기존 Radix use-client 무시 경고가 있다. 과거 registry E401·Node22 원 npm-test 옵션 실패/Node24 결과·audit/lookup 경고는 해소됐다고 보고하지 않는다. 이전 태스크/원 전체 검사는 반복하지 않았다.

## 화면/보존/검증 경계

- settings-desktop, paid-unconfirmed-desktop, paid-confirmed-error-desktop: PC 원본/입력/설정과 확인 전·후/생성 오류.
- imported-subtitle-mobile, paid-confirmed-mobile, reuse-no-paid-mobile: 390px의 긴 입력·전체 이름/필수/재사용·명시적 확인/기존 행동. 모달 내부 스크롤 화면이며 전체 모바일 동등성 검증은 아니다.
- plan-loading-mobile, plan-missing-mobile, plan-failed-mobile: 미확인/누락/실패를 무료로 취급하지 않는 실제 렌더.
- 보호 파일 17개가 HEAD bytes와 같고, backend/shared 및 설치된 한결 UI diff는 없다(`protected-files.json`). 승인 공통/스토리지/검수·API/인증·Vite/package/lock/설치 기록은 보존했다.
- 모든 API/생성/가져오기와 상태·데이터는 **명시적 fixture**다. 생성 후 티켓 route도 fixture job이며 실서버/실모델/실미디어 처리 성공이 아니다. stream/thumbnail은 의도적인 404다. NVIDIA 옵션 확인은 fixture 요청값 검증이지 GPU 실행이 아니다. 실제 사용자 원본/자막 삭제·GPU/유료 호출은 하지 않았다.
- **frontend 확인 UX의 보완**이다. 현재 API에는 서버가 검증하는 확인 토큰/plan_id·가격/결제 필드가 없고, 직접 API 호출의 과금 확인 집행이나 생성 시 재계산된 서버 계획과 브라우저 snapshot의 원자적 일치까지 보장하지 않는다. 새 서버 필드/과금 정책을 추가하지 않았다. 실제 clock mapping/integrity·실서버/실모델/재생/다운로드도 계속 미검증이다.
- 운영 가안은 이번 제출→기획/UI 리뷰→필요 국소 보완→승인 후 공유 마감이다. 확정 날짜/작업일을 새로 만들지 않았다. commit/push·REN-05/S1 완료·REN-06 이후 착수·기본 브랜치 merge/force push·공유 한결 source/CLI 변경·배포/registry 발행은 하지 않았다.
