# Server-owned start intake implementation plan

> **For Hermes:** Use subagent-driven-development for implementation, exact-source SPEC then QUALITY review, and separately verified delivery.

**Goal:** A single explicit Start submits a durable request and receives a compact acknowledgement without waiting for media validation; closing the browser must not stop server preparation.

**Architecture:** Reuse the existing SQL outbox for immutable, internal-only request and stage/terminal receipts. Accept the exact selection, preview token, authorization and metadata anchors before expensive creation; a resident, fenced consumer performs existing validation and creates the immutable job. This pre-job receipt avoids weakening generic `NormalInputs` validation or mutating a placeholder snapshot. Job creation and its bound receipt share a transaction; after exact committed admission the existing StartQueue owns dispatch.

**Tech stack:** Existing FastAPI lifecycle, PostgreSQL/psycopg, typed internal outbox records, existing orchestration/StartQueue, React/TypeScript. No new service, schema, runtime grants, public ingress or provider call is needed for implementation acceptance.

## Ownership and preservation

- Canonical repository: `orderthan31/mediagent`, existing `renewal`, base `db2c85dff59efaefb513238bfaaf0b49acf2a3a9`. Keep master, unrelated WIP, original assets, all historical jobs, consents, calls and queue records unchanged.
- All implementation and bounded repair writers have finished. Parent owns final integration and fixture compatibility, docs, exact-source review binding, Git and runtime activation. No overlapping source writer is permitted.
- This request authorizes implementation and bounded existing-destination delivery, not actual provider/GPU execution, old draft replay, broader role/permission changes or Phase3 early ACK.
- Frozen generic creation remains authoritative. Do not skip WAV/subtitle/receipt/content validation to create fast placeholder snapshots. The receipt is explicitly not yet a job or an execution claim.

## Contract and acceptance

1. `POST /api/work-entry/create-and-start` accepts the existing selection/preview/request nonce/authorization contract and returns 202 with a durable request identity and sanitized state. No media GET/probe/materialization or job workflow runs on this HTTP request.
2. Freeze owner, exact request fingerprint, asset/definition revision metadata anchors and configured role capability scope. An exact nonce replay returns its receipt before recomputing mutable preview state; a changed payload conflicts. Existing draft-only creation stays unchanged.
3. `GET /api/work-entry/start-requests/{request_id}` is authorized, read-only status. A nonce-based read recovers a lost creation reply. Status never calls plan/confirm/run. Raw selections, credentials and transcripts are not returned.
4. Saved draft Start uses `POST /api/renewal/jobs/{id}/start-request` with `{revision,request_id}` and returns `{id: job_id,start_request:{id,state}}`. It is a new explicit action only; no existing draft is discovered or upgraded automatically.
5. Use deterministic child creation/enrollment/confirm/admit nonces. Save exact stage tokens before consuming them, and reconcile existing mutation records after uncertain replies. Do not renew expired authorization or reselect roles after restart.
6. Every mutation receives an internal transactional guard that checks the current request epoch/stage, account/access, cancellation, deadline and exact scope. Session advisory locks alone are not fencing. Do not hold mutable job/intent locks during slow file validation.
7. Cancellation, expiry, drift and uncertainty are visible terminal/attention states. Reconcile a matching committed claim before declaring an intent expired or failed; after admission the new consumer never dispatches or calls providers.
8. The resident consumer scans only the new internal request type with bounded fair traversal, supports multiple API processes, stops claiming on shutdown and resumes persisted work on restart. Legacy drafts, unrelated outbox/domain events and historical unknown attempts are excluded.
9. Internal start event types are explicitly rejected before any generic transport sender. Do not use `published_at` as request-stage completion.
10. Frontend create performs one POST and opens a compact request-status route until a real job exists; then it navigates to that job. Saved Start submits one request. Reopening/polling observes only and cannot replay authorization.
11. Preserve terse UI (`시작 중…`), actual errors, existing read-only canvas and normal settings. Do not add billing/formula/reassurance prose. Preserve the nonce on uncertain submission and reconcile with GET rather than retrying a mutation.

## Task 1 — Durable intake and status

**Files:** create `apps/orchestrator/mideagent_orchestrator/start_requests.py`, `apps/api/app/start_request_routes.py`; modify existing renewal route mounting; add `tests/renewal/test_start_requests.py` and API contract tests.

