# Renewal isolated runtime verification

This suite is opt-in. No operational DSN/config fallback, queue consumption, GPU,
provider request, real user media or startup migration is allowed.

## Dependencies

Use Python 3.12+, FFmpeg/FFprobe, Node 22+ and installed web/Playwright dependencies.
Install `packages/shared[postgres,models,objects,amqp]`, `apps/api`, `agents/cpu`, pytest
and the test-only `moto[server]>=5,<6` in an isolated environment. Moto is an
in-process disposable loopback S3 protocol fixture, **not MinIO vendor validation**.
No test starts a production storage/broker deployment.

## Explicit disposable PostgreSQL

Set `MIDEAGENT_TEST_DSN` to an approved disposable database and
`MIDEAGENT_TEST_DISPOSABLE=1`. Every DB case creates a random schema, applies real
checksum-checked migrations and tears down only that schema. Missing DSN means
skipped tests, not successful DB verification.

```sh
PYTHONPATH=packages/shared:apps/api:agents/cpu python -m pytest tests/renewal -q
```

Tests cover upload resume/hash/owner, immutable workflow revisions, job admission,
review, cancellation, stale/duplicate result fencing, recovery, independent CPU
subprocesses, S3 remote CAS across separate private caches, publisher-confirm and
commit-before-ack contracts, derived VP9/Opus WebM, untouched originals, Range,
download hashes and preview failure preservation.

## Production bundle and real browser paths

```sh
cd apps/web
VITE_RENEWAL_BACKEND=1 VITE_FRONTEND_ONLY=0 npm run build
cd ../..
MIDEAGENT_FRONTEND_ROUNDTRIP=1 MIDEAGENT_EXECUTION_BROWSER=1 MIDEAGENT_EXECUTION_EVIDENCE=<absolute-private-evidence-directory> PYTHONPATH=packages/shared:apps/api python -m pytest tests/renewal -q
```

The suite launches explicit temporary loopback API servers and closes them.
Synthetic credentials use API clients, not password form automation. Requests are
restricted to the exact test origin. Browser tests exercise upload, workflow edit,
create/consent/admit/review/resume, final playback, original/WebM download bytes,
persistence and FHD/cover/unfolded screenshots and download-link reachability.
The object-storage case uses the independent CPU CLI and a different cache from
its application. H.264/AAC support is not required for browser playback: WebM is
the only video-player path. `MIDEAGENT_TEST_CHROME` may name an explicit optional
browser binary for comparison; it is not required by the WebM regression.

## Deliberate limits

`test_amqp.py` uses the real pinned Pika SDK/property encoder, an actual negative
loopback handshake probe and a clearly labeled channel test double. Its media,
S3-emulator and PostgreSQL paths execute for real, including retrying an unpublished
attempt, durable result acceptance and dispatch of the next node. Heartbeat/drain,
confirm failure and poison-message checks at the channel seam are **not live
RabbitMQ routing, restart, HA or multi-consumer acceptance**. No broker is started.

The installed `mideagent-cpu-amqp` executable requires `--enable-broker` and named
broker/object configs. `app.broker_server` separately enables topology provisioning
or result consumption. Import/startup tests prove neither starts implicitly.
CPU subprocess children receive object config/credentials only, not the broker URL
or application DB credentials. Unknown attempts remain fenced, not auto-executed.

These are synthetic loopback tests, not multi-host/MinIO/broker/GPU/production or
actual Fold hardware acceptance. Source size is currently 256 MiB. Long-running
preview generation needs a separate durable scheduler. Model and Loop/Fallback
execution remain fail-closed. Existing legacy-suite and full-web style debts are
tracked in [the runtime contract](../../docs/references/high/runtime.md).

DEV geometry scripts remain available: `frontend-responsive.mjs`,
`frontend-list-containment.mjs`, and `frontend-preview.mjs`. Set an explicit private
`MIDEAGENT_PREVIEW_ORIGIN` and external `MIDEAGENT_PREVIEW_EVIDENCE_DIR`. Mock-backed
DEV layout evidence is not evidence of real API or GPU execution.

## Administrator fleet and ordinary-user browser acceptance

`test_fleet.py` starts real private CPU subprocesses only after administrator
configuration. It covers replica changes, concurrent routing, drain-before-stop,
CAS conflicts, ownership fencing, CSRF/admin denial, and ordinary work selection
without administrative API access. It does not start Compose agents.

Build the production bundle above, then add `MIDEAGENT_FLEET_BROWSER=1` and an
absolute private `MIDEAGENT_FLEET_EVIDENCE` directory to the same disposable test
environment. `test_fleet_browser.py` launches a temporary loopback server with
`--allow-cpu --manage-cpu`, exercises actual administrator start/scale/stop and
ordinary upload/create/consent/completion, and closes all owned processes.

The isolated Node runtime must be available on the test subprocess PATH. The
fleet driver requires installed `agents/cpu` in the same explicit environment;
it does not infer deployment configuration. Container images are source recipes
with static Compose validation only, and unconnected model/GPU adapters remain
unavailable rather than falsely enabled.
