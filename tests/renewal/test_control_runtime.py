"""Only explicit pinned native operations may leave the trusted host runner."""
import json
import pytest
from video_service.agent_control import ControlError, Target


def test_host_engine_rejects_other_targets_and_arbitrary_operations():
    from video_service.control_runtime import PinnedEngine
    calls = []
    target = Target('a' * 64, 'sha256:' + 'b' * 64,
                    (('com.docker.compose.project', 'p'), ('com.docker.compose.service', 'encode')))
    def transport(method, path):
        calls.append((method, path))
        if method == 'GET':
            return json.dumps({'Id': target.container_id, 'Image': target.image_id,
                               'Config': {'Labels': dict(target.labels)}})
        return ''
    engine = PinnedEngine('/var/run/docker.sock', (target,), transport=transport)
    assert json.loads(engine(['container', 'inspect', target.container_id]))[0]['Id'] == target.container_id
    assert engine(['container', 'start', target.container_id]) == ''
    assert engine(['container', 'kill', '--signal', 'SIGTERM', target.container_id]) == ''
    original = len(calls)
    for command in [
        ['container', 'inspect', 'c' * 64], ['container', 'start', 'encode'],
        ['container', 'kill', '--signal', 'SIGKILL', target.container_id],
        ['container', 'stop', target.container_id], ['container', 'rm', target.container_id],
        ['exec', target.container_id, 'sh'],
    ]:
        with pytest.raises(ControlError):
            engine(command)
    assert len(calls) == original
    assert calls[-1] == ('POST', '/v1.45/containers/' + target.container_id + '/kill?signal=SIGTERM')


def test_host_engine_rechecks_pins_before_native_mutation():
    from video_service.control_runtime import PinnedEngine
    target = Target('a' * 64, 'sha256:' + 'b' * 64,
                    (('com.docker.compose.project', 'p'), ('com.docker.compose.service', 'encode')))
    calls = []
    def transport(method, path):
        calls.append((method, path))
        return json.dumps({'Id': target.container_id, 'Image': 'sha256:' + 'c' * 64,
                           'Config': {'Labels': dict(target.labels)}})
    engine = PinnedEngine('/var/run/docker.sock', (target,), transport=transport)
    with pytest.raises(ControlError):
        engine(['container', 'start', target.container_id])
    assert all(method == 'GET' for method, _ in calls)
