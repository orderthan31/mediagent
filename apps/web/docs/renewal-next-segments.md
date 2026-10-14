# renewal · REN-01 이후 작업 구간 운영 가안

이 문서는 다음 작업 인계를 위한 **운영 가안**이다. 확정 마감일·태스크 배정·착수 승인이 아니다. REN-01 AuthGate 첫 적용은 기획/UI 승인됐으며, 아래 구간은 혜지의 별도 순차 인계 후 시작한다.

## 다음 인계 후보: 공통 탐색과 영상 목록의 첫 연결

- 실제 소스: `src/VideoWorkspace.tsx`, `src/video-workspace.css`, `src/workspace-polish.css`, 기존 전역 스타일 연결.
- 먼저 다룰 화면: 영상 목록의 현재 위치·검색·빈/오류 상태와 업로드 주 행동. 기존 hash route, 영상 선택, 업로드 queue/resume/파일 판정은 보존한다.
- 설치 후보: `shell` 또는 `gnb`/`lnb`, `search-field`, `composition`의 ListPanel, `list-row`, `empty-state`, `button`/`icon-button`. 실제 props와 현재 화면 동선을 확인해 필요한 것만 선택한다. 모든 항목 설치나 목록 전체 재작성은 전제가 아니다.
- 경계: 영상 상세·작업 상세·검수 편집·워크플로우 설정을 같은 구간에 몰아넣지 않는다. 이번 구간에서는 새 엔진·미디어/GPU/유료 실행을 추가하지 않는다.
- 예상 작업 구간: **구현과 관련 국소 검증 1~2 작업일 가안**, 이후 혜지의 화면/동선 리뷰. 인계 시점·기획 보완·지원 API 확인에 따라 조정한다. 날짜나 확정 완료 약속으로 사용하지 않는다.
- 인계 시 결정할 항목: 탐색 shell 선택, 영상 목록/업로드의 정확한 첫 화면 범위, UI 상태의 실데이터/명시적 fixture 확인 경계.

## 후속 파일·컴포넌트 맵 (순차 후보)

- 영상 상세와 작업 생성: `VideoWorkspace.tsx`의 영상 상세 route, `WorkflowDialog.tsx`. 후보 `dialog`, `text-field`, `select`/`native-select`, `checkbox`, `form-field`, `button`. 기존 생성 payload와 native 이벤트 계약 보존.
- 작업 목록·상세·진행: `VideoWorkspace.tsx`, `JobDetail.tsx`, `StageProgress.tsx`. 후보 `list-row`, `badge`, `progress`, `progress-stepper`, `empty-state`/`error-state`. 실제 진행/실패/검수 대기/결과 상태를 서로 구분.
- 자막 검수/수정: `SubtitleEditor.tsx`, 기존 editor CSS. 후보 `dialog`, `textarea`, `text-field`, `button`, `action-group`. revision·저장·취소·dirty·focus 계약은 실제 화면별 확인 뒤 별도 태스크로 다룬다.
- 설정: `SettingsPage.tsx`, `settings.css`. 후보 `form-field`, `text-field`, `select`/`native-select`, `button`, 필요한 `alert`. 실제 인증정보 처리와 provider 정책은 UI 리뉴얼을 이유로 바꾸지 않는다.
- 로그인/연결: `AuthGate.tsx`의 REN-01 승인 화면. 후속 구간에서 임의 재디자인하지 않는다. 실서버 계정 인증은 현재 미검증이며 화면 승인과 별개다.

후속 구간별 세부 예상 기간은 실제 인계 범위가 정해진 뒤 기록한다. 위 후보를 기존 Notion 태스크 ID에 임의 재배정하거나 동시에 시작하지 않는다.

## 보존·실행 기준

- 프로젝트 canonical: `orderthan31/mediagent`; 구 별칭은 `video-subtitle`. 작업 경로는 `/Users/austinko/dev/mideagent`, 개발 브랜치는 `renewal`이다.
- 한결 도구는 로컬 미발행 `0.0.2-adapter.1` candidate이며 기존 발행본 `0.0.1`과 vendor/provenance·이전 package/lock을 보존한다. registry 발행·Packages 인증 성공으로 표현하지 않는다.
- 기존 Node22 `npm test` 옵션 실패·E401·audit 경고 기록은 유지한다. 마감 시 원래 test script는 별도 Node24 실행 결과와 구분한다. 일반 앱 host 설치/빌드는 Node22 기준을 유지한다.
- 기존 코드·WIP·원격 feature·다른 머신의 미확인 작업을 건드리지 않는다. 기본 브랜치 병합/force push/운영 배포는 승인 범위가 아니다.

태스크: https://app.notion.com/p/3f971e5d553e81349e37d91f4ed7b1a7
