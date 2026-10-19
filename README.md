# mideagent

원본 하나와 저장한 워크플로우 하나를 티켓 단위로 처리하는 미디어 에이전트 제품이다.
현재 `renewal`에서 PostgreSQL·독립 에이전트·미디어 저장소 구조로 리뉴얼하고 있다.

## 개발 진입점

- [작업 규칙](docs/rules/README.md) · [문서 관리](docs/rules/docs-manage.md)
- [제품 기획](docs/plans/specs.md) · [구조](docs/plans/architect.md) · [디자인](docs/plans/design.md)
- [현재 확정 태스크](docs/plans/tasks.md) · [미확정 기획](docs/plans/ideation.md)
- [개발·격리 실행 계약](docs/references/high/runtime.md) · [문서 인덱스](docs/README.md)

## 현재 상태

- `apps/web`: React/Vite, DEV 합성 목업과 opt-in 실제 API 경로.
- `apps/api`: FastAPI. 리뉴얼 API는 명시 DB/저장소로 구성하며 import나 startup에서 migration·큐 소비를 하지 않는다.
- `packages/shared`: PG 저장소·계약·미디어 유틸리티와 CPU 에이전트 진입점의 개발 소스.
- `workers/media`: 아직 이관되지 않은 레거시 패키지. `agents` 명칭/실행 구조 전환은 진행 태스크이며 완료로 표기하지 않는다.

격리 PG와 합성 미디어를 사용한 업로드·티켓·검수·CPU 처리·다운로드 동선을 확인했지만
현재 신규 runtime은 개발 WIP이며 브라우저 MP4 재생 실패가 남아 있다.
S3-compatible 오브젝트 스토리지·브로커 연결, 최종 회귀·소스 공유와 실제 운영 전환은 완료되지 않았다.
이 README는 GPU/실모델·유료 요청·기존 큐 소비·사용자 원본 처리나 기존 Docker 스택 실행을 지시하지 않는다.

## 이전 자료

구형 파일 저장소·단일 pipeline·GPU/유료 POC·과거 배포/검증 자료는
[archive](docs/references/archive/README.md)에서 과거 이력으로만 참조한다.
과거 성공 기록은 현재 renewal의 기능 수용이나 실행 권한이 아니다.
