# 리뉴얼 실행·저장 계약

## 목적

격리 CPU 경로의 실제 책임·재현 진입점과 운영 전환 경계를 관리한다.

## 현재 상태

검증 업로드·불변 workflow/티켓·PostgreSQL 상태·독립 CPU 프로세스·로컬/S3-compatible CAS·검수/승인/취소/복구·WebM과 이중 다운로드를 구현했다. renewal 관리자 경계와 실제 로컬 CPU 인스턴스 기동/축소/드레인/분산도 격리 검증했다. 실제 컨테이너 제어·MinIO 제품·브로커·다중 머신·GPU/provider·운영 전환은 미검증이다.

## 주요 내용

### 실행·데이터 보호

- API는 명시 DB/콘텐츠 저장소만 받는다. DSN fallback·startup migration·queue scan·실모델 import/call이 없다.
- 작업 snapshot과 정의 revision은 불변이며 동의는 현재 입력/설정/검수와 결속한다. 동의 저장·실행 요청·사람 검수 저장/확정을 분리한다.
- DB delivery reservation 뒤 지정 명령 하나만 실행한다. 독립 에이전트에는 DB/전체 workflow/후속 노드/세션을 보내지 않는다.
- S3 attempt marker는 조건부 쓰기(If-None-Match)를 사용한다. 완료 receipt가 없는 중복은 결과 불명으로 막고 자동 재실행하지 않는다. 결과 ack는 애플리케이션 DB commit 뒤에만 호출한다.
- 취소·lease 만료·이전 generation 결과는 격리한다. 복구는 새 draft 자식 작업이며 검증된 완료 결과만 재사용하고 새 실행 승인을 요구한다.
- 미지원 모델·Loop/Fallback·추가 입력 binding은 편집 지원과 구분하여 실행 승인을 닫는다.

### 저장소와 WebM

- 원본 상한 256 MiB, chunk 4 MiB. `ContentStore`는 private local CAS, `S3ContentStore`는 기존 bucket의 명시 prefix/owner/CAS를 사용한다.
- S3 adapter는 bucket 생성/나열/삭제·서명 URL 발급을 하지 않는다. 키는 프로세스의 명시 환경변수 이름으로만 읽으며 명령/정의/DB에 raw credential을 넣지 않는다. 원격 HTTPS(테스트 loopback HTTP 예외), 직접 SHA/byte 검증, 불변 참조를 사용한다.
- private cache는 로컬 작업공간일 뿐 정본이 아니다. 앱/에이전트는 공유 볼륨 없이 별도 cache에서 S3 HTTP로 원본/결과를 교환한다.
- 업로드 원본과 처리 결과 원본은 보존한다. 별도 `webm-vp9-opus-v1` 파생본(VP9/Opus, 최대 1280×720)을 생성하고 원본 SHA와 연결한다. 원본을 WebM으로 바꿔 저장하지 않는다.
- `/api/videos/{id}/stream`은 WebM 재생, `/download`는 업로드 원본이다. `stream?download=true`는 WebM 첨부 다운로드다.
- 작업 산출물 endpoint는 결과 원본이며 `/preview`가 WebM이다. 양쪽 `?download=true`는 해당 파일 첨부 다운로드다. 고정 영상 입력 플레이어도 `/preview`를 사용한다.
- WebM 생성 실패 시 원본은 다운로드 가능하며 실패 상태를 보존한다. GET에서 변환하거나 지원 여부를 모르는 원본으로 플레이어를 자동 fallback하지 않는다. 현재 WebM은 bounded CPU 처리이며 장시간 미디어의 비동기 스케줄링은 잔여다.

### renewal 관리자 경계와 명시 CPU fleet

- 일반 사용자 허용 동선은 원본 목록/상세·작업 목록/시작/상세다. 나머지 직접 URL은 차단하고 관리 API는 현재 세션의 관리자 권한을 서버에서 확인한다. 세션 확인/본인 로그아웃은 관리 기능과 구별한다.
- `/api/settings/*`, 계정과 `/api/admin/agents/*`는 관리자용이다. 일반 작업 선택은 별도 `/api/work-entry/{workflows,catalog,inspect,preview,create}`를 사용한다. 관리자 제공 workflow의 출처와 revision은 작업에 불변 저장하며 원본·작업 소유자는 실제 사용자다.
- migration `007_agent_fleet.sql`이 목표 설정/revision·변경 이력·실제 인스턴스와 노드 배정을 저장한다. 운영 DB에 자동 적용하지 않는다.
- `--allow-cpu --manage-cpu`는 private local ContentStore 전용이며 S3/다른 executor와 중복 연결하지 않는다. 서버 시작이나 조회는 프로세스를 켜지 않는다. 관리자 configuration PUT 후 실제 ready handshake를 받은 CPU 프로세스만 준비로 집계한다.
- 종류별 0~8개, 전체 활성/드레인 포함 최대 16개, 인스턴스당 1개로 제한한다. DB 잠금으로 명령을 예약하고 idle 인스턴스의 마지막 배정 시각을 기준으로 분산한다. 중복 controller는 advisory ownership lock으로 차단하며 다른 controller PID를 채택/종료하지 않는다.
- 비활성화·축소는 신규 배정을 막고 이미 예약한 명령을 마친 뒤 종료한다. 자동 작업 검색/소비/재실행은 없다. 자리가 없으면 명시 작업은 대기 상태를 유지하며 후속 명시 호출 또는 향후 scheduler가 필요하다.
- 독립 instance는 private stdin/stdout의 제한 JSON 명령과 owner/CAS 참조만 받는다. DB·웹 세션·provider 키·workflow traversal을 받지 않는다. CPU 결과의 요청 digest와 attempt/generation을 검증한다.
- 연결되지 않은 얼굴교체/모델 실행환경은 미연결로 표시하고 활성화 요청을 거부한다. 실제 얼굴교체 on/off가 구현됐다는 뜻이 아니다. 컨테이너 adapter·health·자원 정책은 별도 잔여다.
- 기본 API는 agent package/Torch/FaceFusion을 설치하지 않는다. `legacy-api`는 기존 paused Compose의 기본 API 호환 target이다. API의 직접 upload/preview FFmpeg는 여전히 남는다. CPU 이미지와 선택 legacy media 이미지 및 CPU Compose profiles는 분리했지만 이미지 빌드·실행은 하지 않았으며 기존 GPU/VAD/얼굴교체 overlay의 API 내 엔진 동작도 호환 수용하지 않았다.

