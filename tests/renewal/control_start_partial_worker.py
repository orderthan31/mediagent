"""Synthetic actual FFmpeg work for start/partial recovery, not MQ/product tickets."""
import hashlib,os,signal,subprocess,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from video_service.postgres import Database
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.worker_telemetry import WorkerReporter,exchange
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
dsn=os.environ['REVIEW_REPORT_DSN'];assert urlsplit(dsn).hostname=='review-pg' and urlsplit(dsn).path.startswith('/control_review_')
wid=os.environ['REVIEW_WORKER_ID'];role=os.environ['REVIEW_ROLE'];db=Database(dsn);sink=WorkerTelemetry(db)
reporter=WorkerReporter(wid,'cpu',role,lambda report:sink.accept(report,exchange('cpu',role),expected_worker_id=wid))
stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
def claim():
    with db.connection() as c:
        row=c.execute("SELECT * FROM start_partial_jobs WHERE target_worker_id=%s AND state='queued' ORDER BY number FOR UPDATE SKIP LOCKED LIMIT 1",(wid,)).fetchone()
        if not row or stop.is_set():return None
        c.execute("UPDATE start_partial_jobs SET state='running',worker_id=%s,worker_boot=%s,started_at=clock_timestamp(),claim_count=claim_count+1 WHERE id=%s",(wid,reporter.boot_id,row['id']))
        return dict(row)
def execute(job):
    path=Path('/tmp')/(job['id']+'.mp4');duration=job['duration_seconds'];assert 1<=duration<=30
    subprocess.run(['ffmpeg','-nostdin','-v','error','-re','-f','lavfi','-i','testsrc2=size=128x72:rate=12','-t',str(duration),'-c:v','mpeg4','-threads','1','-y',str(path)],capture_output=True,check=True,timeout=duration+30)
    data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
    with db.connection() as c:c.execute("UPDATE start_partial_jobs SET state='completed',completed_at=clock_timestamp(),artifact=%s,sha256=%s WHERE id=%s AND worker_id=%s",(data,sha,job['id'],wid))
    path.unlink()
active=None
with ThreadPoolExecutor(max_workers=1) as pool:
    while not stop.is_set() or active:
        sink.beat()
        if active:
            job,future=active;reporter.emit('stopping' if stop.is_set() else 'busy',job['id'],job['attempt_id'])
            if future.done():future.result();active=None
        elif not stop.is_set():
            reporter.emit('ready');job=claim()
            if job:active=(job,pool.submit(execute,job))
        time.sleep(.15)
reporter.emit('stopped')
