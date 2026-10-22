"""Disposable installed API, genuine auth/PG/CPU, no operational configuration."""
import os,json
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import uvicorn
from fastapi.staticfiles import StaticFiles
from app.renewal import create_app
from video_service.postgres import Database
from video_service.content_store import ContentStore
assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE')=='1'
assert os.environ['MIDEAGENT_TEST_ORIGIN'].startswith('http://127.0.0.1:')
dsn=os.environ['MIDEAGENT_TEST_DSN'];schema='shared_browser_'+uuid4().hex
with psycopg.connect(dsn) as c:c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
db=Database(make_conninfo(dsn,options='-c search_path='+schema));db.migrate()
root=Path('/tmp/shared-browser-cas');root.mkdir(mode=0o700)
Path('/tmp/shared-browser-state.json').write_text(json.dumps({'schema':schema,'content_root':str(root)}))
app=create_app(db,allowed_origins=(os.environ['MIDEAGENT_TEST_ORIGIN'],),secure_cookies=False,content_store=ContentStore(root),local_execution=True)
app.mount('/',StaticFiles(directory='/web',html=True))
uvicorn.run(app,host='0.0.0.0',port=8080,access_log=False,log_level='warning')
