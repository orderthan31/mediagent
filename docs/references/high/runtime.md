# 리뉴얼 실행·저장 계약

## 목적

현재 개발에서 유지해야 하는 저장·실행·검수·복구의 기술 경계와 재현 진입점을 관리한다.

## 현재 상태

신규 PG/원본/티켓/CPU 경로는 미커밋 WIP다. 격리 브라우저 동선과 다운로드 SHA 확인은 수행했으나 최신 재생 검사는 실패 상태이며 최종 회귀·공유는 남아 있다.

## 주요 내용

### 책임과 보호

- 계정/서빙 등록·원본·workflow revision·ticket snapshot·노드/검수/실행 승인은 소유자 범위 PostgreSQL에 저장한다. 미디어 바이트는 DB와 분리한다.
- 정의/입력/설정·검수의 출처와 불변 hash를 고정한다. 등록 endpoint 설정 snapshot은 외부 모델 가중치 고정이나 추론 재현성을 보장하지 않는다.
- 사람 검수는 draft 저장 → 확정 → 남은 계획 재확인 → 별도 이어 실행으로 분리한다. 에이전트는 웹 세션이나 후속 workflow를 알아서는 안 된다.
- 실행 동의는 서버가 재계산한 남은 계획과 입력에 결속한다. 미사용 동의는 서버 시각 15분 후 만료되며 재요청이 만료 시간을 늘리거나 새 실행을 만들지 않는다.
- 중복 실행 claim과 재전달을 구분한다. 결과 불명 요청을 자동 retry/fallback하지 않으며 늦거나 오래된 generation 결과는 정상 완료에 채택하지 않는다.
- 취소는 진행 중 처리의 정리와 결과 격리를 고려한다. 복구는 원 작업·결과·승인을 덮어쓰지 않는 새 자식 작업이며, 검증된 완료 receipt와 의존성만 재사용한다.
- 모델·제어 노드의 편집 지원과 실제 실행 지원을 구분한다. 현재 CPU 실행기가 미지원 모델·Loop/Fallback을 정상 완료처럼 실행하지 않도록 닫힌 상태를 유지한다.

### 현재 구현 한계

- 원본/콘텐츠의 현재 상한은 256 MiB, 업로드 chunk는 4 MiB다. 과거 legacy의 1/5 GiB 검증을 신규 경로의 대용량 지원 증거로 재사용하지 않는다.
- local `ContentStore`와 CPU subprocess는 실제 구현되어 있으나 원격 S3/브로커를 통한 에이전트 독립 운영은 미완이다.
- 프론트의 실제 API는 `VITE_RENEWAL_BACKEND=1` opt-in이며 `DEV && VITE_FRONTEND_ONLY=1` 목업과 구분한다.
- 최신 합성 MP4 재생은 `NotSupportedError`로 실패했다. 파일 다운로드 SHA·API 정상 응답만으로 플레이어 재생 성공을 주장하지 않는다. 코덱/응답/브라우저 중 원인은 미확정이다.

### 격리 검증

- Python 3.12+·FFmpeg/FFprobe·Node 22+와 설치한 web 의존성을 사용한다.
- `MIDEAGENT_TEST_DSN`은 반드시 disposable PG여야 하며 `MIDEAGENT_TEST_DISPOSABLE=1`을 명시한다. 운영 DSN fallback은 없다. 테스트는 매번 임의 schema만 만들고 정리한다.
- `PYTHONPATH=packages/shared:apps/api python -m pytest tests/renewal -q`로 검사한다. DB 설정 없이 건너뛴 검사는 PG 통과가 아니다.
- production frontend build 후 `MIDEAGENT_EXECUTION_BROWSER=1`, 외부 증적 경로 `MIDEAGENT_EXECUTION_EVIDENCE`를 지정해 `tests/renewal/test_execution.py::test_production_cpu_browser_and_explicit_launcher`를 실행한다. 현재 이 확장 검사는 위 재생 오류로 실패하므로 all-green으로 보고하지 않는다.
- 합성 API 세션 인증, loopback HTTP, 합성 미디어만 사용하고 테스트 서버는 종료한다. 이는 비밀번호 폼 수동 검증이나 운영 배포가 아니다.

## 미확정 사항

실제 원격 저장소/브로커·GPU/모델 실행과 운영 전환은 아직 검증하지 않았다.

## 관련 문서

- [현재 구조](../../plans/architect.md)
- [구현 태스크](../../plans/tasks.md)
- [배포 경계](../../rules/deploy.md)
