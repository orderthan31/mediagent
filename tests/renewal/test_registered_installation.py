"""Installed registered-model wiring; no real provider or paid requests."""
import inspect

from app import operator, server


def test_installed_entrypoints_require_separate_explicit_registered_enablement():
    assert {'registered_model_config_file', 'registered_broker_config_file'} <= server.OPTIONAL_FIELDS
    assert 'enable_registered' in inspect.signature(operator.runtime_components).parameters
    assert 'allow_controlled_models' in inspect.signature(operator.runtime_components).parameters


def test_official_clis_expose_explicit_enablement_and_independent_registered_worker(capsys, monkeypatch):
    import pytest
    monkeypatch.setattr('sys.argv', ['app.server', '--help'])
    with pytest.raises(SystemExit) as exited:
        server.main()
    assert exited.value.code == 0
    text = capsys.readouterr().out
    assert '--enable-registered-models' in text
    assert '--allow-controlled-models' in text
    with pytest.raises(SystemExit) as exited:
        operator.main(['--help'])
    assert exited.value.code == 0
    text = capsys.readouterr().out
    assert 'consume-registered-models' in text
    assert 'declare-registered-topology' in text


def test_installed_address_policy_is_explicit_pinned_and_controlled_only_in_isolation(tmp_path, monkeypatch):
    import importlib.util
    import json
    assert importlib.util.find_spec('video_service.registered_transport') is not None, 'Installed address-pinned transport missing'
    from video_service.registered_transport import RegisteredPolicy
    path = tmp_path / 'policy.json'
    value = {'version': 1, 'mode': 'controlled_http', 'origins': [{'origin': 'http://127.0.0.1:9419', 'addresses': ['127.0.0.1']}]}
    path.write_text(json.dumps(value))
    import pytest
    with pytest.raises(ValueError):
        RegisteredPolicy.from_file(path)
    monkeypatch.delenv('MIDEAGENT_TEST_DISPOSABLE', raising=False)
    with pytest.raises(ValueError):
        RegisteredPolicy.from_file(path, allow_controlled=True)
    monkeypatch.setenv('MIDEAGENT_TEST_DISPOSABLE', '1')
    policy = RegisteredPolicy.from_file(path, allow_controlled=True)
    assert policy.mode == 'controlled_http'
    assert policy.approved_origins == frozenset({'http://127.0.0.1:9419'})
    value['mode'] = 'external'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        RegisteredPolicy.from_file(path)


def test_pinned_transport_refuses_unapproved_origin_before_socket_io(tmp_path, monkeypatch):
    import json

    import httpx
    from video_service.registered_transport import RegisteredPolicy
    path = tmp_path / 'policy.json'
    path.write_text(json.dumps({'version': 1, 'mode': 'controlled_http', 'origins': [{'origin': 'http://127.0.0.1:9419', 'addresses': ['127.0.0.1']}]}))
    monkeypatch.setenv('MIDEAGENT_TEST_DISPOSABLE', '1')
    def forbidden(*args, **kwargs):
        raise AssertionError('Network must not be entered')
    monkeypatch.setattr('socket.create_connection', forbidden)
    transport = RegisteredPolicy.from_file(path, allow_controlled=True).transport()
    import pytest
    with pytest.raises(httpx.TransportError, match='registered_request_denied'):
        transport.handle_request(httpx.Request('POST', 'http://127.0.0.1:9420/v1'))


def test_registered_queue_carries_only_exact_attempt_reference_and_rejects_cpu_wire():
    import importlib.util
    assert importlib.util.find_spec('video_service.registered_broker') is not None, 'Registered independent delivery missing'
    import pytest
    from video_service.rabbitmq_transport import InvalidMessage, decode
    from video_service.registered_broker import decode_reference, reference
    command = {'protocol_version': 1, 'run_id': 'a' * 32, 'attempt_id': 'b' * 32, 'generation': 1,
               'agent': {'id': 'translate', 'revision': '1'}, 'inputs': {}, 'options': {},
               'translation': {'candidates': [{'credential_ref': 'db:' + 'd' * 32}], 'source_language': 'en', 'target_language': 'ko'}}
    delivery = reference('c' * 32, command)
    value = decode_reference(delivery)
    assert value['attempt_id'] == command['attempt_id']
    assert b'credential_ref' not in delivery.body and b'target_language' not in delivery.body
    with pytest.raises(InvalidMessage):
        decode(delivery)
    from dataclasses import replace
    with pytest.raises(InvalidMessage):
        decode_reference(replace(delivery, correlation_id='f' * 32))


