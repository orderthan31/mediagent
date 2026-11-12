"""Independent saved subtitle copies; temporary local CAS and explicit S3 double only."""
import ast
import asyncio
import hmac
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / 'packages/shared'))
from video_service.content_store import ContentStore

ACTOR, COPY = 'a' * 32, 'b' * 32
SRT = '\ufeff  \r\n00:00:00,125 --> 00:00:00,750\r\n수정 <script>literal</script>\r\n둘째 줄\r\n\r\n-3\r\n00:00:01,000 --> 00:00:01,800\r\n끝\r\n'


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Existing POSIX CAS chmod semantics require this Windows-only test adapter.
    # Do not change the production immutable CAS or touch files outside tmp_path.
    if os.name == 'nt':
        chmod = Path.chmod
        def windows_mode(path, mode, *args, **kwargs):
            if mode == 0o400 and path.is_relative_to(tmp_path):
                return
            return chmod(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, 'chmod', windows_mode)
    return ContentStore(tmp_path)


def service(store):
    from video_service.subtitle_copies import SubtitleCopies
    return SubtitleCopies(store)


def payload(id=COPY, srt=SRT):
    return dict(id=id, filename='원본.smi', title='편집 자막', srt=srt)


def test_save_shared_list_reopen_preserves_exact_bytes_and_history(store):
    copies = service(store)
    first = copies.save(ACTOR, **payload())
    assert first['id'] == COPY and first['cue_count'] == 2
    assert 'storage_key' not in json.dumps(first) and 'actor_id' not in first
    assert service(ContentStore(store.root)).get(COPY)['srt'] == SRT
    assert copies.list()['copies'] == [first]
    assert copies.save(ACTOR, **payload()) == first
    newer = copies.save('c' * 32, **payload('d' * 32, SRT.replace('수정', '새 수정')))
    assert len(copies.list()['copies']) == 2 and newer['id'] != first['id']
    assert copies.get(COPY)['srt'] == SRT
    with pytest.raises(ValueError, match='collision'):
        copies.save(ACTOR, **payload(srt=SRT.replace('수정', '덮어쓰기')))


@pytest.mark.parametrize('change', [
    {'filename': '../escape.srt'}, {'filename': 'C:\\private.srt'},
    {'id': '../escape'}, {'title': ''}, {'srt': '<html>no subtitle</html>'},
    {'srt': SRT.replace('00:00:00,750', '00:00:00,100')},
    {'srt': '1\n00:00:00,000 --> 00:00:01,000\n \n'},
    {'srt': SRT + 'x' * (16 * 1024 * 1024)},
])
def test_invalid_save_does_not_publish(store, change):
    with pytest.raises(ValueError):
        service(store).save(ACTOR, **{**payload(), **change})
    assert service(store).list()['copies'] == []


def actual_app(store):
    from fastapi import Depends, FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
    from video_service.admission_policy import AdmissionPolicy
    path = ROOT / 'apps/api/app/renewal.py'
    tree = ast.parse(path.read_text(encoding='utf8'))
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in {'session', 'request_boundary', 'JsonBodyLimit'}]
    app = FastAPI()
    accounts = SimpleNamespace(session=lambda cookie: {'user': {'id': ACTOR, 'role': 'user'}, 'csrf_token': 'csrf'} if cookie == 'valid' else None)
    ns = dict(app=app, Request=Request, HTTPException=HTTPException, JSONResponse=JSONResponse, accounts=accounts,
              cookie='test_session', hmac=hmac, origins={'https://unit.invalid'}, content_store=store,
              policy=AdmissionPolicy(), re=__import__('re'))
    for node in nodes:
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
    app.add_middleware(ns['JsonBodyLimit'], uploads=True)
    path = ROOT / 'apps/api/app/subtitle_copy_routes.py'
    spec = importlib.util.spec_from_file_location('unit_subtitle_copy_routes', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.mount_subtitle_copies(app, store, Depends(ns['session']))
    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)
    return app


