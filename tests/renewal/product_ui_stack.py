"""UI-only product acceptance prerequisites; never creates/adopts/runs a ticket.

The installed API/result/model CLIs are the accepted image. Only read-only test
observations and a cancellation-release watcher are added outside that API.
"""
import json
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from test_registered_installed_stack import installed


def serve(stack):
    assert os.environ.get('MIDEAGENT_TEST_DISPOSABLE') == '1'
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    # Different valid prerequisites ensure the browser must save real changes.
    for name, definition in list(stack.definitions.items()):
        value = stack.runtime.definition(stack.owner, definition['id'])
        value = {key: value[key] for key in ('catalog_version','revision','name','nodes','edges','inputs')}
        for node in value['nodes']:
            node.pop('fallback_refs', None)
            if node['type'] == 'transcribe':
                node['model_ref'] = stack.refs['asr_second']
            elif node['type'] == 'translate':
                node['model_ref'] = stack.refs['text_second']
        value['name'] = '화면 통합 · ' + name
        stack.definitions[name] = stack.runtime.save_definition(stack.owner, definition['id'], value)
    with stack.database.connection() as db:
        assert db.execute('SELECT count(*) AS n FROM jobs').fetchone()['n'] == 0
    stack.start('model', 'app.operator', 'consume-registered-models')
    stack.start('api', 'app.server', '--admission-mode', 'normal')

    def observe_cancel():
        newest, released = None, set()
        while not stop.wait(0.025):
            with stack.database.connection() as db:
                latest = db.execute('SELECT id FROM jobs ORDER BY created_at DESC LIMIT 1').fetchone()
                if latest and latest['id'] != newest:
                    newest = latest['id']
                    stack.release.clear()
                    stack.entered.clear()
                if stack.calls and stack.calls[-1]['name'] == 'cancel_first':
                    identity = stack.calls[-1]['node_run_id']
                    row = db.execute('SELECT j.cancel_requested FROM jobs j JOIN node_runs n ON n.job_id=j.id AND n.owner_id=j.owner_id WHERE n.id=%s', (identity,)).fetchone()
                    if row and row['cancel_requested'] and identity not in released:
                        released.add(identity)
                        stack.release.set()
    thread = threading.Thread(target=observe_cancel, daemon=True)
    thread.start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/meta':
                body = {'workflow_ids': {name: row['id'] for name,row in stack.definitions.items()},
                        'asset_id': stack.source['asset_id'], 'refs': stack.refs,
                        'prerequisite_only': True, 'initial_ticket_count': 0}
            elif path == '/state':
                with stack.database.connection() as db:
                    jobs = db.execute('SELECT id,status,snapshot_sha256,snapshot FROM jobs ORDER BY created_at').fetchall()
                    runs = db.execute('SELECT id,job_id,node_id,node_type,status,request,result FROM node_runs ORDER BY id').fetchall()
                    late = db.execute('SELECT job_id,node_run_id,reason FROM result_quarantine').fetchall()
                body = {'jobs':jobs,'runs':runs,'quarantine':late,'calls':list(stack.calls),'errors':list(stack.errors)}
            else:
                self.send_error(404)
                return
            raw = json.dumps(body,ensure_ascii=False,default=str).encode()
            assert all(secret.encode() not in raw for secret in stack.private['keys'].values())
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1',9420),Handler)
    serving = threading.Thread(target=server.serve_forever,daemon=True)
    serving.start()
    Path(os.environ['REG_INSTALLED_EVIDENCE'],'ready.json').write_text(json.dumps({'ready':True,'initial_tickets':0,'api':'official app.server','provider':'controlled fixture; not recognition/translation quality'}))
    try:
        stop.wait()
    finally:
        stack.release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


def main():
    fixture = installed.__wrapped__()
    try:
        serve(next(fixture))
    finally:
        fixture.close()



if __name__ == "__main__":
    main()
