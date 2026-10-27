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
fallback chain (never truncates it). Operator/API auto-enrollment, multiple-candidate
role transitions, user-facing held recovery, normal-site activation and whole E2E
remain separate unfinished connections. Native test and installed-byte evidence
must be reported separately from these source-level contracts.
