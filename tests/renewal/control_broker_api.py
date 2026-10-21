"""Disposable API using real product tickets, real TLS MQ/S3, opt-in control."""
import json
import os
from urllib.parse import urlsplit
import uvicorn
from starlette.staticfiles import StaticFiles
from app.server import load_bootstrap
from app.operator import runtime_components
from app.renewal import create_app
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
config,dsn=load_bootstrap('/run/bootstrap/api.json')
assert urlsplit(dsn).hostname=='control-pg' and urlsplit(dsn).path.startswith('/control_broker_')
assert all(urlsplit(o).hostname=='127.0.0.1' for o in config['allowed_origins'])
db=Database(dsn);store,credentials,broker=runtime_components(db,config,enable_broker=True)
app=create_app(db,allowed_origins=tuple(config['allowed_origins']),secure_cookies=False,content_store=store,credential_store=credentials,broker_factory=broker,local_execution=True,remote_control=RemoteControl(db))
app.mount('/',StaticFiles(directory='/ui',html=True))
uvicorn.run(app,host='0.0.0.0',port=8080,access_log=False,log_level='warning',proxy_headers=False)
