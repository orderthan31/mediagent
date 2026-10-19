# mideagent

원본 하나와 저장한 워크플로우 하나를 티켓 단위로 처리하는 미디어 에이전트 제품이다.
현재 `renewal`의 opt-in CPU 실행 경로이며 운영 전환이나 GPU/실모델 완료를 의미하지 않는다.

## 개발 진입점

- [작업 규칙](docs/rules/README.md) · [문서 관리](docs/rules/docs-manage.md)
- [제품 기획](docs/plans/specs.md) · [구조](docs/plans/architect.md) · [디자인](docs/plans/design.md)
- [현재 태스크](docs/plans/tasks.md) · [실행·저장 계약](docs/references/high/runtime.md)
- [격리 테스트](tests/renewal/README.md) · [문서 인덱스](docs/README.md)

## 현재 구현

- `apps/web`: DEV 목업과 capability-gated PostgreSQL API 경로를 구분한다.
- `apps/api`: 검증 업로드·불변 workflow revision·티켓·노드·검수·승인·취소/복구 API. startup은 migration·큐 소비를 하지 않는다.
- `agents/cpu`: 분석·오디오 추출·자막 생성·인코딩·검증의 개별 CLI와 S3 객체 기반 단일 명령 진입점.
- `agents/media/media_agent`: import·패키징·스크립트 참조까지 전환한 legacy 호환 코드. 단일 파이프라인은 의존 코드가 있어 보존하며 실행/청소 CLI는 명시 승인 없이는 차단한다.
- 로컬 CAS 또는 명시 S3-compatible CAS를 사용한다. S3 경로는 API/에이전트의 별도 캐시 사이에서 HTTP 객체 전달을 검증했으며 공유 볼륨이 필요 없다.
- 업로드 원본과 처리 결과 원본은 보존하고 별도 WebM(VP9/Opus)을 생성한다. 플레이어는 WebM, 다운로드는 원본과 WebM을 구분한다.

격리 PostgreSQL·합성 미디어·loopback S3 프로토콜 에뮬레이터를 사용한다. 에뮬레이터 검증은 실제 MinIO 제품 검증·다른 머신 배포·브로커 연동을 뜻하지 않는다.
기존 legacy 회귀의 실패와 전체 web lint/format 부채는 [실행 계약](docs/references/high/runtime.md)에 분리한다.
이 README는 GPU/provider/유료 호출·기존 큐 소비·사용자 원본 처리·운영 Docker 실행을 지시하지 않는다.

## 이전 자료

구형 MVP·GPU/유료 POC·과거 배포 기록은 [archive](docs/references/archive/README.md)의 과거 이력이다.
운영 데이터·키·백업은 이번 명칭 전환이나 미사용 소스 정리의 삭제 대상이 아니다.
