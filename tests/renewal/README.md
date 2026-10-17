# Renewal PostgreSQL foundation

This is an opt-in implementation, not a production migration or execution service.
Importing `app.renewal` does not connect to a database, migrate it, load existing
operational settings, launch workers, or consume a queue.

## Implemented boundary

- Explicit checksum-checked transactional SQL migrations.
- First-administrator bootstrap, scrypt passwords, hashed sessions, CSRF and admin-issued accounts.
- Owner-scoped serving connections and registered models, CAS state revisions and immutable configuration revisions.
- OpenAI-compatible text adapter with a required injected transport; URL registration and compatibility checks perform **no network requests**.
- Optional frontend binding through `VITE_RENEWAL_BACKEND=1`; DEV publishing mode still wins when `DEV && VITE_FRONTEND_ONLY=1`.
- CPU local transcript-to-SRT runner contract. This is not an independently deployed process or broker integration.

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