### 독립 실행 진입점

Python 3.12+와 FFmpeg/FFprobe가 필요하다. `packages/shared[postgres,models,objects]`, `apps/api`, `agents/cpu`를 격리 환경에 설치한다. CPU 에이전트 자체는 PostgreSQL 패키지나 API 연결 없이 동작한다.

- `mideagent-analyze`, `mideagent-extract-audio`, `mideagent-generate-subtitle`, `mideagent-encode`, `mideagent-validate-video`: 각 고정 역할의 JSON stdin/stdout 명령. `--input-root`/`--output-root`는 명시 private root다.
- `mideagent-object-agent --agent <role> --owner <owner-id> --config-env <explicit-name>`: 원격 CAS를 사용하는 단일 명령. 설정은 endpoint/bucket/region/prefix/cache_root와 access_key_env/secret_key_env 이름만 포함한다.
- `python -m app.renewal_server --dsn-env <name> --origin http://127.0.0.1:<port> --content-root <root> --allow-cpu`: 로컬 전용 launcher.
- 같은 launcher의 `--manage-cpu`를 명시해야 관리자 상세에서 로컬 CPU fleet을 조작할 수 있다. CPU package를 같은 승인된 환경에 설치해야 하며 이 옵션 없이 조작 가능으로 표시하지 않는다. 실제 운영에 이 명령을 자동 적용하지 않는다.
- S3 실행은 content-root 대신 `--object-config-env <app-config-name> --agent-config-env <agent-config-name>`을 사용한다. 앱과 agent config의 private cache_root를 다르게 지정한다. 이 launcher는 공개 production server가 아니다.
- `agents/media/media_agent`는 기존 API 의존성을 위한 legacy 호환 코드다. CLI는 `--allow-legacy-queue` 없이는 queue/cleanup을 실행하지 않으며 이 플래그의 존재가 현재 운영 실행 승인은 아니다. 기존 WORKER_* 환경변수·과거 DB/protocol 식별자는 데이터 호환성을 위해 임의 변경하지 않는다.

### 검증과 남은 부채

- 전체 renewal 격리 회귀는 61개 통과(관리자 fleet/일반 사용자 동선을 포함한 네 브라우저 경로, skip 없음), web 단위 테스트는 44개 통과했다. 실제 기동 실패·프로세스 종료, ready handshake 후 DB 기록 실패 주입에서도 상태/소유 프로세스 제어가 유지되는지 검증했다. 변경 Python lint/format, 변경 runtime 화면 lint/format, 타입/build, compose 정적 구성 검사를 별도로 통과했다. compose 검사는 스택 실행이 아니다.
- 테스트는 명시 disposable PostgreSQL의 임의 schema와 합성 미디어만 사용한다. S3 테스트는 임시 loopback 프로토콜 에뮬레이터이며 종료 후 서버를 닫는다.
- 코덱 지원 Chrome만 사용하는 우회와 구분한다. H.264/AAC 미지원 Chromium에서도 WebM 원본/산출물 재생, 재생 시간 진행·영상 크기, 원본/WebM 실제 다운로드와 SHA를 확인한다. FHD/cover/unfolded는 브라우저 에뮬레이션이지 실기기 수용이 아니다.
- 현재 legacy suite는 27 failed / 558 passed / 1 skipped이며 직전 exact SHA `ae057f643ebf8bb6c93c1088cfe9ebc4140dfa24`의 기존 검증 결과와 실패 식별자 집합이 동일하다. 그 직전 검증도 `6035f763e896f23cccbaf249a5c13604748f82ff` baseline과 대조했다. 주요 부채는 과거 fixture/실행 승인 계약, provider mock 설정과 download test 호환성이다. 전체 legacy suite는 all-green이 아니다.
- 전체 web lint는 기존 오류 80개, format은 기존 파일 네 개 부채가 있다. 에이전트 목록의 기존 컨벤션 오류 7개를 함께 정리했으며 변경 runtime 화면 lint·web 단위 테스트·타입/build 검사와 분리한다. 검사를 삭제하거나 실행 승인 보호를 낮추지 않는다.
- 실제 제품/다중 머신에서는 최소권한 bucket prefix 정책, 인증/허용 명령 범위, 브로커 topology, 장애/중복/취소 및 성능을 다시 수용해야 한다. 현재 S3 fixture는 IAM/실 MinIO 적합성을 증명하지 않는다.

## 미확정 사항

실제 제품/배포 분할·인증/브로커·GPU/실모델·대용량 비동기 실행은 별도 단계다.

## 관련 문서

- [구조](../../plans/architect.md) · [태스크](../../plans/tasks.md) · [격리 테스트](../../../tests/renewal/README.md) · [배포 경계](../../rules/deploy.md)
