# Task Handoff Performance Implementation Plan

> **For Hermes:** Use subagent-driven-development to execute each phase with exact-tree SPEC then QUALITY review.

**Goal:** Reduce task-transition overhead identified in the read-only audit without weakening immutable input verification, explicit execution authority, durable result handling or unknown-outcome/no-replay fences.

**Architecture:** Add bounded, privacy-safe stage timing first. Then avoid unnecessary whole-artifact work before eligible capacity exists and reuse verified material only within an explicitly bounded operation. Make durable result settlement independent from the expensive next dispatch, using existing approved enrollment/reconciliation where sufficient or a separately reviewed durable wakeup contract. Finally reduce measured connection/scheduling overhead; do not replace RabbitMQ or raise warm/concurrency capacity by guesswork.

**Tech Stack:** Python 3.12+, PostgreSQL, S3 CAS, RabbitMQ/Pika, existing orchestrator and ControlNet, pytest. No new service, public ingress, model/GPU inference or alternate host.

## Authorization, source and ownership

- User instruction `1572065941334921299`: proceed in the recommended order. This authorizes bounded implementation/testing and gated delivery; the earlier audit-only hold is superseded for this work.
- Starting branch `renewal`; base `1f672ca8732cab996926f55100a9a91a5c81a379`, tree `cdd7b123748f8b1acce64e86fcc6d6e82e0238ae`. `master` remains comparison-only. No forced push/new branch/worktree.
- Parent owns integration, plan/status, exact-tree freezing, GitHub App identity/push and native activation. Implementers own only their assigned source/test files. Design/review children are read-only.
- Audit evidence is private: `/root/workspaces/mideagent-transition-audit-20261117T001158Z/`. Implementation receipts: `/root/workspaces/mideagent-handoff-implementation-20261117T014947Z/`.
- Local isolated test interpreter: `/root/workspaces/mideagent-handoff-implementation-20261117T014947Z/venv/bin/python`.
- Preserve all existing jobs, original media, credentials, role/model pins, #5/DLQ/accepted-result20, accepted/held/unknown records, backups and WIP. No automatic historical replay, initialization cleanup, broad GRANT, authentication/network relaxation or unapproved provider call.
- Current runtime is mixed-revision. Prepared future MT135/Bridge artifacts are not active; this plan does not silently activate them as a prerequisite.

## Safety and gate contract

1. **Pre-flight:** Re-read source/index/runtime identities; preserve unrelated changes. Use existing authorized readers and existing disposable test fixtures, never an operating DSN as a test database.
2. **Revision:** TDD for each changed invariant, exact source/file manifest, then independent SPEC and QUALITY. Maximum two class-level repair cycles; preserve original failures and escalate if a third substantial repair is needed or progress stalls.
3. **Runtime pre-flight:** Build exact approved images, prove imports and permissions with no egress, backup through existing authorized maintenance only where needed, prepare stopped candidates and executable predecessor recovery before stopping a scoped service. Confirm active work/delivery settlement on actual application vhost; if unresolved, keep runtime unchanged and continue only separately safe source work.
4. **Abort/recover:** No forced stop of unsettled workers, no queue purge, no business-DB rewind. Restore only the changed compatible service/configuration. Preserve errors and read back actual state after lost SSH responses before retrying.
5. **Closeout:** Distinguish source/test delivery, installed code, instrumentation measurements, synthetic acceptance and actual provider E2E. Never report inferred speedup as measured production improvement.

## Phase 1 — Privacy-safe stage timing (implement first)

**Files:**
- Create `packages/shared/video_service/handoff_timing.py`.
- Instrument bounded entry/exit points in `apps/orchestrator/mideagent_orchestrator/{controller,execution,model_delivery}.py` and `packages/shared/video_service/{object_store,rabbitmq_transport,durable_transport}.py` as actually required.
- Create `tests/renewal/test_handoff_timing.py` and focused real-callback/object-store regression coverage.

**Contract:**
- Provide a small span/context API, e.g. `with handoff_span('dispatch', job_id=opaque_id): ...`, using monotonic duration and UTC endpoints. Nested work carries an opaque correlation identity.
- Closed stage/outcome/schema, validated opaque IDs and bounded nonnegative numeric metrics only. Never emit prompts, filenames, keys, URLs, headers, request/response bodies, arbitrary labels or exception messages.
- Metadata-only timing must be observable in the installed process without relying on a disabled root logger. The sink must be bounded and best-effort; sink failure must not alter execution/return/exception semantics. Preserve private pre-tee diagnostic policies.
- Aggregate per-object bytes/operations, not a record per streaming block. No inferred provider time from end-to-end tool duration.
- Observe dispatch/preflight/result import/adoption, object GET/hash/materialization, connection setup and publish-confirm boundaries. Do not change execution order, retries, ACK, pool policy or business state in this phase.

