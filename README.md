# mideagent

원본과 저장한 workflow를 불변 티켓으로 처리하는 미디어 에이전트 제품이다.
현재 `renewal`은 명시 CPU 실행·저장소·검수 기반이며 운영 전환이나 GPU/실모델 완료를 뜻하지 않는다.

## 개발 진입점

- [작업 규칙](docs/rules/README.md) · [문서 관리](docs/rules/docs-manage.md)
- [기획](docs/plans/specs.md) · [구조](docs/plans/architect.md) · [디자인](docs/plans/design.md) · [태스크](docs/plans/tasks.md)
- [실행·저장 계약](docs/references/high/runtime.md) · [MQ req/res](docs/references/high/agent-protocol.md)
- [격리 검증](tests/renewal/README.md) · [문서 인덱스](docs/README.md)

## 소스 구조

```text
apps/api/app/             renewal API·controller·명시 launcher
apps/web/                 DEV-only 목업 / 인증된 renewal UI
agents/cpu/               cli.py · server.py · broker.py (평탄한 패키지)
agents/gpu/               facefusion.py · vad.py · models.py (선택 엔진)
packages/shared/video_service/
  contracts/              versioned MQ request/response JSON Schema
  postgres/               DB 상태·불변 정의·outbox/inbox·fleet
  cpu_agents.py           bounded CPU 역할 구현
  object_agent.py          DB-free 원격 CAS 실행
  rabbitmq_transport.py   opt-in AMQP 전송·검증
```

Python import 이름은 `mideagent_cpu`, `mideagent_gpu`이며 각 `pyproject.toml`의 package-dir로 실제 위 폴더에 매핑한다. 동일 이름의 하위 소스 폴더를 다시 만들지 않는다.

구형 `agents/media`, 파일 큐·고정 workflow·SQLite 계정/설정 API, legacy Docker overlays와 `scripts/`의 일회성 POC·복구·벤치마크·배포 스크립트는 제거했다. 예전 화면 검증 PNG/로그도 소스 트리에서 제거했으며 Git 이력은 보존한다. 실제 원본·자막·DB·키·백업은 정리 대상이 아니다.

## 실행 책임

- controller만 workflow·승인·lease·취소 세대·검수·DB/outbox/inbox를 소유한다.
- CPU agent는 역할 하나의 입력·옵션·출력 계약만 처리한다. 원격 전달은 owner-scoped CAS 참조이며 DB·전체 graph·다음 노드·provider 키는 받지 않는다.
- 일반 사용자는 원본·작업만 접근한다. workflow·agent·serving·system·account는 관리자 전용이다.
- GPU 엔진은 별도 소스/선택 이미지에 보존했다. 실제 GPU 패키지·모델 설치, MQ consumer 연결과 GPU hardware 검증은 미완료이며 준비 완료로 광고하지 않는다.

## 설치·검증

Python 3.12+, FFmpeg/FFprobe와 Node가 필요하다. 격리 환경에서:

```sh
python -m pip install -e 'packages/shared[postgres,models,objects,amqp,verify]' -e apps/api -e agents/cpu -e agents/gpu
```

DB·합성 미디어·브라우저 검증의 실제 명령과 opt-in 조건은 [격리 검증 안내](tests/renewal/README.md)를 따른다. 기본 API startup은 migration·큐 scan·worker·provider/GPU 호출을 시작하지 않는다.

## Compose와 bootstrap

root Compose는 `renewal` profile의 API/web 레시피다. API는 `app.server --bootstrap-file`을 사용하며 LLM key·provider·model을 environment에 입력받지 않는다. 앱 설정의 정본은 관리자 DB다. 관리자 write-only 키 저장·교체·폐기는 DB 암호문과 불변 connection revision으로 관리하며 pinned model resolver→주입 text wire를 검증했다. 기본 model network 실행은 disabled다. 삭제한 환경변수 fallback을 복구하지 않는다.

프로세스 부팅에 필요한 DB 접속·콘텐츠 root·origin·listen/cookie 설정만 별도 private bootstrap 파일로 제공한다. 이것은 DB가 열리기 전 필요한 인프라 bootstrap이며 모델/provider 설정 파일이 아니다.

private 디렉터리의 `api.json` 구조:

```json
{
  "database_dsn_file": "/run/bootstrap/database.dsn",
  "content_root": "/data/content",
  "allowed_origins": ["http://127.0.0.1:8080"],
  "host": "0.0.0.0",
  "port": 8000,
  "secure_cookies": false
}
```

`database.dsn`은 운영자가 승인한 접속 문자열을 별도 파일에 보관한다. 두 파일은 Git/build context 밖에 두고 런타임 UID/GID `10001:10001`의 읽기 권한을 확인한다. bootstrap은 알 수 없는 필드와 provider/모델/key 필드를 거부하며 값은 오류에 출력하지 않는다. 위 HTTP/cookie 예시는 loopback 접근용이며 TLS 운영 환경은 HTTPS origin과 secure cookie를 사용한다.

`MIDEAGENT_BOOTSTRAP_DIR`은 해당 private 디렉터리의 절대 경로다. `docker compose --profile renewal config --quiet`는 정적 검증이며 배포가 아니다. `/healthz`는 프로세스 liveness만 확인하며 DB 준비 완료를 의미하지 않는다. 실제 migration·DB/스토리지 준비·image build/run은 별도 수용 단계다. API는 외부에 publish하지 않고 web만 `127.0.0.1:8080`으로 publish한다. MagicDNS/원격 배포는 이 레시피만으로 완료되지 않는다.

`agents/cpu/compose.yaml`은 명시 stdin/local-CAS, `compose.amqp.yaml`은 외부 broker/S3를 전제로 한 선택 레시피다. 선택 `infra/compose.yaml`은 별도 TLS broker/PG/S3 설치 recipe, `compose.transport.yaml`은 root API/results/operator 연결 overlay다. 신규 private bootstrap·수동 초기화·권한·복구는 [배포 절차](docs/rules/deploy.md)를 따른다. 실제 격리 broker/S3/독립 CPU 왕복은 수용했지만 운영 배포·원격 fleet 제어·GPU agent 실행은 별도다. 기본 startup에 consumer를 붙이지 않는다. 이미지 graph는 `docker buildx bake -f docker-bake.hcl --print api cpu cpu-amqp api-broker gpu`로 조회한다. 공통 FFmpeg base는 실행 서비스가 아닌 build layer다.

## 이전 자료

[archive](docs/references/archive/README.md)는 과거 이력일 뿐 현행 실행 안내가 아니다. Git history rewrite·master 통합·운영 데이터 청소는 이번 정리에 포함하지 않는다.
