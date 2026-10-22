"""Explicit disposable ticket-fixture server; never an operating DSN or provider."""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import uvicorn
from app.renewal import create_app
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_execution import movie
from test_ticket_artifact_execution import make_cpu, make_registered
from video_service.content_store import ContentStore
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution


def main():
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    dsn, origin = os.environ['MIDEAGENT_TEST_DSN'], os.environ['MIDEAGENT_ARTIFACT_ORIGIN']
    target = conninfo_to_dict(dsn)
    assert target['host'] == 'ticket-db' and target['dbname'] == 'ticket_fixture'
    assert urlsplit(origin).hostname == '127.0.0.1'
    schema = 'ticket_browser_' + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    database = Database(make_conninfo(dsn, options='-c search_path=' + schema))
    database.migrate()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        actor = Accounts(database).create('ticket-fixture-admin', os.environ['MIDEAGENT_ARTIFACT_PASSWORD'], first=True)
        runtime = Execution(database, ContentStore(root))
        first = make_cpu(runtime, actor['id'], movie.__wrapped__(root))
        first = runtime.run_local(actor['id'], first['id'])
        second, _calls = make_registered(runtime, actor['id'], first['asset_id'])
        second = runtime.run_local(actor['id'], second['id'])
        cancelled = runtime.create(actor['id'], first['asset_id'], first['workflow_id'], first['workflow_revision'], request_id=uuid4().hex)
        from test_execution import admit
        admit(runtime, actor['id'], cancelled['id'])
        command = runtime.claim_next(actor['id'], cancelled['id'])
        result = runtime.execute_command(actor['id'], command)
        current = runtime.get(actor['id'], cancelled['id'])
        runtime.cancel(actor['id'], current['id'], current['revision'])
        cancelled = runtime.accept(actor['id'], command, result)
        app = create_app(database, allowed_origins=(origin,), secure_cookies=False,
                         content_store=runtime.store, local_execution=True)

        @app.get('/fixture-state')
        def fixture_state():
            return {'jobs': [first['id'], second['id']], 'cancelled': cancelled['id'],
                    'scope': 'disposable real PG/CAS, synthetic CPU and registered MockTransport results'}

        app.mount('/', StaticFiles(directory='/web', html=True))
        uvicorn.run(app, host='0.0.0.0', port=8080, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
