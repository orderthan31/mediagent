"""Execution-host service. No HTTP listener and no automatic target discovery.

The API writes the remote mailbox. Only this separately installed, explicitly
configured host has native runtime authority and the private ACK signing key.
Database/storage locations are independent of the engine socket's machine.
"""
import argparse
import http.client
import json
import signal
import socket
import threading
from pathlib import Path

from .agent_control import ControlError, Target


class PinnedEngine:
    def __init__(self, socket_path, targets, *, transport=None):
        if not isinstance(socket_path, str) or not socket_path.startswith('/'):
            raise ControlError('explicit_engine_socket_required')
        self.socket_path = socket_path
        self.targets = {target.container_id: target for target in targets}
        if not self.targets or len(self.targets) != len(targets):
            raise ControlError('unique_pinned_targets_required')
        self.transport = transport or self._request

    def _request(self, method, path):
        connection = http.client.HTTPConnection('localhost', timeout=30)
        try:
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.sock.settimeout(30)
            connection.sock.connect(self.socket_path)
            connection.request(method, path)
            response = connection.getresponse()
            raw = response.read(8 * 1024 * 1024 + 1)
            if response.status not in (200, 204) or len(raw) > 8 * 1024 * 1024:
                raise ControlError('native_engine_outcome_unknown')
            return raw.decode()
        except (OSError, http.client.HTTPException, UnicodeError):
            raise ControlError('native_engine_outcome_unknown') from None
        finally:
            connection.close()

    def _inspect(self, identity):
        value = json.loads(self.transport('GET', '/v1.45/containers/' + identity + '/json'))
        target = self.targets[identity]
        if (value['Id'] != identity or value['Image'] != target.image_id
                or any(value['Config']['Labels'].get(k) != v for k, v in target.labels)):
            raise ControlError('control_target_identity_mismatch')
        return value

    def __call__(self, args):
        if not isinstance(args, list):
            raise ControlError('native_operation_not_allowed')
        inspect = len(args) >= 3 and args[:2] == ['container', 'inspect']
        start = len(args) == 3 and args[:2] == ['container', 'start']
        stop = len(args) == 5 and args[:4] == ['container', 'kill', '--signal', 'SIGTERM']
        ids = args[2:] if inspect else args[-1:] if start or stop else []
        if not ids or any(identity not in self.targets for identity in ids):
            raise ControlError('native_operation_not_allowed')
        try:
            rows = [self._inspect(identity) for identity in ids]
            if inspect:
                return json.dumps(rows)
            suffix = '/start' if start else '/kill?signal=SIGTERM'
            return self.transport('POST', '/v1.45/containers/' + ids[0] + suffix)
        except (ValueError, KeyError, TypeError):
            raise ControlError('invalid_control_observation') from None


def run(config, *, handover_bindings=None):
    from .control_ack_receipts import AckReceipts
    from .durable_control import BrokerReports, DurableHost, SignalControl
    from .postgres import Database
    from .postgres.control_recovery import ControlRecovery
    from .postgres.remote_control import RemoteControl

    expected = {'database_dsn_file', 'receipt_root', 'receipt_key_file', 'groups', 'docker_socket'}
    if not isinstance(config, dict) or set(config) != expected:
        raise ControlError('invalid_host_configuration')
    for field in ('database_dsn_file', 'receipt_root', 'receipt_key_file', 'docker_socket'):
        if not isinstance(config[field], str) or not Path(config[field]).is_absolute():
            raise ControlError('absolute_host_path_required')
    if not isinstance(config['groups'], dict) or not config['groups']:
        raise ControlError('explicit_host_groups_required')
    groups, slots, profiles = {}, {}, {}
    for group, spec in config['groups'].items():
        if set(spec) != {'family', 'role', 'slots'} or not isinstance(spec['slots'], list):
            raise ControlError('invalid_host_group')
        profiles[group] = (spec['family'], spec['role'])
        groups[group] = tuple(Target(row['container_id'], row['image_id'],
                                    tuple(sorted(row['labels'].items()))) for row in spec['slots'])
        slots[group] = [row['worker_id'] for row in spec['slots']]
    database = Database(Path(config['database_dsn_file']).read_text().strip())
    store = RemoteControl(database)
    from .postgres.target_handover import TargetHandover
    from .target_handover import descriptor, resolve_active, target_from
    approved = handover_bindings or {}
    if not isinstance(approved, dict) or set(approved) - set(groups):
        raise ControlError('invalid_handover_bindings')
    for group, bound in groups.items():
        if store.has(group):
            if len(bound) != 1 and group in approved:
                raise ControlError('handover_requires_exactly_one_slot')
            if len(bound) == 1:
                configured = descriptor(bound[0], slots[group][0])
                resolved = resolve_active(TargetHandover(store), group, configured, approved.get(group))
                groups[group] = (target_from(resolved),)
    targets = tuple(target for group in groups.values() for target in group)
    engine = PinnedEngine(config['docker_socket'], targets)
    adapter = SignalControl(groups, runner=engine)
    # Validate every local pin/policy before provisioning even one mailbox group.
    for group in groups:
        adapter.details(group)
    receipts = AckReceipts(config['receipt_root'], Path(config['receipt_key_file']).read_bytes())
    host = DurableHost(store, adapter, slots, BrokerReports(database, profiles),
                       receipts=receipts, recovery=ControlRecovery(store))
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    try:
        while not stopping.is_set():
            host.step()
            stopping.wait(.25)
    finally:
        host.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-file', required=True)
    parser.add_argument('--enable-control', action='store_true')
    parser.add_argument('--handover-bindings-file')
    args = parser.parse_args()
    if not args.enable_control:
        parser.error('Host enrollment and execution require --enable-control')
    try:
        raw = Path(args.config_file).read_bytes()
        if len(raw) > 32768:
            raise ControlError('invalid_host_configuration')
        bindings = None
        if args.handover_bindings_file:
            binding_raw = Path(args.handover_bindings_file).read_bytes()
            if len(binding_raw) > 32768:
                raise ControlError('invalid_handover_bindings')
            bindings = json.loads(binding_raw)
        run(json.loads(raw), handover_bindings=bindings)
    except Exception:
        # Never expose DSNs, engine inspect environment or native diagnostics.
        print(json.dumps({'status': 'failed', 'code': 'fixed_host_control_stopped'}), flush=True)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
