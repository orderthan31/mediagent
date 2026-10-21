"""Disposable upload UI fixture. Installed 6986b614 API; no operating config mounted."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import uvicorn
from starlette.staticfiles import StaticFiles
from app.renewal import create_app
from video_service.postgres import Database
from video_service.content_store import ContentStore

assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE')=='1'
origin=os.environ['MIDEAGENT_TEST_ORIGIN']
assert urlsplit(origin).hostname=='127.0.0.1'
dsn=os.environ['MIDEAGENT_SYNTHETIC_DSN']
assert urlsplit(dsn).hostname=='upload-pg'
database=Database(dsn)
database.migrate()
root=Path('/tmp/upload-fixture-content');root.mkdir(mode=0o700)
app=create_app(database,allowed_origins=(origin,),secure_cookies=False,
               content_store=ContentStore(root),local_execution=False)
app.mount('/',StaticFiles(directory='/ui',html=True))
uvicorn.run(app,host='0.0.0.0',port=8080,access_log=False,log_level='warning',proxy_headers=False)
