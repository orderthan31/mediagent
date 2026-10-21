"""Disposable native lifecycle fixture; direct PG reports, NOT a broker/DAG test."""
import os,signal,time
from threading import Event
from video_service.postgres import Database
from video_service.postgres.worker_telemetry import WorkerTelemetry
from video_service.worker_telemetry import WorkerReporter,exchange
assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
worker=os.environ['REVIEW_WORKER_ID'];role=os.environ['REVIEW_ROLE'];sink=WorkerTelemetry(Database(os.environ['REVIEW_REPORT_DSN']))
reporter=WorkerReporter(worker,'cpu',role,lambda report:sink.accept(report,exchange('cpu',role),expected_worker_id=worker))
stop=Event();signal.signal(signal.SIGTERM,lambda *_:stop.set())
while not stop.is_set():
    sink.beat();reporter.emit('ready');stop.wait(.3)
reporter.emit('stopping')
if os.environ.get('REVIEW_ABNORMAL')=='1':raise SystemExit(7)
time.sleep(1);reporter.emit('stopped')