def test_registered_reference_rejects_mismatched_model_kind_and_engine_version():
    import pytest
    from video_service.rabbitmq_transport import InvalidMessage
    from video_service.registered_broker import reference
    command = {'protocol_version': 1, 'run_id': 'a' * 32, 'attempt_id': 'b' * 32,
               'agent': {'id': 'translate', 'revision': '1'}, 'transcription': {'candidates': []}}
    with pytest.raises(InvalidMessage):
        reference('c' * 32, command)
    command.update(protocol_version=2, translation=command.pop('transcription'))
    with pytest.raises(InvalidMessage):
        reference('c' * 32, command)


def test_api_accepts_only_bound_registered_broker_runtimes_not_arbitrary_injection():
    from types import SimpleNamespace

    import pytest
    from app.renewal import create_app
    database = object()
    credentials = SimpleNamespace(database=database)
    translation = SimpleNamespace(credentials=credentials, policy_sha256='a' * 64)
    transcription = SimpleNamespace(credentials=credentials, policy_sha256='a' * 64)
    factory = lambda: None
    factory.registered_factory = lambda: None
    factory.registered_policy_sha256 = 'a' * 64
    factory.translation_runtime = translation
    factory.transcription_runtime = transcription
    args = {'allowed_origins': ['http://127.0.0.1:9418'], 'secure_cookies': False,
            'content_store': SimpleNamespace(storage_kind='s3'), 'local_execution': True,
            'credential_store': credentials, 'translation_runtime': translation,
            'transcription_runtime': transcription, 'broker_factory': factory}
    app = create_app(database, **args)
    assert any(route.path == '/api/renewal/jobs/{identity}/run' for route in app.routes)
    factory.registered_policy_sha256 = 'b' * 64
    with pytest.raises(ValueError):
        create_app(database, **args)


def test_private_bootstrap_opt_in_builds_both_runtimes_with_same_encrypted_resolver(tmp_path, monkeypatch):
    import json
    import os
    import secrets

    import pytest
    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return str(path)
    key_file = tmp_path / 'key'
    key_file.write_bytes(os.urandom(32))
    access = tmp_path / 'access'
    secret = tmp_path / 'secret'
    access.write_text(secrets.token_urlsafe(24))
    secret.write_text(secrets.token_urlsafe(24))
    broker = write('mq.json', {'namespace': 'registered-install-unit', 'url_file': str(tmp_path / 'mq-url'), 'allow_loopback': True})
    objects = write('objects.json', {'endpoint': 'http://127.0.0.1:9972', 'bucket': 'registered-unit', 'region': 'us-east-1',
                                    'prefix': 'unit', 'cache_root': str(tmp_path / 'cache'),
                                    'access_key_file': str(access), 'secret_key_file': str(secret)})
    policy = write('models.json', {'version': 1, 'mode': 'controlled_http', 'origins': [{'origin': 'http://127.0.0.1:9419', 'addresses': ['127.0.0.1']}]})
    config = {'admission_policy': {'mode': 'normal'}, 'content_root': str(tmp_path / 'local'), 'object_config_file': objects, 'credential_key_file': str(key_file),
              'broker_config_file': broker, 'registered_broker_config_file': broker, 'registered_model_config_file': policy}
    database = object()
    _, _, disabled = operator.runtime_components(database, config, enable_broker=True)
    assert getattr(disabled, 'registered_factory', None) is None
    monkeypatch.setenv('MIDEAGENT_TEST_DISPOSABLE', '1')
    store, credentials, factory = operator.runtime_components(database, config, enable_broker=True, enable_registered=True, allow_controlled_models=True)
    assert store.storage_kind == 's3'
    assert factory.translation_runtime.credentials is credentials
    assert factory.transcription_runtime.credentials is credentials
    assert factory.translation_runtime.policy_sha256 == factory.registered_policy_sha256
    assert factory.transcription_runtime.policy_sha256 == factory.registered_policy_sha256
    with pytest.raises(ValueError):
        operator.runtime_components(database, config, enable_registered=True, allow_controlled_models=True)
    with pytest.raises(ValueError):
        operator.runtime_components(database, {**config, 'admission_policy': {'mode': 'maintenance', 'agent_id': 'encode', 'slot_id': 'a' * 32, 'handover': False}}, enable_broker=True, enable_registered=True, allow_controlled_models=True)


