"""Read-only owner evidence for the NEW broker-control fixture database."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import psycopg
from psycopg.rows import dict_row
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
cfg=json.loads(Path(os.environ['MIDEAGENT_BROKER_CONTROL_CONFIG']).read_text())
assert urlsplit(cfg['owner_dsn']).hostname=='127.0.0.1' and urlsplit(cfg['owner_dsn']).path.startswith('/control_broker_')
with psycopg.connect(cfg['owner_dsn'],row_factory=dict_row) as db:
    requests=db.execute('SELECT request_id,agent_id,revision,replicas,phase,error_code,created_at,updated_at FROM remote_control_requests ORDER BY revision').fetchall()
    actions=db.execute('SELECT id,request_id,worker_id,action,phase,issue_count,issued_at,EXTRACT(EPOCH FROM now()-issued_at) elapsed_seconds FROM remote_control_actions ORDER BY issued_at,id').fetchall()
    jobs=db.execute('SELECT id,ticket_number,status FROM jobs ORDER BY ticket_number').fetchall()
    runs=db.execute('SELECT id,job_id,node_id,node_type,status,started_at,completed_at FROM node_runs ORDER BY started_at').fetchall()
    observed=db.execute('SELECT worker_id,family,role,boot_id,state,ticket_id,attempt_id,received_at FROM worker_observations ORDER BY worker_id').fetchall()
    events=db.execute('SELECT e.worker_id,e.boot_id,e.sequence,e.state,e.ticket_id,e.attempt_id,e.received_at,r.node_id,j.ticket_number FROM worker_observation_events e LEFT JOIN node_runs r ON r.id=e.attempt_id AND r.job_id=e.ticket_id LEFT JOIN jobs j ON j.id=r.job_id ORDER BY e.received_at').fetchall()
    api=cfg['pg_roles']['api']['role'];host=cfg['pg_roles']['host']['role']
    privileges={
      'api_can_write_observation':db.execute("SELECT has_column_privilege(%s,'remote_control_groups','observed','UPDATE') v",(api,)).fetchone()['v'],
      'api_can_write_signal_journal':db.execute("SELECT has_table_privilege(%s,'remote_control_actions','UPDATE') v",(api,)).fetchone()['v'],
      'host_can_read_product_jobs':db.execute("SELECT has_table_privilege(%s,'jobs','SELECT') v",(host,)).fetchone()['v'],
      'host_can_read_password_hashes':db.execute("SELECT has_column_privilege(%s,'accounts','password_hash','SELECT') v",(host,)).fetchone()['v'],
    }
    assert not any(privileges.values())
def public(value):
    if hasattr(value,'isoformat'):return value.isoformat()
    return float(value)
print(json.dumps({'requests':requests,'actions':actions,'jobs':jobs,'runs':runs,'workers':observed,'events':events,'privileges':privileges},default=public))