def call(app, method='GET', path='/api/subtitle-copies', body=None, *, cookie='valid', csrf='csrf', origin='https://unit.invalid'):
    async def invoke():
        sent, pending = [], [dict(type='http.request', body=json.dumps(body, ensure_ascii=False).encode() if body is not None else b'', more_body=False)]
        async def receive():
            if pending:
                return pending.pop()
            await asyncio.Event().wait()
        async def send(message):
            sent.append(message)
        headers = [(b'host', b'unit.invalid'), (b'content-type', b'application/json'), (b'origin', origin.encode()), (b'cookie', ('test_session=' + cookie).encode()), (b'x-csrf-token', csrf.encode())]
        url, _, query = path.partition('?')
        await app(dict(type='http', http_version='1.1', method=method, scheme='https', path=url, raw_path=url.encode(), query_string=query.encode(), headers=headers, client=('unit', 1), server=('unit.invalid', 443), root_path=''), receive, send)
        return sent[0]['status'], json.loads(b''.join(v.get('body', b'') for v in sent))
    return asyncio.run(invoke())


def test_real_routes_save_requery_reopen_auth_csrf_origin_and_finite_body(store):
    app = actual_app(store)
    assert call(app, 'POST', body=payload(), cookie='absent')[0] == 401
    assert call(app, 'POST', body=payload(), csrf='bad')[0] == 403
    assert call(app, 'POST', body=payload(), origin='https://other.invalid')[0] == 403
    assert call(app)[1]['copies'] == []
    # Ordinary >64KiB document, not the old generic JSON bound.
    large = payload(srt=SRT.replace('둘째 줄', '문' * 25000))
    status, saved = call(app, 'POST', body=large)
    assert status == 201
    assert call(app, path='/api/subtitle-copies/' + COPY)[1]['srt'] == large['srt']
    assert call(app)[1]['copies'] == [saved]
    assert call(app, path='/api/subtitle-copies/' + COPY, cookie='absent')[0] == 401
    assert call(app, 'POST', body={**payload(), 'job_id': 'e' * 32})[0] == 422
    assert call(app, 'PUT', path='/api/subtitle-copies/' + COPY, body=payload())[0] == 405
    assert call(app, path='/api/subtitle-copies/' + 'f' * 32)[0] == 404
    assert call(app, 'POST', path='/api/other', body={'srt': 'x' * 66000})[0] == 413


def test_s3_authority_survives_new_cache_and_bounded_namespace(store, tmp_path):
    from test_ticket_artifacts import MemoryS3
    from video_service.object_store import S3ContentStore
    class Client(MemoryS3):
        def __init__(self):
            super().__init__()
            self.metadata, self.lists = {}, []
        def put_object(self, **request):
            super().put_object(**request)
            self.metadata[request['Key']] = request['Metadata']
        def get_object(self, **request):
            return {**super().get_object(**request), 'Metadata': self.metadata[request['Key']]}
        def list_objects_v2(self, **request):
            assert request['Prefix'] == 'renewal/subtitle-copies/'
            assert request['MaxKeys'] == 20
            self.lists.append(request)
            keys = sorted(k for k in self.objects if k.startswith(request['Prefix']) and k > request.get('StartAfter', ''))
            return {'Contents': [{'Key': k} for k in keys[:20]], 'IsTruncated': len(keys) > 20}
    client = Client()
    remote = S3ContentStore(client, 'synthetic-bucket', store.root, prefix='renewal')
    saved = service(remote).save(ACTOR, **payload())
    receipt = 'renewal/subtitle-copies/' + COPY + '.json'
    assert receipt in client.objects
    other = tmp_path / 'empty-cache'
    other.mkdir()
    reopened = service(S3ContentStore(client, 'synthetic-bucket', other, prefix='renewal'))
    assert reopened.list()['copies'] == [saved]
    assert reopened.get(COPY)['srt'] == SRT
    old_metadata = client.metadata[receipt]
    client.metadata[receipt] = {**old_metadata, 'sha256': '0' * 64}
    with pytest.raises(ValueError, match='digest mismatch'):
        reopened.get(COPY)
    client.metadata[receipt] = old_metadata
    del client.objects[receipt]
    assert reopened.list()['copies'] == []  # No stale cache as authority.
    assert len(client.lists) == 2
    for i in range(21):
        service(remote).save(ACTOR, **payload(f'{i:032x}'))
    first = reopened.list()
    assert len(first['copies']) == 20 and first['next_cursor'] == f'{19:032x}'
    second = reopened.list(first['next_cursor'])
    assert len(second['copies']) == 1 and second['next_cursor'] is None
    assert client.lists[-1]['StartAfter'] == 'renewal/subtitle-copies/' + f'{19:032x}' + '.json'


