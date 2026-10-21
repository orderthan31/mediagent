"""Disposable product control API. No Docker client/socket or host configuration."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from starlette.staticfiles import StaticFiles
from app.renewal import create_app
from video_service.content_store import ContentStore
from video_service.postgres import Database
from video_service.postgres.remote_control import RemoteControl

assert os.environ.get('MIDEAGENT_CONTROL_DISPOSABLE')=='1'
dsn=os.environ['MIDEAGENT_CONTROL_API_DSN']
assert urlsplit(dsn).hostname=='control-pg' and urlsplit(dsn).path.startswith('/control_ui_')
origin=os.environ['MIDEAGENT_TEST_ORIGIN'];assert urlsplit(origin).hostname=='127.0.0.1'
db=Database(dsn)
root=Path('/tmp/control-content');root.mkdir(mode=0o700,exist_ok=True)
app=create_app(db,allowed_origins=(origin,),secure_cookies=False,content_store=ContentStore(root),local_execution=False,remote_control=RemoteControl(db))
app.mount('/',StaticFiles(directory='/ui',html=True))
uvicorn.run(app,host='0.0.0.0',port=8080,access_log=False,log_level='warning',proxy_headers=False)
