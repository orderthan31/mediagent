# Independent model roles — transcription boundary checkpoint

Operating services remain unchanged: the old registered-model application consumer is
still central. This staged implementation is not a claim that all model roles or the
product E2E are complete.

## Current role boundary

`mideagent_models.broker` consumes only the role's own command/cancel queues and emits
its own result/cancel-ACK. A command contains a task, frozen model reference, immutable
input artifact and output custody reference, not jobs/outbox/workflow/next-node data.
The role cannot publish another command or read the controller's result inbox.
The orchestrator must still own workflow scheduling, result adoption and next dispatch.

Transcription executes a real LangGraph: prepare, per-chunk acquire/invoke/validate,
parallel fanout, then finish/hold/cancelled. It owns its SQLite checkpoints, immutable
envelope binding, PCM chunks and call-intent ledger. Unknown started calls are held,
never automatically recalled. Completed chunk results and complete final payloads
are reused after the physical role process restarts.

The private host-managed role config sets `chunk_concurrency` and `task_slots`; these
are not user graph parameters or a claim of an integrated product administrator UI.
A semaphore bounds total model calls across concurrent tasks in one role instance;
`max_calls` remains a separate immutable per-task budget. There is no hard 2/8/16 cap.
Horizontal replicas and multi-machine outage/recovery are not yet proved.

MQ cancellation is bound to the immutable envelope SHA. A durable tombstone can arrive
before task input; admission transfers it atomically to the task. Model execution and
control run on separate pools so a busy task cannot prevent its own cancellation.
The ACK follows existing in-flight call fences; no new model call starts after it.
Cancellation and completion use SQLite BEGIN IMMEDIATE: first committed terminal wins.
Late cancellation returns an already committed completion. A later completion proposal
is quarantined if cancellation won. Transcript and projection trace commit together.
Clock structure, exact PCM frames and total WAV length are checked before task admission.

## Storage and tool credentials

Only private environment leaves supply TLS MQ, temporary scoped S3 session credentials
and a scoped model-tool capability. No existing provider key, master key or application
PostgreSQL credential is copied into the role. Artifact stores and model-tool endpoint
are configured separately from deployment placement. Paths resolve only inside the role.
Fixture proof uses a controlled TLS provider; it proves wiring/state, not recognition
quality or real-provider authentication. The production registry/credential grant bridge
is pending and must not be replaced by copying real keys.

## Entry points and remaining work

`python -m mideagent_models.broker --config /run/role.json` runs the role service;
`--once` handles one task while retaining its control consumer until it settles.
The existing local `mideagent_models.cli` remains a standalone diagnostic entrypoint.
Build `agents/models/Dockerfile` with an explicitly pinned dependency base and revision.
No public listener or Docker socket is needed by the role or the product API.

Pending: orchestrator task mapping/adoption and live credential/tool grants; translation
and vocal roles; review-OFF editing/save/reopen; same-site subtitle/video/auth-download
E2E; actual provider quality only after separate approval. Preserve old/unknown records.

## Artifact delivery failure boundary

Pure command/cancel decoding and nested-field validation raise InvalidRoleDelivery;
only that delivery is rejected. Storage/network exceptions are not invalid-envelope
errors. Verified descriptor/digest disagreement has a distinct integrity error.
`artifact_delivery_attempts` is a private transport retry budget (default 3), not a
model-call budget. Retries reuse the immutable completed role result and deterministic
CAS object. A role-local journal freezes the emitted result reference and attempt count.
Exhaustion stays held with the original broker delivery unacknowledged; recreating the
consumer does not reset the budget or recall a completed model. Held-release/adoption
integration remains an orchestrator follow-up, not an automatic old/DLQ task replay.
Publisher confirm failure still prevents ACK. The new recovery/poison regression proof
uses real LangGraph/SQLite with local mock MQ/store faults, not native fault injection.

Cancel delivery journal admission follows scope authorization in the same role-local
SQLite transaction as cancellation/tombstone adoption. Rejected scopes never reserve
the accepted control identity or its retry budget. Accepted cancel deliveries use a
separate scoped journal: old rejected rows remain immutable audit history and cannot
poison a later valid control. Matching prior accepted/held journal state is carried
forward without resetting its budget. No original journal or unknown record is deleted.


