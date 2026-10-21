"""One disposable DB only: product API, host mailbox and per-worker PG roles."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from video_service.postgres import Database

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config=json.loads(Path(os.environ['MIDEAGENT_CONTROL_FIXTURE_CONFIG']).read_text())
dsn=config['owner_dsn'];parts=urlsplit(dsn)
assert parts.hostname=='127.0.0.1' and parts.path.startswith('/control_ui_')
Database(dsn).migrate()
with psycopg.connect(dsn) as db:
    db.execute("CREATE TABLE control_fixture_jobs(id text PRIMARY KEY CHECK(id ~ '^[a-f0-9]{32}$'),ticket_number bigint GENERATED ALWAYS AS IDENTITY(START WITH 7001) UNIQUE,state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','completed')),target_worker_id text,worker_id text,duration_seconds integer NOT NULL CHECK(duration_seconds BETWEEN 1 AND 15),started_at timestamptz,completed_at timestamptz,artifact bytea,sha256 text)")
    db.execute("CREATE FUNCTION control_fixture_report_clock() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.received_at=clock_timestamp();RETURN NEW;END $$")
    db.execute("CREATE TRIGGER control_fixture_report_time BEFORE INSERT OR UPDATE ON remote_control_reports FOR EACH ROW EXECUTE FUNCTION control_fixture_report_clock()")
    for role in [config['api'],config['host'],*config['workers']]:
        db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role['role']),sql.Literal(role['password'])))
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role['role'])))
    api=sql.Identifier(config['api']['role']);host=sql.Identifier(config['host']['role'])
    db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(api))
    db.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(api))
    db.execute(sql.SQL('REVOKE ALL ON remote_control_groups,remote_control_requests,remote_control_reports,control_fixture_jobs FROM {}').format(api))
    db.execute(sql.SQL('GRANT SELECT ON remote_control_groups,remote_control_requests TO {}').format(api))
    db.execute(sql.SQL('GRANT UPDATE(revision,enabled,replicas,pending_request) ON remote_control_groups TO {}').format(api))
    db.execute(sql.SQL('GRANT INSERT ON remote_control_requests TO {}').format(api))
    db.execute(sql.SQL('GRANT SELECT,INSERT ON remote_control_groups TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(observed,observed_at,pending_request) ON remote_control_groups TO {}').format(host))
    db.execute(sql.SQL('GRANT SELECT ON remote_control_requests,remote_control_reports TO {}').format(host))
    db.execute(sql.SQL('GRANT UPDATE(phase,error_code,updated_at) ON remote_control_requests TO {}').format(host))
    db.execute('ALTER TABLE remote_control_reports ENABLE ROW LEVEL SECURITY')
    db.execute('ALTER TABLE control_fixture_jobs ENABLE ROW LEVEL SECURITY')
    db.execute(sql.SQL('CREATE POLICY host_read_reports ON remote_control_reports FOR SELECT TO {} USING(true)').format(host))
    for index,worker in enumerate(config['workers']):
        role=sql.Identifier(worker['role']);wid=sql.Literal(worker['worker_id'])
        db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE ON remote_control_reports TO {}').format(role))
        db.execute(sql.SQL('GRANT SELECT,UPDATE ON control_fixture_jobs TO {}').format(role))
        db.execute(sql.SQL("CREATE POLICY {} ON remote_control_reports FOR ALL TO {} USING(worker_id={} AND agent_id='analyze') WITH CHECK(worker_id={} AND agent_id='analyze')").format(sql.Identifier('worker_report_'+str(index)),role,wid,wid))
        predicate=sql.SQL('(target_worker_id IS NULL OR target_worker_id={}) AND (worker_id IS NULL OR worker_id={})').format(wid,wid)
        db.execute(sql.SQL('CREATE POLICY {} ON control_fixture_jobs FOR ALL TO {} USING({}) WITH CHECK(({}) AND worker_id={})').format(sql.Identifier('worker_job_'+str(index)),role,predicate,predicate,wid))
print(json.dumps({'disposable_schema_ready':True,'api_cannot_publish_observation':True,'workers_row_bound':len(config['workers'])}))
