"""Graph-only disposable PG fixture: real auth/workflow saves; no media/model execution."""
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
from psycopg.types.json import Jsonb
from video_service.content_store import ContentStore
from video_service.postgres import Database
from video_service.postgres.accounts import Accounts
from video_service.postgres.execution import Execution
from video_service.postgres.intake import digest
from video_service.postgres.registry import Registry


def main():
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    dsn, origin = os.environ['MIDEAGENT_TEST_DSN'], os.environ['MIDEAGENT_CANVAS_ORIGIN']
    target = conninfo_to_dict(dsn)
    assert target['host'] == 'canvas-db' and target['dbname'] == 'canvas_fixture'
    assert urlsplit(origin).hostname == '127.0.0.1'
    schema = 'canvas_browser_' + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    database = Database(make_conninfo(dsn, options='-c search_path=' + schema))
    database.migrate()
    with tempfile.TemporaryDirectory() as temporary:
        actor = Accounts(database).create('canvas-fixture-admin', os.environ['MIDEAGENT_CANVAS_PASSWORD'], first=True)
        runtime = Execution(database, ContentStore(Path(temporary)))
        registry = Registry(database)
        connection = registry.save_connection(actor['id'], uuid4().hex, revision=0,
            name='Graph-only fixture, never called', provider='openai_compatible', protocol='openai_compatible', endpoint='http://127.0.0.1:9/v1')
        refs = []
        for index in range(2):
            identity = uuid4().hex
            registry.save_model(actor['id'], identity, revision=0, name=f'Graph-only model pin {index}', model=f'not-called-{index}',
                connection_id=connection['id'], connection_revision=1, model_types=['text'], input_modalities=['text'],
                output_modalities=['text'], capabilities=['text_generation'])
            refs.append({'model_id': identity, 'revision': 1})
        items = {}
        for width in (1440, 390):
            port = 'video_input_' + 'x' * 20
            definition = {'id': uuid4().hex, 'revision': 0, 'catalog_version': 1,
                'name': f'합성 캔버스 · 분기와 긴 이름 · {width}', 'inputs': {port: 'video', 'transcript': 'transcript'},
                'nodes': [
                    {'id': 'split', 'type': 'select', 'position': {'x': 320, 'y': 30}, 'options': {'data_type': 'video', 'selection': 'both'}},
                    {'id': 'left', 'type': 'review', 'position': {'x': 330, 'y': 40}, 'options': {'data_type': 'video'}},
                    {'id': 'right', 'type': 'review', 'position': {'x': 340, 'y': 50}, 'options': {'data_type': 'video'}},
                    {'id': 'join', 'type': 'join', 'position': {'x': 350, 'y': 60}, 'options': {'left_type': 'video', 'right_type': 'video'}},
                    {'id': 'translated', 'type': 'translate', 'position': {'x': 360, 'y': 70}, 'options': {}, 'model_ref': refs[0], 'fallback_refs': refs[1:]},
                ], 'edges': []}
            for source, source_port, dest, dest_port in [('$input', port, 'split', 'value'), ('split', 'a', 'left', 'value'),
                    ('split', 'b', 'right', 'value'), ('split', 'a', 'join', 'left'), ('right', 'value', 'join', 'right'),
                    ('$input', 'transcript', 'translated', 'transcript')]:
                definition['edges'].append({'id': uuid4().hex, 'source': {'node': source, 'port': source_port}, 'target': {'node': dest, 'port': dest_port}})
            payload = {key: value for key, value in definition.items() if key != 'id'}
            from video_service.renewal_contracts import validate
            validation = validate(payload)
            if not validation['valid']:
                raise ValueError('Graph-only fixture: ' + str(validation['issues']))
            definition = runtime.save_definition(actor['id'], definition['id'], payload)
            asset_id, job_id = uuid4().hex, uuid4().hex
            # A declared, unverified input is deliberately NOT a runnable/upload-verified movie.
            # Seed only an immutable draft for canvas reads; do not call create/admit/execute.
            asset = {'asset_id': asset_id, 'uploaded_by': actor['id'], 'original_filename': '실제 영상이 아닌 합성 그래프 전용 · 아주 긴 입력 이름과 포트 가독성 확인.graph',
                'sha256': '0' * 64, 'size_bytes': 0, 'content_verified': False, 'web_preview': {'status': 'unavailable'}}
            snapshot = {'version': 1, 'asset': asset, 'definition': definition, 'inputs': {}, 'options': {}, 'fixture': 'graph-only, never executed'}
            with database.connection() as db:
                db.execute('INSERT INTO assets(owner_id,id,filename,storage_key,bytes,sha256,metadata) VALUES (%s,%s,%s,%s,0,%s,%s)',
                    (actor['id'], asset_id, asset['original_filename'], 'declared:graph-only', asset['sha256'], Jsonb({'registration_state': 'declared', 'fixture': 'graph-only'})))
                db.execute("INSERT INTO jobs(owner_id,id,asset_id,workflow_id,workflow_revision,status,snapshot,snapshot_sha256,workflow_owner_id) VALUES (%s,%s,%s,%s,%s,'draft',%s,%s,%s)",
                    (actor['id'], job_id, asset_id, definition['id'], definition['revision'], Jsonb(snapshot), digest(snapshot), actor['id']))
            items[str(width)] = {'workflow': definition['id'], 'job': job_id, 'original': definition, 'snapshot_sha256': digest(snapshot)}
        app = create_app(database, allowed_origins=(origin,), secure_cookies=False,
                         content_store=runtime.store, local_execution=False)

        @app.get('/fixture-state')
        def fixture_state():
            proof = {}
            with database.connection() as db:
                for width, item in items.items():
                    job = db.execute('SELECT snapshot_sha256,snapshot,revision,status FROM jobs WHERE owner_id=%s AND id=%s', (actor['id'], item['job'])).fetchone()
                    proof[width] = {**item, 'current_snapshot_sha256': digest(job['snapshot']), 'job_revision': job['revision'], 'job_status': job['status']}
            return {'items': proof, 'scope': 'real auth/workflow PG persistence; direct-seeded immutable graph-only drafts; no media/model/MQ execution'}

        app.mount('/', StaticFiles(directory='/web', html=True))
        uvicorn.run(app, host='0.0.0.0', port=8080, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
