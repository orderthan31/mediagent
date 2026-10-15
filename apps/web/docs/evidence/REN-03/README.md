# REN-03 — 스토리지·업로드 리뉴얼 제출 근거

## 실행 기준·범위

- Mac `/Users/austinko/dev/mideagent`, `renewal`, HEAD `82d4e778683a49c2b72031ccb72dd47c7054313b`. 착수 시 clean; 구체 경쟁 writer 미발견. 별도 기획 디렉터리의 기존 http.server는 repo writer가 아니며 중지하지 않았다.
- Codex/코딩 Agent 없이 직접 구현. 현재 미커밋 candidate, commit/push·배포·GPU/유료 실행 없음.
- 영상 목록/선택·원본 상세 정보·upload queue/session의 표현 및 보조 행동을 리뉴얼했다. 티켓/자막 검수·워크플로우·설정 내부는 재디자인하지 않았다.

## 설치·변경 이유

실제 installed `hangyeol add badge progress empty-state --dry-run`→`add`로 필요한 editable UI 3개를 설치했다. 기존 Theme/TextField/Button/GNB를 유지한다. Progress가 선언한 `@radix-ui/react-progress@1.1.17`을 exact runtime pin/lock으로 연결했다. shared source/CLI·owner hash는 수정하지 않았고 설치 원본은 installer-originals에 보존했다. 로컬 generated UI의 앱 lint/format 문법만 정합화했다.

영상 목록은 원본/결과 등록 출처 Badge, 파일명, 시간·용량·날짜 메타데이터와 항상 보이는 `영상 열기`로 구성했다. 행 전체의 실제 hash link를 유지하여 작은 화면에서도 명시적 탭 대상과 상세 진입을 연결한다. 재생시간이 없으면 `재생시간 미확인`이며 앞쪽 구분점이나 임의 시간값을 만들지 않는다.

원본 상세는 native video/정보 dl/다운로드/삭제를 분리한다. 기존 새 작업·자막 입력·작업 기록의 동선과 정책은 유지한다. native video는 preload=none이며 재생 검증을 위해 실미디어를 호출하지 않았다.

업로드는 파일별 카드로 상태 Badge, 원래 byte 기반 Progress, 전송량/전체량, 원문 오류와 보조 행동을 구분한다. 전송 대기·전송 중·영상 확인 및 등록 중·일시정지·실패·완료, 저장된 불완전 세션/등록 대기를 모두 표현한다. 재개/재시도/제거/세션 삭제 확인은 기존 queue/action에 연결한다. 완료 항목의 무효 일시정지 행동만 표시하지 않고 제거는 유지한다. 작은 전송량은 0.0 MB로 반올림하지 않고 실제 B/KB로 표시하며 전송 정책은 바꾸지 않는다.

업로드가 없을 때는 compact EmptyState로 목록을 밀어내는 빈 공간을 줄였다. 조회 미확인/실패에서는 저장된 업로드의 부재를 확정하지 않는다. 기존 영상 검색/개수/최신성 주의·업로드 활성은 유지한다.

공유 Confirm의 native dialog/showModal/cancel/busy/action 로직은 그대로이고 제목 접근성·한결 취소/삭제 Button·한정 스타일만 정리했다. 이 표현은 기존 작업 삭제에서도 공유되지만 티켓 내부 화면 전체 변경은 아니다.

## 실제 검사

원 명령과 exit은 checks.json, final-checks.json, queue-final-checks.json 및 `.log`에 보존했다.