def test_pinned_tls_uses_approved_address_original_sni_and_refuses_redirect_and_bad_cert(tmp_path, monkeypatch):
    import datetime
    import hmac
    import json
    import secrets
    import socket
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpx
    import pytest
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    from video_service.registered_transport import RegisteredPolicy

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'registered-fixture.invalid')])
    now = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
            .not_valid_after(now+datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('registered-fixture.invalid')]), critical=False)
            .sign(key, hashes.SHA256()))
    ca, private_key = tmp_path/'ca.crt', tmp_path/'tls.key'
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    token = secrets.token_urlsafe(24)
    requests, sni, addresses = [], [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            matched = hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+token)
            requests.append({'host': self.headers['Host'], 'key_matches': matched, 'path': self.path})
            self.send_response(307 if self.path=='/redirect' else 200)
            if self.path=='/redirect':
                self.send_header('Location', 'https://unapproved.invalid/steal')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(ca, private_key)
    server_context.set_servername_callback(lambda _socket, host, _context: sni.append(host))
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    actual_connect = socket.create_connection
    def connect(address, timeout, **kwargs):
        assert address == ('1.1.1.1', server.server_port)
        addresses.append(address)
        # TEST ONLY: the public pin is mapped to this test's loopback TLS peer.
        # This prevents any public socket; production never resolves the hostname.
        return actual_connect(('127.0.0.1', server.server_port), timeout=timeout, **kwargs)
    monkeypatch.setattr(socket, 'create_connection', connect)
    path = tmp_path/'policy.json'
    value = {'version': 1, 'mode': 'external', 'ca_file': str(ca),
             'origins': [{'origin': 'https://registered-fixture.invalid:'+str(server.server_port), 'addresses': ['1.1.1.1']}]}
    path.write_text(json.dumps(value))
    try:
        policy = RegisteredPolicy.from_file(path)
        with httpx.Client(transport=policy.transport(), trust_env=False, follow_redirects=True) as client:
            response = client.post(value['origins'][0]['origin']+'/v1', json={}, headers={'Authorization': 'Bearer '+token})
            assert response.status_code == 200
            with pytest.raises(httpx.TransportError, match='registered_request_denied'):
                client.post(value['origins'][0]['origin']+'/redirect', json={}, headers={'Authorization': 'Bearer '+token})
        assert len(addresses) == 2 and all(row['key_matches'] for row in requests)
        assert sni == ['registered-fixture.invalid', 'registered-fixture.invalid']
        value['origins'][0]['origin'] = 'https://wrong-fixture.invalid:'+str(server.server_port)
        path.write_text(json.dumps(value))
        with (
            httpx.Client(transport=RegisteredPolicy.from_file(path).transport(), trust_env=False) as client,
            pytest.raises(httpx.TransportError, match='registered_transport_failure'),
        ):
            client.post(value['origins'][0]['origin'], json={}, headers={'Authorization': 'Bearer '+token})
        value['origins'][0]['origin'] = 'https://registered-fixture.invalid:'+str(server.server_port)
        del value['ca_file']
        path.write_text(json.dumps(value))
        with (
            httpx.Client(transport=RegisteredPolicy.from_file(path).transport(), trust_env=False) as client,
            pytest.raises(httpx.TransportError, match='registered_transport_failure'),
        ):
            client.post(value['origins'][0]['origin'], json={}, headers={'Authorization': 'Bearer '+token})
        assert len(requests) == 2  # Neither wrong-host nor untrusted-CA peer received key bytes.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