**TDD:**
1. Add failing tests for finite monotonic duration, UTC endpoints, nested identity, emission of only safe fields, secret sentinels, oversized/invalid metadata, sink failure, BaseException/cancellation preservation and concurrent context isolation.
2. Run with the isolated interpreter and repository `PYTHONPATH`, no provider credentials/egress.
3. Implement minimum timing module/hooks.
4. Exercise real controller receive/dispatch and fake object store; verify identical original callback results/call counts, zero added generation/dispatch, no mutation/replay and bounded records.
5. Capture unique test counts and source hashes; independent SPEC→QUALITY before delivery.

## Phase 2 — Reduce redundant verified I/O

**Candidate files:** `execution.py`, `agent_pool.py`, `object_store.py`, `content_store.py`, `audio_region_reviews.py`, relevant focused tests. Final inventory must follow read-only design review, not blanket permission to rewrite these modules.

**Design constraints:**
- Separate cheap eligibility/current claim/capacity demand from expensive source verification. A cold-role demand may prepare capacity but must not create a command/provider invocation before exact input verification and fresh locked checks.
- Determine references needed by the next eligible node instead of blindly validating unrelated historical outputs. Preserve original-media clock/type/budget contracts.
- Prefer one-operation verified-handle reuse with complete owner/reference/digest/size/type and snapshot/generation binding. No cross-request remote-authority cache in this phase.
- Revalidate local bytes and relevant mutable context; preserve remote corruption, permission revocation, cross-owner, symlink, snapshot drift, cancelled/unknown and stale claim negatives. Any changed freshness guarantee must be explicit and reviewed.

**TDD:** Establish predecessor GET/byte counts using the real store and a synthetic S3; add expected-correct regressions for cold capacity producing no large GET, a ready successor validating only its required references, and repeated references reusing a verified operation. Include tampering/drift/cancellation controls and PG concurrency tests with event-gated fake I/O outside mutable locks. Compare counts and lock occupancy, not fabricated wall-clock improvements.

## Phase 3 — Durable settlement, asynchronous subsequent scheduling

**Candidate files:** `controller.py`, `model_delivery.py`, `agent_pool.py`, `dispatch.py` and existing outbox transport/reconciliation paths. A schema migration is not a default.

**Design prerequisite:** Prove whether existing durable `agent_pool_jobs` enrollment plus current generation/claim and resident `AgentPool.tick()` guarantees the next wakeup after a committed result. Confirm the dispatcher really runs in every enabled composition. If insufficient, propose an exact durable wakeup using existing infrastructure before implementing; do not silently add runtime grants or background replay authority.

**Acceptance:** Result callback may ACK only after durable receipt/adoption and an exact durable scheduling obligation exist. The next expensive dispatch runs separately with bounded concurrency. Preserve synchronous fallback for non-enrolled/unsupported paths where durability cannot be established. Handle crash before/after commit/ACK, duplicate result, broker loss, cancelled job, changed generation/claim, held/unknown and lost replies without duplicate execution or lost work. Explicitly preserve start-queue progression and unrelated approved-job ordering.

## Phase 4 — Target measured remaining overhead

1. Assess publisher-owner persistent AMQP connection with heartbeat servicing and bounded submit/shutdown; never share BlockingConnection across request threads or retry an uncertain send.
2. Add DB pooling only if measured benefit justifies it and session advisory guards have explicit release/reset guarantees. Retaining per-call connections is preferable to leaking ownership.
3. Fix bounded runnable-frontier filling only with independent-branch tests and existing job/role caps; do not uncap concurrency or parallelize model candidates/batches without their budget/checkpoint contract.
4. Do not add a warm floor or model daemon unless measured active local model reload proves the need. Retaining RabbitMQ and current resources is the default.

## Integrated verification and rollout

- Test exact frozen intended tree, including added files and this plan. Keep test artifacts outside repo and disable unnecessary cache writes.
- Run relevant scheduling, pool admission, artifact-origin/integrity, role-delivery recovery, cancellation, auth and terminal privacy regressions; use explicitly disposable PG/S3 only.
- Use synthetic media to exercise cold-role/warm-role, large-original/small-successor and independent-branch paths. Confirm original file/reference/graph/pins unchanged and no provider call. Record GET count/bytes, lock duration, pure scheduling spans and ACK timing.
- Parent pins verified bot author/committer before creating the review candidate. Use normal GitHub App push to `renewal` and exact canonical remote readback; preserve `master`.
- Roll out only necessary components after readiness/settlement gates. Keep users' existing held/unknown jobs unchanged. Verify actual source imports, private health, provided asset compatibility, business fingerprints and protected services. Report measured before/after where available, and explicitly label anything only source-tested or not activated.

