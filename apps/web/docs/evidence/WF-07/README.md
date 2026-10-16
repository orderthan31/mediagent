# WF-07 — approved A implementation / review evidence

Baseline: `45322a80a037f334e4b38d014e09d9685f20ab69`, branch `renewal`.
Direct implementation on the designated PC; no coding agent or second writer.
This evidence is not PM acceptance, operating execution permission, external inference, or global exactly-once/billing protection.

## Product path and contracts

- Work start still selects video + saved workflow. An explicit **new recovery contract** opt-in creates tickets in a separate `/recovery-tickets` namespace. Existing workflow/graph/review/decision/work tickets and the legacy queue are not migrated/reset.
- Ordinary preparation/confirmation never dispatches work. Execution remains separate and uses the existing work factory only if explicitly connected; deployment keeps all five existing factories absent.
- An explicit recovery request creates a held child with stable parent/attempt identity. Durable request admission also retains one child identity if copying is interrupted. Repeated identical requests return that child; different payloads under the same request ID conflict. Parent ticket JSON and partial/results are preserved.
- Reuse validates owner, source/input/output SHA, definition/options, exact registered model pin, selected dependency fingerprints and completed receipts. Successful joins/downstream and independent results are not rerun. Frozen judgment and approved review bytes retain original provenance, including an approved waiting gate. A disabled model's completed result can be reused; any new call still uses current model admission.
- Missing/corrupt receipts/results are blocked, not guessed or replaced by an automatic whole rerun. Remaining work gets a child-specific fresh plan token, cost confirmation and separate execution. Even a held child forked again cannot reuse its former plan token.
- Persistent cancellation CAS is distinct from completion. Coordinator admission suppresses new submissions; the node boundary rechecks admission. Already-started calls can settle with results preserved, but cannot launch descendants/join after cancellation. Completed ticket status cannot be reversed. No forced provider abort/refund guarantee.
- Execution generations and retirement reject stale state publication; late result metadata is retained separately. A released lock/timeout is not proof of call outcome. Unknown calls require separate duplicate-call/cost-risk acknowledgment before a held recovery child can be created, and then a new execution-plan confirmation. No automatic replay.
- If every completion receipt survived but terminal publication was interrupted, a held child offers explicit finalization-only confirmation/execution without any new node call.
- Definition saves now retain immutable history prospectively. Existing older revisions are not synthesized. Restoring an existing committed revision or an owner-scoped server ticket snapshot validates current format/model references and CAS, then saves a **new revision**. It never rewinds head, edits old ticket/model pins or starts execution. History written before a failed head publication is not offered as committed history.

## Verification ledger

- Backend **75 PASS**: new WF07 **14** + relevant existing definition/sequential/graph/review/decision/work/entry/registry regressions. See `logs/WF07-python-final4.log`.
- Frontend **42 PASS**, lint, formatting, production TypeScript/build; browser TypeScript checked separately. Known dependency warnings remain visible; dependencies were not changed.
- Browser **six unique final cases**: new actual isolated ASGI/store PC1440/390 two full recovery/cancel/unknown/history journeys + existing editor PC/390 and existing product entry PC/390 four cases. This is not one six-pass batch. The regression batch passed three and had one Edge context-creation failure before mobile navigation; the fresh mobile rerun passed. See `browser-ledger.json`.
- New browser journeys use actual persistent stores/API and synthetic CPU encoding/ffprobe. Failure/interruption and judgment transports are explicitly controlled fixtures, not external model success. Cancellation during active work and stale publication are real store/coordinator tests with controlled barriers/interruption, not real provider abort or OS crash recovery claims.
- `parent-*.json` / `child-*.json` preserve raw persisted bytes (including nanosecond numeric tokens). Child joined receipts equal their parents; original a/b encoding occurs once and only the failed independent analysis is invoked again. The original parent ticket JSON stays unchanged. Creation/cancellation of an unstarted child does not add engine calls.
- Prior preflight's existing-contract thirteen-test rerun is separate and NOT added to these new test counts. Old UI01 Backend82/browser14/installation15 are not relabeled WF07 passes.

## Failures retained, not erased

RED logs cover missing functionality and boundary defects. Initial UI runs also exposed a short list-load wait, a test using the wrong pre-existing run-button name, and a same-hash navigation that did not reset the separate creation form; fixtures were corrected and rerun. The product defect where a restored r3 head still showed r2 in the saved-definition selector was reproduced RED and fixed by refreshing that list. Existing regression evidence regenerated by this task is copied under `regression/`; baseline evidence files were restored byte-for-byte from the unchanged baseline commit.

## Operating boundary

Actual deployment/installed-source/image/health/HTTPS preservation receipts are supplied separately after the exact ordinary commit is installed in the original single private web/API. No Worker start, queue consumption, GPU/provider/paid/user-original processing, key change/exposure, auth restoration, public ingress, extra stack, registry publication or VPS split is authorized. Existing data, databases, settings, keys, WIP/stash/bundles/backups remain protected. Other-device access and external inference remain unverified.
