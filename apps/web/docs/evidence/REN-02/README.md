# REN-02 첫 구간 — 공통 탐색·레이아웃 리뷰 후보

- 기준: `renewal`, HEAD `f1bf5ba32fa324e17e6f58480a5dbcbbe5bf4bfc`의 미커밋 candidate. Codex/코딩 에이전트 없이 Mac에서 직접 구현.
- 시작 시 clean/구체 writer 미발견 확인 후 진행 중으로 변경했다. 현재 dirty는 이 첫 구간의 변경이며 자동 commit/push/배포하지 않았다.
- 첫 구간 제출이며 REN-02 전체/S1 완료 또는 기획 승인 아님.

## 변경 목적·동선

기존 접는 사이드바를 실제 설치한 한결 GNB 상단 탐색으로 바꿨다. 영상 보관함(`#/`) → 기존 영상 상세(`#/videos/:asset_id`), 작업 목록(`#/jobs`) → 기존 작업 상세(`#/jobs/:job_id`), 설정(`#/settings`)만 제공한다. 없는 스토리지/티켓/서빙 메뉴는 만들지 않았다. 영상 상세는 영상 보관함, 작업 상세는 작업 목록을 현재 탐색으로 선택한다.

Indigo Theme와 기존 Pretendard를 소비하고 현재 위치, 제목/설명, 업로드 Button, 검색 TextField의 위계를 구분했다. 작은 화면은 GNB의 실제 disclosure 메뉴를 사용하고 이동/Escape 후 닫힘을 확인했다. 새 CSS는 공통 shell/제목/검색만 담당한다. 기존 영상 row·상세, 업로드 queue/resume 구현은 REN-03으로 남겼다.

연결되지 않은 목록을 정상적인 빈 보관함으로 오해하지 않도록 연결 확인 안내와 빈 상태 표시 조건만 보완했다. API 요청/재시도/폴링 계약은 변경하지 않았다. 정상 연결에서 검색 없음·빈 보관함·업로드 파일 선택 행동은 유지한다.

## 실제 검증

`checks.json` 및 각 `.log` 참조.
- 앱 lint / format check / TypeScript 포함 production build: PASS.
- Chromium 국소 검사 8개: PASS. REN-02 관련 4개와 기존 AuthGate 4개.
- PC 1440×1000 / 작은 화면 390×844에서 실제 앱 렌더. 화면 첨부는 명시적 API fixture 데이터다.
- 현재 메뉴 aria-current, 검색/지우기, 없는 검색 결과, 정상 빈 상태, 영상 선택→기존 상세, 업로드 native file chooser 열기, 작은 화면 가로 넘침 없음, 메뉴→작업/설정 route·검색 초기화·Escape 닫힘, 설정 오류 표시 확인.
- AuthGate 회귀: Indigo/font loading, native required/busy/password clear, 연결 대기/실패/재시도, 로그인→workspace→세션 만료 확인. AuthGate 생산 소스는 불변이고 기존 테스트의 signed-in Theme 기대만 갱신했다.
- 승인된 REN-01 스크린샷은 보존했다. 재검사 출력은 `auth-regression/`에 분리하고 테스트에 선택적 AUTH_EVIDENCE_DIR을 추가했다.
- installed `hangyeol add gnb --dry-run`→`add gnb` 및 doctor PASS. 로컬 editable GNB의 앱 lint/format 정합성만 조정했다. 공유 source/CLI와 owner hash는 변경하지 않았고 doctor source.edited info는 그대로다.
- `protected-files.json`: AuthGate, Vite, API clients, SettingsPage, JobDetail, upload-queue 소스 HEAD 대비 byte-identical.

## 실패 이력·검증 경계

첫 PC 검사는 미구현 탐색/테마에서 RED였다. 이후 헤더 border-top 기대 0px 대비 실제 3px RED를 확인하고 공통 CSS의 테두리만 0/하단 1px로 보완하여 GREEN. 목록 연결 실패 상태 RED 후 실패/정상 빈 상태를 분리하여 GREEN.

작은 화면 검사에서 설정 제목을 `설정`으로 예상했던 조회는 실제 기존 `AI 공급자 설정`과 불일치했다. 생산 설정 제목을 바꾸지 않고 테스트 기대를 바로잡았다. 첫 영상 선택 검사 종료 시 아직 요청 중이던 subtitles 요청이 해제되어 proxy ECONNREFUSED 로그가 1회 있었고, 기존 상세의 실제 자막 빈 상태까지 기다리도록 수정했다. 최종 8개 실행에는 이 proxy 로그가 없다. 최초 format check는 installer 갱신 hangyeol.json 포맷에서 실패했고 포맷만 적용 후 PASS.

실서버 인증/실데이터 목록/실제 파일 전송·queue/resume·GPU·유료 실행은 이번 fixture 검사의 증명이 아니다. picker만 열고 파일 업로드를 실행하지 않았다. REN-01의 E401·Node22 npm test 옵션 실패/Node24 통과·audit 이력과 실서버 인증 미검증은 유지한다. 전체 회귀·운영 배포·registry 발행·기본 브랜치 병합·REN-03 착수는 하지 않았다.

## 리뷰 요청

공통 탐색·현재 위치·제목/검색/업로드의 목적 적합성과 PC/작은 화면 UI 검토를 요청한다. 구현/기술 국소 PASS와 혜지의 기획 수락은 별개다. 상태는 진행 중 / 리뷰 대기다.
