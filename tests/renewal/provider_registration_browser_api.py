"""Disposable registry/credential UI fixture; no operating data or provider calls."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import uvicorn
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.renewal import create_app
from video_service.postgres import Database
from video_service.postgres.credentials import CredentialStore


def main():
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    origin = os.environ['MIDEAGENT_TEST_ORIGIN']
    assert urlsplit(origin).hostname == '127.0.0.1'
    dsn = os.environ['MIDEAGENT_TEST_DSN']
    target = conninfo_to_dict(dsn)
    assert target.get('host') == '127.0.0.1'
    assert target.get('dbname') == 'provider_registration_fixture'
    schema = 'provider_browser_' + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    database = Database(make_conninfo(dsn, options='-c search_path=' + schema))
    database.migrate()
    master = Path('/tmp/provider-master.key')
    master.write_bytes(os.urandom(32))
    master.chmod(0o600)
    Path('/tmp/provider-browser-state.json').write_text(json.dumps({'schema': schema}))
    app = create_app(
        database,
        allowed_origins=(origin,),
        secure_cookies=False,
        credential_store=CredentialStore.from_file(database, master),
    )
    app.mount('/', StaticFiles(directory='/web', html=True))
    uvicorn.run(app, host='0.0.0.0', port=8080, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
