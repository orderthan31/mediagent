"""Disposable spoken-source/API fixture, never operating data/provider calls."""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psycopg
import uvicorn
from app.renewal import create_app
from fastapi.staticfiles import StaticFiles
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from test_transcription_execution import (
    audio_graph,
    audio_wire,
    movie_from_speech,
    register_models,
)
from video_service.content_store import ContentStore
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.credentials import CredentialStore
from video_service.postgres.execution import Execution
from video_service.postgres.registry import Registry
from video_service.postgres.transcription import TranscriptionRuntime
from video_service.postgres.translation import TranslationRuntime


def main():
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    dsn, origin = os.environ['MIDEAGENT_TEST_DSN'], os.environ['MIDEAGENT_TEST_ORIGIN']
    target = conninfo_to_dict(dsn)
    assert target['host'] == '127.0.0.1' and target['dbname'] == 'transcription_fixture'
    assert urlsplit(origin).hostname == '127.0.0.1'
    schema = 'asr_browser_' + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    database = Database(make_conninfo(dsn, options='-c search_path=' + schema))
    database.migrate()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        account = Accounts(database).create('asr-fixture-admin', os.environ['MIDEAGENT_TEST_PASSWORD'], first=True)
        credentials = CredentialStore(database, os.urandom(32))
        fixture = audio_wire.__wrapped__()
        wire_origin, calls, entered, release = next(fixture)
        try:
            kwargs = {'transport_factory': lambda: httpx.HTTPTransport(retries=0), 'approved_origins': {wire_origin}, 'mode': 'controlled_http'}
            translator, transcriber = TranslationRuntime(credentials, **kwargs), TranscriptionRuntime(credentials, **kwargs)
            runtime = Execution(database, ContentStore(root), translation_runtime=translator, transcription_runtime=transcriber)
            refs = register_models(database, account['id'], credentials, wire_origin)
            cancel_refs = register_models(database, account['id'], credentials, wire_origin, mode='cancel')
            unsupported = Registry(database).save_model(account['id'], uuid4().hex, revision=0, name='시간 규격 미지원', model='gpt-4o-transcribe', connection_id=credentials.model(account['id'], refs[1]['model_id'], 1)['connection_id'], connection_revision=2, model_types=['speech_recognition'], input_modalities=['audio'], output_modalities=['text'], capabilities=['speech_recognition'])
            source = runtime.ingest(account['id'], 'synthetic-spoken.mp4', movie_from_speech(root))
            graph = runtime.save_definition(account['id'], uuid4().hex, audio_graph(refs[0], refs[2]))
            app = create_app(database, allowed_origins=(origin,), secure_cookies=False, content_store=runtime.store, local_execution=True, credential_store=credentials, translation_runtime=translator, transcription_runtime=transcriber)

            @app.get('/fixture-state')
            def fixture_state():
                return {'workflow_id': graph['id'], 'asset_id': source['asset_id'], 'refs': refs, 'cancel_ref': cancel_refs[0], 'unsupported_id': unsupported['id'], 'calls': calls, 'entered': entered.is_set()}

            @app.post('/fixture-release')
            def fixture_release():
                release.set()
                return {'released': True}

            app.mount('/', StaticFiles(directory='/web', html=True))
            uvicorn.run(app, host='0.0.0.0', port=8080, access_log=False, log_level='warning')
        finally:
            fixture.close()


if __name__ == '__main__':
    main()
