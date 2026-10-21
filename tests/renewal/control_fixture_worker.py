"""Synthetic cooperative workload for fixed-target control acceptance only.

Not a production broker/DAG worker. Generates a real timed FFmpeg video and
persists its bytes/hash before exiting, with per-instance reports and job claims.
"""
import hashlib
import os
import re
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from video_service.postgres import Database

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
dsn=os.environ['MIDEAGENT_CONTROL_WORKER_DSN']
assert urlsplit(dsn).hostname=='control-pg'
assert urlsplit(dsn).path.startswith('/control_ui_')
worker=os.environ['MIDEAGENT_CONTROL_WORKER_ID'];assert re.fullmatch('[a-f0-9]{32}',worker)
db=Database(dsn);boot=uuid4().hex;stop=threading.Event();active=None
signal.signal(signal.SIGTERM,lambda *_:stop.set())
signal.signal(signal.SIGINT,lambda *_:stop.set())


def report(state, job=None):
    with db.connection() as conn:
        conn.execute("INSERT INTO remote_control_reports(worker_id,agent_id,boot_id,state,ticket_id,ticket_number) VALUES (%s,'analyze',%s,%s,%s,%s) ON CONFLICT(worker_id) DO UPDATE SET boot_id=EXCLUDED.boot_id,state=EXCLUDED.state,ticket_id=EXCLUDED.ticket_id,ticket_number=EXCLUDED.ticket_number,received_at=now()",(worker,boot,state,job['id'] if job else None,job['ticket_number'] if job else None))


def claim():
    with db.connection() as conn:
        job=conn.execute("SELECT * FROM control_fixture_jobs WHERE state='queued' AND (target_worker_id IS NULL OR target_worker_id=%s) ORDER BY ticket_number FOR UPDATE SKIP LOCKED LIMIT 1",(worker,)).fetchone()
        if not job or stop.is_set():return None
        conn.execute("UPDATE control_fixture_jobs SET state='running',worker_id=%s,started_at=now() WHERE id=%s",(worker,job['id']))
        return dict(job)


def execute(job):
    output=Path('/tmp')/('control-'+job['id']+'.mp4')
    duration=job['duration_seconds'];assert type(duration) is int and 1<=duration<=15
    subprocess.run(['ffmpeg','-nostdin','-v','error','-re','-f','lavfi','-i','testsrc2=size=128x72:rate=12','-t',str(duration),'-c:v','mpeg4','-y',str(output)],check=True,capture_output=True,timeout=45)
    content=output.read_bytes();digest=hashlib.sha256(content).hexdigest()
    with db.connection() as conn:
        conn.execute("UPDATE control_fixture_jobs SET state='completed',artifact=%s,sha256=%s,completed_at=now() WHERE id=%s AND worker_id=%s",(content,digest,job['id'],worker))
    output.unlink()


report('connected')
with ThreadPoolExecutor(max_workers=1) as pool:
    while not stop.is_set() or active:
        if active:
            job,future=active
            report('stopping' if stop.is_set() else 'busy',job)
            if future.done():
                future.result();active=None
        elif not stop.is_set():
            report('ready')
            job=claim()
            if job:active=(job,pool.submit(execute,job))
        time.sleep(.15)
report('stopped')