- Write failing real-PG tests for compact, media-free 202 acceptance, same nonce, changed payload, ownership and rollback/lost acknowledgement.
- Implement immutable internal request records and append-only receipts using existing SELECT/INSERT rights. Keep original request bytes and metadata scope anchored.
- Verify no new-table/grant dependency, no media method calls, no job/provider/command on acceptance and no public exposure of raw request data.

## Task 2 — Server execution and fencing

**Files:** new core module; narrow internal guard/receipt seams in `execution.py` and `model_roles.py`; existing API lifespan integration; `packages/shared/video_service/durable_transport.py`; backend restart/concurrency tests.

- Write failing tests for browser absent, restart at every stage, job/consent/claim committed before receipt, duplicate consumers, lost ownership and cancellation during slow validation.
- Execute existing selection validation/create/enrollment/plan/confirm/admit in the server consumer; receipt-bind creation in its SQL transaction. Use exact frozen roles and stage data, not another available subset.
- Add guard checks to the actual mutation transactions, including idempotent reconciliation; preserve original immutable snapshots and normal APIs.
- Reject internal events at the transport boundary; assert sender/provider spies remain uncalled.
- Verify expired consent/request, inactive owner, scope drift, processing review and unknown outcomes do not generate renewed authority.
- Keep the existing new-Start/pool qualification unchanged. Demonstrate handoff to its actual queue path with a fake dispatcher; identify any installed capacity liveness limitation separately rather than removing exclusions.

## Task 3 — Thin frontend

**Files:** `apps/web/src/job-start.mjs`, `WorkflowStart.tsx`, `RenewalJobDetail.tsx`, new compact request-status component and existing app route; `tests/server-owned-start.test.mjs`, focused routed browser tests.

- Wire the saved-start helper and create receipt route; retain the original missing-export RED and seven-test checkpoint as historical evidence rather than current installation status.
- Add create acknowledgement/lost-reply nonce recovery and read-only request-status routing. Do not issue prepare/plan/confirm/admit/run from the new UI path.
- Test PC/mobile, double clicks, close/reload immediately after receipt, uncertainty, cancellation/status errors, no implicit POST on mount and same resulting job identity.
- Keep legacy explicit helper compatibility tests; do not weaken existing permission/cancellation/unknown-outcome assertions.

## Task 4 — Exact candidate acceptance

- Run real disposable no-network PostgreSQL acceptance and parse actual pytest/XML results and fixture cleanup. No production DSN or provider network is allowed.
- Run focused frontend lint/format, Node tests, production-mode build and real-component browser tests. Classify existing whole-repository lint/fixture debt separately.
- Freeze the complete intended changed/new-path inventory and source hashes, obtain independent SPEC then QUALITY, and retain rejected probes. Repair limit: two cycles per invariant class, then stop on a concrete blocker.

## Task 5 — Scoped delivery

- Verify actual installed baselines/dependencies and existing outbox rights; preserve historical image differences with minimal overlays. Build and test before stopping any service.
- Back up native authoritative DB/config where required, preserve executable predecessor recovery, and switch only necessary API/web (and any separately proven reader compatibility dependency).
- Do not run paid/model jobs or replay #41/#42. Verify exact installed imports, resident intake lifecycle, HTTPS asset hashes and read-only PC/mobile status; preserve business/consent/call/queue records and protected service identities.
- Report source completion, actual installation and actual provider E2E separately. Never advertise an untested generic media speedup, universal cache or model readiness.

## Current status

**운영 반영 완료.** 실행 코드 기준은 `dad53a7463db28fd1beb5236c10b881306ebdf48`이며, 문서 상태 정리와 실행 이미지의 소스 식별자를 구분한다.