## Status

- [x] User implementation authorization and clean base captured.
- [x] Existing architecture audit and measured timing baseline preserved.
- [x] Isolated local Python 3.12 test environment prepared.
- [x] Phase 1 instrumentation implementation/tests/SPEC/QUALITY/native verification.
  - Published instrumentation source: `e98379be86d54b2640234c6db241d204e6174a7a`, tree `37c84f712713a5d56f6e4e89583550a9f81e7ea6`; independent SPEC and QUALITY passed, 20 focused tests.
  - Installed only the reviewed telemetry overlays on API, three result consumers and two Bridges; preserved the older installed results projection variant and excluded future adapter/MT135 changes.
  - Exact images/modules, actual AMQP consumer registration, private HTTPS session, unchanged frontend index, business fingerprints and queue contents were verified. Thirteen stable protected services remained unchanged; two pre-existing auto-restarting initializers were retained without intervention.
  - A rollout readiness probe incorrectly treated inherited `Healthcheck: [NONE]` as a missing healthy state; that attempt restored all predecessors. Historical failure was preserved, actual consumer/channel/peer readiness was proven on the originals, and the corrected rollout passed. No business data was restored or replayed.
  - Performance attribution remains pending natural work; installed timing and isolated regression success are not measured production speedup.
- [x] Phase 2 approved cold and plain/audio ready-input slices delivered; broader cases/reuse remain explicitly deferred.
  - [x] Slice 1: shared admitted cold-demand gate published as `ed141eb26b3f863762ae2ba6def5b125ee1affe9`; exact source SPEC/QUALITY and installed-variant integration approved. Parent independently passed 57 cold-gate/timing cases on a fresh no-network disposable PostgreSQL fixture.
  - [x] Slice 1 installed on API and three result consumers only. Exact images/imports, private HTTPS actor/CSRF, unchanged frontend, business fingerprints, enrollment/demand/policy and queues verified; workers, Bridges and controller unchanged. No historical replay or production speedup claim.
  - [x] Ready plain/audio staging published and installed as `5dfc3156c3dd74fcc35310491eb43b399a6e425e`: immutable capture, selected-port verification and derived command/budget work outside mutable locks, fresh final authority/capacity checks, one atomic command. Unsupported Face/subtitle/native-control/engine/deferred/historical cases retain full existing fallbacks.
  - [x] User `1572122549284773923` approved one extra audio-root repair after the prior limit. Original-source exemption is confined to preprocessing; successor audio still requires normalized PCM/full-frame checks even under numeric caps and original-reference aliases. Targeted 11 cases and complete bounded 102-case ready/cold/timing acceptance passed; the unrelated seven baseline harness failures remain explicitly documented.
  - [x] Exact source SPEC/QUALITY and native mapping approved. Four API/result replacements independently read back with exact imports/images, actual broker readiness, unchanged business/enrollment/demand/policy/queues, private HTTPS actor/CSRF and unchanged frontend. Fifteen stable protected services and two pre-existing auto-restarting initializers retained. Workers, Bridges, controller, old jobs and provider execution untouched by this slice.
  - [ ] Optional operation-local reuse remains deferred: no implicit cache or weakened per-read remote freshness without an explicit semantics decision.
- [ ] Phase 3 durable handoff implementation/tests/reviews.
  - **Deferred / no ACK-early switch:** frozen-base liveness proof found that reserved ordinary/model successors can disappear from API pump selection, and AgentPool membership disables managed encode's recoverable pending path. Existing enrollment alone does not prove restart-safe scheduling.
  - Source API StartQueuePump wiring is proven; native resident restart/crash coverage is not. Keep synchronous result→dispatch and all held/unknown recovery rules unchanged. No new obligation type, historical scan, retry, service or grant was enabled.
  - Prerequisite report: private `phase3-liveness-proof.md`; parent independently reproduced five critical frozen AST predicates. Any future bounded managed-CPU scope needs an explicitly resolved fresh-path protocol and atomic exact scheduling obligation before implementation/activation.
- [ ] Phase 4 measured remaining overhead disposition/tests/reviews.
  - Passive timing evidence contains metadata reads and consumer-start connection spans, not a command publish/confirm or workflow before/after cohort. Persistent publisher, DB pooling and warm-floor changes remain unjustified and unimplemented; bounded frontier filling remains later work, not part of the audio repair.
- [x] Integrated delivery/readback of the approved slices and bounded audio repair. Phase 3/4 and optional cache/broader closures above are not claimed complete; no production seconds-saved or provider E2E claim.
