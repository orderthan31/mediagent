# REN-04 · 티켓 상세·진행·자막 검수 구현 리뷰 후보

## 기준과 범위

- `renewal`, HEAD `f43e420108d6f773a0a34e0c4a4ca941833cfea4` 이후의 **미커밋 candidate**. Codex/코딩 Agent 없이 개인 Mac에서 직접 구현했다. 승인·공유 마감·태스크 종료는 아직 아니다.
- JobDetail에 입력 영상, 실제 workflow 요청 단계, 현재 상태/단계, 부분 결과와 현재 허용된 검수/수정·다운로드 행동을 한결 UI로 연결했다. 내부 job/asset/API/status 이름은 바꾸지 않았다.
- StageProgress는 기존 전사/번역 분량·인코딩 비율을 한결 Progress로 표시한다. 인코딩은 native progress와 같은 0~1 범위로 제한한다. 요청된 단계 목록과 실제 현재 단계를 구분하며 없는 skip/분기 상태나 전체 완료 추정을 만들지 않는다.
- SubtitleEditor에는 한결 Button/Input/Textarea와 빈 트랙 EmptyState를 적용했다. 완료 티켓은 자막 저장, 검수 대기는 초안 저장과 기존 최종 출력 행동을 구분한다. 기존 저장/검증/revision/dirty/키보드/트랙·페이지 상태 코드는 보존했다.
- 미리보기 불가, 읽기 전용 상태, 부분 결과와 콘텐츠 차단/실패는 정상 완료와 구분한다. 미확인 자막은 0개로 확정하지 않는다. 완료 상태에 남은 cancel_requested를 실행 중 정리 대기로 표시하지 않는다. 취소 정책을 추가한 것은 아니다.
- 작은 화면의 편집 영역이 기존 flex 높이에 눌리는 문제와 시작/종료가 갈라지는 legacy grid 충돌을 consumer scope에서 보완했다. 전체 모바일 편집 동등성 검증은 아니다.

## 실제 실행 근거

- `checks.json`: 앱 lint/format, 타입 포함 build, browser TypeScript, 관련 job-failure **4개**, Chromium **3개 흐름**, doctor 통과. 단순 파일 생성/육안 추측이 아니다.
- Chromium 3개 흐름: 실제 상태/부분 결과, 완료 티켓의 원문·번역/수정/저장/readonly 응답, 검수 대기의 409 충돌·507 실패와 입력/revision 보존.
- `last-checks.json`: 완료/실패/중단 이후의 잘못된 정리 대기 안내를 국소 보완한 뒤 관련 상태 흐름 **1개**와 변경 lint/타입 포함 build를 다시 확인했다.
- `mobile-final-checks.json`: 마지막 mobile grid 보완과 결과 링크/빈 트랙의 완료 티켓 흐름 **1개**를 다시 확인했다. browser 타입·변경 lint·최종 build도 통과했다. 위 숫자를 합쳐 새 전체 검사 수로 보고하지 않는다.
- RED/이전 화면은 별도 파일에 보존했다. `review-red.log`, `completed-red.log`, `mobile-editor-red.log`, `empty-editor-red.log`, `cancel-notice-red.log`, `mobile-grid-red.log`와 `editor-mobile-before-*.png`는 현재 성공 화면이 아니다.
- `protected-files.json`: 승인 공통/스토리지/AuthGate/API/WorkflowDialog/Vite 등 13개 파일이 HEAD bytes와 같고, JobDetail/SubtitleEditor의 business prefix도 HEAD와 byte-identical이다. backend/shared diff는 없다.
- Textarea는 실제 installer로 선택 설치했다. installer 원본은 `installer-originals/textarea.tsx.txt`, 로컬 editable 파일에는 앱 lint/format 정합화만 했다. owner hash는 수동 갱신하지 않았다.

## 화면과 fixture 경계

- `review-desktop.png`: 입력 영상·요청 흐름·검수 대기·부분 결과/기존 검수 진입.
- `editor-failed-desktop.png`: PC 409 후 507 저장 실패, 수정 입력과 기존 revision 보존.
- `completed-desktop.png`, `editor-saved-mobile.png`: 완료 티켓 편집/저장과 390px 모달 내부 스크롤·시간/문구 읽기. 시작/종료의 같은 행 배치를 bounding box로 확인했다.
- `progress-desktop.png`, `blocked-desktop.png`, `queued-mobile.png`: 실제 지원 상태를 API fixture로 표현한 진행/차단·실패/대기.
- `readonly-editor.png`, `empty-editor.png`: 명시적 403 읽기 전용 응답과 빈 트랙의 기존 입력 UI.
- 모든 화면/동선은 **명시적 API fixture**다. stream/thumbnail은 의도적으로 404이며, 실서버 인증·실모델·실제 미디어 재생·실파일 다운로드 성공이 아니다. 다운로드는 URL/탐색 연결까지만 확인했다. 실제 사용자 원본/자막 삭제, GPU/유료 호출은 하지 않았다.

## 안전 계약·미확인·경고

- API·WorkflowDialog와 backend/shared를 그대로 보존했다. SubtitleEditor의 저장/범위 검증/revision 및 JobDetail의 seek/preview business prefix도 bytes가 같다. 이 사실이 실서버 clock mapping/input integrity나 유료 확인의 실행 검증을 뜻하지 않는다.
- 현 frontend WorkflowDialog에는 plan 타입의 paid_stages는 있지만 명시적 유료 확인 UI가 구현돼 있지 않다. 이번에 새 확인 정책을 만들거나 해당 확인 절차가 fixture로 통과했다고 주장하지 않는다. 후속 범위 판단용 기존 공백으로 제출한다.
- 현재 타깃 frontend에는 clock mapping 전용 필드/UI가 없다. 원래 초 단위 입력/검증·seek 연결은 보존했지만 실미디어 mapping/integrity 성공은 미검증이다. 없는 engine 상태/검증 계약을 발명하지 않았다.
- 최종 build의 Radix use-client 지시문 무시 경고는 로그 원문에 남겼다. 과거 npm registry E401·Node22 원 npm-test 옵션 실패/Node24 결과·audit/lookup 경고는 해소됐다고 확대하지 않는다. 이번에는 관련 국소 검증만 했고 원 전체 테스트·실서버 검사는 반복하지 않았다.
- 운영 가안은 현재 제출 → 기획/UI 리뷰 → 필요한 국소 보완 → 승인 후 일반 공유 마감이다. 확정 작업일이나 마감일을 설정하지 않는다. REN-05/S1 종료·기본 브랜치 병합/force push·공유 한결 source/CLI 변경·배포/registry 발행은 하지 않았다.