- 완전한 39개 변경 경로를 동결해 독립 SPEC·QUALITY 승인을 받았다. 내구성 있는 생성 전 접수, 저장 작업의 명시 시작, GET 전용 상태·원래 nonce 복구와 기존 StartQueue 인계를 연결했다. 기존 검증·승인·취소·만료·불명 결과·중복 실행 fence는 유지한다.
- 동일 실행 코드의 실제 격리 PostgreSQL 핵심 46개와 API/입력 43개를 통과했으며 그중 신규 기능 사례는 중복을 제외해 83개다. 프론트 단위 213개, routed 브라우저 28개와 별도 model-budget 브라우저 1개를 통과했다. 저장 자막의 계획 회귀 24개는 실제 typed preflight를 사용하도록 테스트 연결을 보완한 뒤 통과했다. 다른 혼합 묶음의 기존 fixture 실패·skip은 별도 보존하며 전체 저장소 회귀가 모두 통과했다고 표시하지 않는다.
- 실제 production bundle·API·임시 DB에서 202 접수 후 브라우저 종료, 소유 API 프로세스 강제 종료·재시작, 같은 접수 재개와 합성 CPU 분석 완료를 확인했다. 결과 HTTP 다운로드의 바이트·SHA-256도 일치했다. 이는 실제 공급자나 운영 원본 전사·번역 실행 증거가 아니다.
- 최종 이미지의 실제 모듈 import·CLI, 설치된 서버 소스 8개, HTTPS 정적 자산 22개와 버전 메타데이터를 대조했다. 운영 API의 기동과 새 읽기 전용 상태 경로, 1440/768/390/320px 실제 HTTPS 화면의 노드 선택·가로 넘침·콘솔·무변경 요청을 확인했다. 운영에서 새 접수를 제출하거나 기존 작업을 시작하지 않았다.
- 교체는 기존 API·웹 두 서비스로 제한했다. 결과 수신기·브리지·컨트롤러·워커, 기존 사설 접근·CSRF·권한을 유지했고 보존 대상 작업·업무 데이터·큐·비대상 서비스를 대조했다. DB 백업은 비공개 보관 경로에서 형식·해시를 검증했으며 이전 컨테이너와 실행 가능한 복구 경로를 보존했다. DB 되감기나 작업·결과 재발행은 하지 않았다.
- 자산 가용성은 기존의 fresh read-time 의미다. 권한 있는 라이브러리 제거가 마지막 읽기 뒤 커밋하는 것을 배제하지 않으며, 엄격한 제거-through-commit 배타성을 제공한다고 주장하지 않는다. 실제 모델 호출·영상 전체 속도 향상·Phase 3 early ACK는 이번 완료 범위가 아니다.

### 보존된 검증 경과

아래는 앞선 후보와 보완 단계의 이력이다. 당시의 부분 통과·미반영 상태를 현재 승인이나 운영 상태로 대신 사용하지 않는다. 원래 실패와 기각된 probe, 각 단계의 소스 결합과 실행 증거는 비공개 검증 자료에 보존한다.

- The original 12-path backend candidate passed 43 new real-PG cases. Independent SPEC rejected caller-constructible authority, media I/O under mutable job locks and late-claim terminalization. Unchanged probes were reproduced; bounded cycle-one repairs now provide issued/runtime-bound/revoked guards using fresh persisted authority, claim reconciliation in the root/job-locked terminal transaction, and unlocked validation with final metadata-only source rechecks.
- Separate backend repair runs exercised guard/claim/restricted-role behavior and generic, subtitle, accepted-audio and accepted-transcript I/O. These overlapping runs are not the final combined-byte verdict. The old normal-input fake receives only an optional `lock` keyword; its assertions are unchanged.
- Saved-start frontend authority completed its two-cycle repair and independent SPEC. A subsequent generic-create quality finding exposed an older acknowledgement overwriting a newer nonce. The minimal nonce-matched enrichment correction has expected-correct RED/GREEN evidence and 213 unit, 28 routed and one separate model-budget browser pass; whole-source review remains a separate gate.
- An earlier isolated production-bundle/browser/API/PostgreSQL journey accepted 202, closed the browser, killed and restarted its owned API, then resumed the same receipt to one completed synthetic CPU analysis. This is bounded historical proof, not final-image, operating, whole-media or model inference acceptance. The final exported-tree harness additionally requires result-download integrity and source-import-origin checks.
- Native read-only inspection and an isolated SQLSTATE 42501 probe established that assets SELECT+INSERT does not authorize `FOR SHARE`. No operating grant or schema change is added: migrations 005/032 retain source identity/deletion restrictions, with fresh availability reads and existing authorized authority locks. Privileged library-removal markers are not serialized through SQL commit; strict removal-through-commit exclusion is not claimed and must remain visible in final acceptance.
- Source publication, installed compatibility, protected-data preservation and operating activation are distinct. No old #41/#42 replay, provider/GPU inference, phase-three early ACK, broader privileges or new ingress is authorized by this implementation.
