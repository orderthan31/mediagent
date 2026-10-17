# Renewal PostgreSQL foundation

This is an opt-in implementation, not a production migration or execution service.
Importing `app.renewal` does not connect to a database, migrate it, load existing
operational settings, launch workers, or consume a queue.

## Implemented boundary

- Explicit checksum-checked transactional SQL migrations.
- First-administrator bootstrap, scrypt passwords, hashed sessions, CSRF and admin-issued accounts.
- Owner-scoped serving connections and registered models, CAS state revisions and immutable configuration snapshots.
- Declared model types, input/output modalities and capabilities are separate from agent task roles.
- Source-metadata repository/API with immutable, idempotent declarations and bounded owner-scoped pagination.
- OpenAI-compatible text adapter with a required injected transport; URL registration and compatibility checks perform **no network requests**.
- Optional frontend binding through `VITE_RENEWAL_BACKEND=1`; DEV publishing mode still wins when `DEV && VITE_FRONTEND_ONLY=1`.
- CPU local transcript-to-SRT runner contract. This is not an independently deployed process or broker integration.

Serving lists are read-only navigation rows; edit/availability controls belong to
detail pages. Configuration revisions stay internal rather than appearing as
model versions. Snapshots preserve registered settings, not external model weights
or endpoint reproducibility. Existing workflow references never silently retarget.

`/api/source-metadata` stores declarations only. A `sha256:...` reference is not a
filesystem path or evidence that content exists. Responses explicitly return
`content_verified: false`. Registration does not upload, open, probe, download or
process media; trusted content verification and the frontend source binding remain
subsequent work. No job, outbox message or execution claim is created.

The existing private DEV preview remains mock-backed. Unsupported renewal pages
show an unavailable boundary instead of querying legacy media/queue APIs. Jobs,
workflow repositories, review persistence, execution admission, broker consumers,
real provider/GPU validation and production cutover are not delivered by this checkpoint.
Raw provider keys cannot be entered or persisted through these registry forms;
credential-reference resolution remains a subsequent integration.

## Prerequisites

Use Python 3.12+, Node.js 22+ and the repository's installed frontend dependencies.
Install the shared package with its `postgres,models` extras and the API package in
an isolated environment, plus `pytest`. The optional browser test also requires the
pinned Playwright package/browser installed by the frontend development setup.
No test auto-installs a database or starts a broker.

## Explicit disposable test database only

Set `MIDEAGENT_TEST_DSN` to a disposable PostgreSQL instance and
`MIDEAGENT_TEST_DISPOSABLE=1`. Never use an operational DSN. Every DB test creates a
random `renewal_test_...` schema, applies the real migrations and drops only that
schema in teardown. There is no DSN fallback to application configuration.

```sh
PYTHONPATH=packages/shared:apps/api python -m pytest tests/renewal -q -s
```

Without the explicit DSN, DB cases are skipped; this is not DB verification.

For production-bundle → loopback HTTP API → real isolated PostgreSQL verification,
first build the matching opt-in frontend, then run the browser test explicitly:

```sh
cd apps/web
VITE_RENEWAL_BACKEND=1 VITE_FRONTEND_ONLY=0 npm run build
cd ../..
MIDEAGENT_FRONTEND_ROUNDTRIP=1 PYTHONPATH=packages/shared:apps/api \
  python -m pytest tests/renewal -q -s
```

The test creates a temporary loopback HTTP server and closes it afterward. It uses
synthetic credentials through the HTTP API client, not automated password-form
entry. Browser requests cannot leave that exact loopback origin. It checks serving
create/reopen, explicit connection-revision replacement, old-reference preservation,
account list/reopen, logout revocation and absence of legacy media/queue requests.
It does not prove manual credential form submission, visual acceptance or live
model connectivity.

For explicit application construction, call
`create_app(Database(dsn), allowed_origins=(exact_origin,), secure_cookies=True)`.
Origins must be configured explicitly. The loopback browser test alone opts out of
secure cookies. Apply migrations separately using
`python -m video_service.postgres.migrate --dsn-env <explicit_environment_name>`;
API startup never invokes that command.

For a bounded DEV synthetic browser check, set `MIDEAGENT_PREVIEW_ORIGIN` to the
explicit private publishing preview origin and run
`node tests/renewal/frontend-preview.mjs`. It creates its own isolated browser/tab
state, exercises empty/single/multi-page lists, detail-only serving actions,
selected-media canvas and selected-node scrolling. It does not validate an
operational API, model execution or actual touch hardware.

For responsive route and touch/wheel checks, also set an evidence directory outside
this watched checkout and run:

```sh
MIDEAGENT_PREVIEW_ORIGIN=<explicit-private-dev-origin> \
MIDEAGENT_PREVIEW_EVIDENCE_DIR=<external-evidence-directory> \
  node tests/renewal/frontend-responsive.mjs
```

The matrix distinguishes cover portrait (416×657 CSS px), unfolded landscape
(816×616 CSS px), and FHD PC (1920×1080), plus shorter browser-chrome and adjacent
320/390/896/1440px cases. Mobile probes assume DPR=3; these are reproducible browser
emulations, **not measured Fold hardware dimensions**. Physical panel pixels must
never be passed directly as CSS viewport dimensions. Actual browser zoom, display
scaling, safe areas and device chrome still require a real-device check.

Each viewport visits every active root, representative create/detail/edit routes,
every catalog agent detail, and both access forms without entering credentials.
It also exercises navigation, fold-size transitions without losing unsaved input,
canvas pickers/settings, selected-node wheel and touch scrolling, table-local
horizontal scrolling, and empty/single/45-row pagination. Short form actions share
the bottom baseline; longer forms place actions after the content instead of
covering fields or the canvas. Pagination labels must remain horizontal despite
legacy global label rules, and a closed execution popover must remain invisible.
The test fails closed on real API/external network requests and uses fresh,
isolated synthetic browser state only.
