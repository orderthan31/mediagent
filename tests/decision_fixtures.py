"""Explicit controlled provider/executor fixtures; never wire into production."""
import hashlib
import json
from pathlib import Path
from video_service.decision_tickets import DecisionTicketStore

PROFILE = {'id': 'controlled-offline-fixture', 'revision': '1', 'schema_version': 1, 'paid': False}


class ControlledProvider:
    descriptor = PROFILE

    def __init__(self, value=None, error=None):
        self.value = value or {'version': 1, 'label': 'pass', 'confidence': .9, 'reason': 'Controlled fixture only, NOT external model inference'}
        self.error = error
        self.calls = []

    def decide(self, context):
        self.calls.append(context)
        if self.error:
            raise self.error
        return self.value


class Harness:
    def __init__(self, root, graph, provider=None):
        self.root = Path(root)
        self.source = self.root / 'controlled-input.bin'
        self.source.write_bytes(b'controlled fixture input; no user media')
        self.provider = provider or ControlledProvider()
        self.store = DecisionTicketStore(self.root, adapter_profile=self.provider.descriptor)
        self.graph = graph
        asset = {'asset_id': 'b'*32, 'size_bytes': self.source.stat().st_size, 'source_mtime_ns': self.source.stat().st_mtime_ns}
        self.ticket = self.store.create('isolated-new', {'definition_id': graph['id'], 'definition_revision': 1, 'asset_id': asset['asset_id'], 'options': {}}, lambda: graph, lambda: asset)
        self.prefs = {'revision': 0, 'api_keys': {}}
        self.calls = []
        self.last = None
        self.number = 0

    def factory(self, bound, options, admitted):
        def execute(step, inputs, work, check):
            self.calls.append({'node': step['id'], 'serving_revision': bound['revision'], 'input_sha256': {p: hashlib.sha256(v.read_bytes()).hexdigest() for p,v in inputs.items()}})
            outputs = {}
            for port in step['outputs']:
                path = work / (port + '.fixture')
                path.write_text(json.dumps({'mode': 'controlled_fixture_NOT_media', 'node': step['id'], 'port': port}))
                outputs[port] = path
            return outputs
        execute.decision_provider = self.provider
        return execute

    def run(self):
        store, identity = self.store, self.ticket['id']
        current = store.get(identity)
        plan = store.plan(identity, self.prefs)
        confirmed = store.confirm(identity, current['revision'], plan['token'], bool(plan['paid_roles']), self.prefs)
        self.last = {'request_id': 'isolated-'+str(self.number), 'revision': confirmed['revision'], 'token': plan['token'], 'operation': 'start' if self.number == 0 else 'continue'}
        self.number += 1
        return store.run(identity, self.prefs, self.source, self.factory, **self.last)