### Application-side task mapping (development)
`video_service.postgres.model_roles.ModelRoles` enrolls an explicitly selected,
not-yet-published transcription attempt. Migration026 maps its original request,
attempt and generation to the immutable role envelope. Publication journals a
separate committed sending intent under a session advisory guard; an ambiguous
send never automatically republishes. The original execution entrypoint rejects
an enrolled attempt, rather than running it centrally.

`RoleToolBridge` verifies a task's exact admitted WAV chunk and frozen registry
revision before resolving the pinned credential transiently. Its distinct SQL
HTTP-intent ledger commits before provider bytes, reuses a received reply, and
holds unknown/settled calls without automatic recall. The role receives only its
scoped service credential, never the provider key or global database access.

Results are verified against the mapping and actual TLS object bytes, including
reprojection of the frozen timeline; only the application calls accept/claim_next.
This first mapping supports one pinned candidate and explicitly rejects a configured
fallback chain (never truncates it). Fresh-job API/operator enrollment, scoped
cancel publication/ACK and application result-delivery recovery are now connected
in development source; no existing job is automatically opted in. Multiple-candidate
role transitions, worker-side artifact-exhaustion recovery without a received result,
normal-site activation and whole E2E remain unfinished connections. Native test and installed-byte evidence
must be reported separately from these source-level contracts.


### Bridge admission ordering
The application credential bridge holds a shared PostgreSQL session advisory
call fence from its final current-attempt check through actual adapter I/O.
Product cancellation acquires the same job fence exclusively before its job row
lock. Concurrent call admissions can share this fence; a cancellation that wins
first blocks subsequent model calls. An in-flight call winner must drain before
cancellation commits. Existing bounded database lock errors are not cancellation
success/ACK and must not be presented as such. No job/run row lock is held across
provider I/O.

The committed `sending` record authorizes the exact received role command before
publisher confirmation returns. The publisher drops validation row locks before
network I/O, so a fast consumer can perform its own checks instead of becoming
permanently held solely because confirmation is still pending. Later confirmation
updates only a still-sending projection, never downgrades already accepted results.
Failed/ambiguous sends retain sending/unknown history and cannot automatically
republish. This ordering is a source-level disposable-PG/local-delivery contract
until separately installed and exercised; it is not native MQ race proof.


### Explicit user/operator connection (development source, not installed)
- Apply migrations027/028 only through an explicit approved deployment; startup
  does not migrate, scan jobs, replay DLQ or activate roles.
- A configured application factory needs both `model_role_broker_config_file` and
  `model_role_result_config_file`, alongside the already-bound registered setup.
  The first uses the application command/cancel-write/result-read principal; the
  second resolves the role-output store. Never use these as worker credentials.
- The authenticated owner may POST `.../jobs/{id}/model-role/enrollment` with its
  current draft revision and request ID. Only a fresh draft with no attempts is
  eligible. The snapshot/model/input/budget stays immutable; execution still needs
  its own plan/confirmation/admission. BrokerController routes only these explicitly
  enrolled transcription attempts. The result operator owns accept/next dispatch.
- Official operator modes are `enroll-model-role` (exact owner/job/revision/request),
  `model-role-status` (exact owner/job), and `consume-model-role-results`. These are
  separate from the old registered-model execution worker and have no queue scan.
- Product cancel and its scoped role-control intent commit atomically. Control send
  intents are durable; sent/unknown cannot automatically resend. ACK is bound to
  the exact role envelope. In-flight native/deferred attempts prevent claiming that
  the whole job drained. Lock timeout returns retryable409/cancel_applied=false and
  leaves the job generation/revision and control journal unchanged.
- The user status view shows real reservations, reported role call counts, held
  causes and controller delivery state separately. Publication is not proof of an
  executing role. Model outcome_unknown provides no rerun action.
- A scoped result receipt which the application has already received may be held
  on artifact GET/adoption failure. Only explicit `result-delivery` recovery retries
  that same immutable receipt; it never starts a worker/model, resets attempts or
  changes prior uncertainty. Recovery is request-ID/CAS-bound and transport-budgeted.
  Worker artifact PUT exhaustion with no received result is not repaired by this path.
- The optional job panel shows this state and its artifact-only action. The panel's
  PC/mobile contract fixture is separate from actual PG/authenticated API/TLS S3
  tests. Neither proves operating-site deployment or native MQ races.
