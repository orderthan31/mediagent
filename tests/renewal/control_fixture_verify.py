"""Read-only native evidence: actor privilege split and per-worker report visibility."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
cfg=json.loads(Path(os.environ['MIDEAGENT_CONTROL_FIXTURE_CONFIG']).read_text())
parts=urlsplit(cfg['owner_dsn']);assert parts.path.startswith('/control_ui_')
with psycopg.connect(cfg['owner_dsn']) as db:
    a=cfg['api']['role'];h=cfg['host']['role']
    privileges={
      'api_can_write_observation':db.execute("SELECT has_column_privilege(%s,'remote_control_groups','observed','UPDATE')",(a,)).fetchone()[0],
      'api_can_change_contract':db.execute("SELECT has_column_privilege(%s,'remote_control_groups','contract_sha256','UPDATE')",(a,)).fetchone()[0],
      'api_can_finish_requests':db.execute("SELECT has_column_privilege(%s,'remote_control_requests','phase','UPDATE')",(a,)).fetchone()[0],
      'api_can_write_worker_reports':db.execute("SELECT has_table_privilege(%s,'remote_control_reports','INSERT')",(a,)).fetchone()[0],
      'host_can_read_product_jobs':db.execute("SELECT has_table_privilege(%s,'jobs','SELECT')",(h,)).fetchone()[0],
      'host_can_read_password_hashes':db.execute("SELECT has_column_privilege(%s,'accounts','password_hash','SELECT')",(h,)).fetchone()[0],
    }
    assert not any(privileges.values())
    command_counts=db.execute('SELECT phase,count(*) FROM remote_control_requests GROUP BY phase').fetchall()
    assert all(phase=='succeeded' for phase,count in command_counts)
    revision=db.execute("SELECT revision FROM remote_control_groups WHERE agent_id='analyze'").fetchone()[0]
    assert sum(count for phase,count in command_counts)==revision
visibility=[]
for worker in cfg['workers']:
    dsn=f"postgresql://{worker['role']}:{worker['password']}@{parts.hostname}:{parts.port}{parts.path}"
    with psycopg.connect(dsn) as db:
        ids=[r[0] for r in db.execute('SELECT worker_id FROM remote_control_reports').fetchall()]
        assert ids==[worker['worker_id']]
        visibility.append({'worker_id':worker['worker_id'],'only_own_report_visible':True})
print(json.dumps({'privileges':privileges,'worker_visibility':visibility,'commands':command_counts}))