- 앱 lint 최종 PASS, format check PASS, 타입 포함 최종 production build PASS, browser test 타입 검사 PASS.
- 설치 doctor PASS. 로컬 editable 문법/format 조정은 source.edited info로 유지하며 hash를 조작하지 않았다.
- 기존 upload-queue/upload-verification/video-file 관련 테스트 10개 PASS. 전체 26개나 AuthGate 전체를 반복한 것이 아니다.
- Chromium 5개 흐름 검사 PASS: 정상 빈/조회 실패·이전 목록, PC 출처/검색/상세, 기존 직렬 queue, 불완전 세션/삭제 확인, 390px 영상 선택→상세/삭제 취소. pageerror 0을 검사했다.
- queue/세션 2개만 추가 화면 수집, queue 1개만 B/KB 표시·등록 실패/재시도 보강 후 국소 실행 PASS. 이를 서로 다른 추가 테스트 수나 합산 전체 회귀로 집계하지 않는다.
- 명시적 8-byte 파일 fixture로 실제 기존 queue/입력/API client를 호출했다. mismatch size 오류, 전송 50%와 앞선 전송의 대기, pause→다음 파일 등록, registration failure→retry→done, resume→done, chunk 400 오류 원문, 목록에서 제거를 확인했다. 저장된 READY complete POST와 불완전 세션 file chooser, DELETE는 명시적 fixture에서만 발생했고 403/error/취소를 확인했다. 실제 사용자 파일/원본을 전송·삭제하지 않았다.
- PC 1440×1000/작은 화면 390×844에서 파일명·메타데이터·행 열기·queue/session 배치를 캡처했다. 작은 화면 목록/세션/queue에서 document 가로 넘침 없음 확인.
- protected-files.json: 18개 보호 파일 HEAD와 byte-identical. VideoWorkspace의 workspaceLinks부터 main JSX 직전까지 business prefix(실제 queue 생성/전송·입력·action·hash route·polling·jobRows 포함)도 byte-identical. 승인 AuthGate/GNB/공통 shell CSS와 API/queue/integrity/파일판정·워크플로우/검수·설정은 원본 유지.
- 최종 산출 CSS에서 Progress custom property를 좁게 확인했고 실제 화면에서 50%/100% 막대를 확인했다.

## 실패·경고·미확인

- 기존 모바일 열기/미확인 재생시간 slice의 RED와 업로드 카드 slice의 RED를 보존했다. B/KB 표시의 4 B / 8 B 기대는 0.0 MB / 0.0 MB에서 RED였고 UI 표현만 보완해 GREEN.
- 첫 lint는 fixture 테스트의 if braces에서 실패, 앱 규칙을 완화하지 않고 test syntax만 보완해 PASS. 첫 sessions 검사는 native picker를 단일 선택으로 가정했지만 기존 chooseResume는 ref만 바꾸고 input multiple을 즉시 재렌더하지 않아 실제 picker는 multiple이었다. 기존 native 입력/first-valid-file resume 동작을 바꾸지 않고 picker 열림 확인으로 기대를 교정했다. 새 단일 선택 계약을 검증했다고 주장하지 않는다.
- RED에서 pending fixture를 finally 해제하며 teardown 직전 poll 요청의 proxy ECONNREFUSED 로그가 있었고 원 로그를 보존했다. 최종 PASS 실행에는 이 proxy 오류가 없다.
- production build는 Radix progress/primitive의 `use client` module directive 무시 경고와 함께 exit0였다. 경고 없는 build로 보고하지 않는다.
- 설치 시 npm audit 2 high 경고; 자동 audit fix/업그레이드를 하지 않았다. 패키지 threat-intelligence 조회 deadline 경고도 악성 증거/검증 완료로 치환하지 않는다.
- 모든 새 화면·상태·수치는 명시적 API fixture다. 목록/detail의 20 MB/날짜/시간은 fixture metadata이고 queue 파일은 실제 테스트가 만든 8-byte dummy이며 사용자의 실영상이 아니다. 미리보기 poster/stream은 fixture 404로 두었으므로 native video 껍데기만 렌더했다. 실제 다운로드/재생, 실서버 인증/소유권·실파일 업로드·서버 등록 결과/재개는 미검증이다. GPU/유료/운영 배포/registry 발행은 하지 않았다.
- REN-01의 E401·Node22 npm test 옵션 실패/Node24 통과·audit 및 미검증 이력과 REN-02 증거는 그대로 유지했다.

## 운영 가안·검토

이번 실제 구현/국소 확인은 본 작업 세션에서 후보 제출까지 진행했다. 다음 순서는 기획/UI 리뷰→필요한 국소 보완→승인 후 일반 commit/push 마감이며 확정 마감일은 없다. 이전 REN-02 1~2 작업일 가안을 이번 전체 마감으로 복사하지 않는다. 리뷰로 새 범위가 정해지면 그 범위에 한해 운영 가안을 조정한다.

REN-03 진행 중/리뷰 대기로 제출하며 S1 완료·REN-04 착수·기본 브랜치 merge/force push·shared source 변경·배포 승인을 뜻하지 않는다.