def test_maintenance_still_denies_new_routes():
    from video_service.admission_policy import AdmissionPolicy
    policy = AdmissionPolicy('maintenance', 'encode', 'a' * 32)
    for method, path in [('GET', '/api/subtitle-copies'), ('GET', '/api/subtitle-copies/' + COPY), ('POST', '/api/subtitle-copies')]:
        assert not policy.permits(method, path)


def test_finite_pages_literal_ids_cue_budget_and_integrity(store):
    from video_service.subtitle_copies import validate_srt
    native = SRT.replace('-3', '-1234567890123456789012345678901234567890')
    assert validate_srt(native)[1] == 2
    assert validate_srt(native.replace('00:00:01,000', '00:00:00,500'))[1] == 2  # SRT overlap allowed.
    cues = ''.join(f'{i}\n00:00:00,000 --> 00:00:01,000\nx\n\n' for i in range(10001))
    assert validate_srt(cues[:cues.rfind('10000\n')])[1] == 10000
    with pytest.raises(ValueError, match='10000'):
        validate_srt(cues)
    copies = service(store)
    for i in range(21):
        copies.save(ACTOR, **payload(f'{i:032x}'))
    first = copies.list()
    assert len(first['copies']) == 20 and first['next_cursor'] == f'{19:032x}'
    assert [row['id'] for row in copies.list(first['next_cursor'])['copies']] == [f'{20:032x}']
    assert copies.list(first['next_cursor'])['next_cursor'] is None
    receipt = store.root / 'subtitle-copies' / ('0' * 32 + '.json')
    raw = receipt.read_bytes()
    receipt.write_bytes(raw.replace(b'"cue_count":2', b'"cue_count":3'))
    with pytest.raises(ValueError, match='receipt'):
        copies.get('0' * 32)


def test_s3_denied_is_honest_403_without_publish_or_automatic_retry(store):
    from botocore.exceptions import ClientError
    from test_ticket_artifacts import MemoryS3
    from video_service.object_store import S3ContentStore
    class Denied(MemoryS3):
        writes = 0
        def put_object(self, **request):
            self.writes += 1
            raise ClientError({'ResponseMetadata': {'HTTPStatusCode': 403}, 'Error': {'Code': 'AccessDenied', 'Message': 'PRIVATE credentials'}}, 'PutObject')
    client = Denied()
    remote = S3ContentStore(client, 'synthetic-bucket', store.root, prefix='renewal')
    status, body = call(actual_app(remote), 'POST', body=payload())
    assert status == 403 and 'AccessDenied' in body['detail'] and 'PRIVATE' not in json.dumps(body)
    assert client.writes == 1 and client.objects == {}


def test_runtime_mount_and_package_discovery_include_real_routes():
    tree = ast.parse((ROOT / 'apps/api/app/renewal_routes.py').read_text(encoding='utf8'))
    mount = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mount_runtime')
    call = next(n for n in ast.walk(mount) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'mount_subtitle_copies')
    assert [ast.unparse(arg) for arg in call.args] == ['app', 'runtime.store', 'session_dependency']
    import tomllib
    shared = tomllib.loads((ROOT / 'packages/shared/pyproject.toml').read_text())
    api = tomllib.loads((ROOT / 'apps/api/pyproject.toml').read_text())
    assert shared['tool']['setuptools']['packages']['find']['include'] == ['video_service*']
    assert api['tool']['setuptools']['packages']['find']['include'] == ['app*']


def test_existing_cas_and_ticket_protocol_remain_unchanged(store, tmp_path):
    from test_ticket_artifacts import (
        test_ticket_bindings_are_real_paths_with_shared_cas_bytes,
        test_s3_ticket_binding_persists_remote_key_and_reopens_without_cache,
    )
    test_ticket_bindings_are_real_paths_with_shared_cas_bytes(tmp_path)
    test_s3_ticket_binding_persists_remote_key_and_reopens_without_cache(tmp_path)
