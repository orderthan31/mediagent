# Independent model roles — staged speech checkpoint

Current operating `registered` application consumer is NOT replaced by this checkpoint.

`mideagent_models.transcription.TranscriptionAgent` executes actual LangGraph nodes:
prepare → acquire → invoke → validate → advance → next chunk / finish / hold / cancelled.
It owns `role-state.sqlite`, `graph-checkpoints.sqlite`, immutable PCM chunk bindings,
pre-HTTP call intents, completed chunk reuse, unknown holds and a task-local cancellation fence.
It neither imports `postgres.Execution` nor reads jobs/outbox/workflow definitions nor adopts
results or dispatches the next workflow node. The orchestrator retains those responsibilities.

`python -m mideagent_models.cli --config /run/role.json --audio /cache/verified.wav`
reads one task JSON from stdin. A role-only HTTP tool receives only the approved model
reference, source language and bounded PCM chunk, not a global job or workflow. Its bearer
capability is read from a private environment leaf and is not stored in graph checkpoints.
`--cancel-task TASK_ID` persists cancellation and acknowledges after active call fences settle.
There is no automatic retry of a started/unknown model call after a process restart.

This first checkpoint is controlled-provider/development evidence, not actual provider quality.
Remaining: role-scoped credential/tool admission integration; role-specific MQ/TLS S3 result
references and orchestrator adoption; configurable chunk concurrency; translation/vocal roles;
review-OFF editing and same-site final subtitle/video/download proof. No operating cutover,
real paid call, GPU work, existing key duplication or existing task replay is authorized by it.
