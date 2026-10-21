"""Owner-only synthetic job injection/readback. No public fixture endpoints."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from video_service.postgres import Database
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config=json.loads(Path(os.environ['MIDEAGENT_CONTROL_FIXTURE_CONFIG']).read_text())
assert urlsplit(config['owner_dsn']).path.startswith('/control_ui_')
db=Database(config['owner_dsn'])
operation=sys.argv[1]
with db.connection() as conn:
    if operation=='enqueue':
        worker=sys.argv[2];assert worker in [w['worker_id'] for w in config['workers']]
        identity=uuid4().hex
        row=conn.execute('INSERT INTO control_fixture_jobs(id,target_worker_id,duration_seconds) VALUES(%s,%s,10) RETURNING id,ticket_number,state',(identity,worker)).fetchone()
        print(json.dumps(dict(row)))
    elif operation=='read':
        identity=sys.argv[2];assert re.fullmatch('[a-f0-9]{32}',identity)
        row=conn.execute('SELECT * FROM control_fixture_jobs WHERE id=%s',(identity,)).fetchone();assert row
        content=bytes(row['artifact']) if row['artifact'] is not None else None
        if content is not None:
            assert hashlib.sha256(content).hexdigest()==row['sha256']
            root=Path(config['artifact_root']);root.mkdir(exist_ok=True)
            (root/(identity+'.mp4')).write_bytes(content)
        print(json.dumps({'id':row['id'],'ticket_number':row['ticket_number'],'state':row['state'],'worker_id':row['worker_id'],'bytes':len(content) if content else 0,'sha256':row['sha256'],'hash_verified':content is not None}))
    else:raise ValueError('fixture_operation_not_allowed')
