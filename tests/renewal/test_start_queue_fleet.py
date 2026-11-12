"""Production Fleet method AST over a small fake DB/driver; no PG or processes."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


class FleetDatabase:
    """SQL result adapter, not scheduling logic; read probes reject locks/writes."""
    def __init__(self):
        self.configs = {'analyze': {'enabled': True}, 'extract_audio': {'enabled': True}}
        self.instances = [
            dict(id='busy-a', agent_id='analyze', controller_id='own-controller',
                 state='ready', in_flight=1, last_assigned_at=None, completed=0, created_at='1'),
            dict(id='free-b', agent_id='extract_audio', controller_id='own-controller',
                 state='ready', in_flight=0, last_assigned_at=None, completed=0, created_at='2'),
        ]
        self.read_only = True
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if self.read_only:
            assert sql.startswith('SELECT ') and 'FOR ' not in sql, 'probe must only SELECT without row locks'
        if sql.startswith('SELECT ') and 'FROM agent_configurations' in sql:
            rows = [self.configs[params[0]]] if params[0] in self.configs else []
        elif sql.startswith('SELECT ') and 'FROM agent_instances' in sql:
            assert "state='ready'" in sql and 'in_flight=0' in sql and 'controller_id=%s' in sql
            assert 'ORDER BY last_assigned_at NULLS FIRST,completed,created_at,id' in sql and 'LIMIT 1' in sql
            rows = sorted(
                (row for row in self.instances if row['agent_id'] == params[0]
                 and row['controller_id'] == params[1] and row['state'] == 'ready' and row['in_flight'] == 0),
                key=lambda row: (row['last_assigned_at'] is not None, row['last_assigned_at'] or '',
                                 row['completed'], row['created_at'], row['id']),
            )[:1]
        elif sql.startswith('UPDATE agent_instances SET in_flight=1'):
            next(row for row in self.instances if row['id'] == params[0])['in_flight'] = 1
            rows = []
        elif sql.startswith("UPDATE agent_instances SET state='failed'"):
            next(row for row in self.instances if row['id'] == params[0])['state'] = 'failed'
            rows = []
        else:
            raise AssertionError('Unexpected Fleet SQL: ' + sql)
        return SimpleNamespace(fetchone=lambda: deepcopy(rows[0]) if rows else None)


@pytest.fixture
def fleet_case():
    path = ROOT / 'packages/shared/video_service/postgres/fleet.py'
    original = next(node for node in ast.parse(path.read_text(encoding='utf8')).body
                    if isinstance(node, ast.ClassDef) and node.name == 'Fleet')
    methods = [node for node in original.body if isinstance(node, ast.FunctionDef)
               and node.name in {'can_reserve', 'reserve'}]
    cls = ast.ClassDef(name='Fleet', bases=[], keywords=[], body=methods, decorator_list=[])
    tree = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = {}
    exec(compile(tree, str(path), 'exec'), namespace)
    fleet = namespace['Fleet']()
    db, alive_calls, live = FleetDatabase(), [], {'busy-a', 'free-b'}

    def forbidden(*args, **kwargs):
        raise AssertionError('Availability must not refresh/reserve/own/configure/signal processes')

    def alive(identity):
        alive_calls.append(identity)
        return identity in live

    fleet.controller_id = 'own-controller'
    fleet.driver = SimpleNamespace(alive=alive, start=forbidden, stop=forbidden,
                                   request=forbidden, pid=forbidden, supports=forbidden)
    fleet._refresh = fleet._ownership = fleet.get = fleet.configure = forbidden
    return fleet, db, alive_calls, live


@pytest.mark.parametrize('condition,expected', [
    ('free', True), ('missing-config', False), ('disabled', False), ('no-driver', False),
    ('busy', False), ('other-controller', False), ('not-ready', False), ('dead', False),
])
def test_fleet_availability_is_select_only_and_preserves_authority(fleet_case, condition, expected):
    fleet, db, alive_calls, live = fleet_case
    row = db.instances[1]
    if condition == 'missing-config':
        del db.configs['extract_audio']
    elif condition == 'disabled':
        db.configs['extract_audio']['enabled'] = False
    elif condition == 'no-driver':
        fleet.driver = None
    elif condition == 'busy':
        row['in_flight'] = 1
    elif condition == 'other-controller':
        row['controller_id'] = 'other-controller'
    elif condition == 'not-ready':
        row['state'] = 'draining'
    elif condition == 'dead':
        live.remove('free-b')
    before = deepcopy((db.configs, db.instances, live))
    fleet.reserve = lambda *args: pytest.fail('Availability called reserve')
    assert fleet.can_reserve(db, 'extract_audio') is expected
    assert before == (db.configs, db.instances, live)
    assert all(sql.startswith('SELECT ') and 'FOR ' not in sql for sql, _ in db.calls)
    assert alive_calls == (['free-b'] if condition in {'free', 'dead'} else [])


def test_fleet_probe_mirrors_first_candidate_without_refreshing_dead_row(fleet_case):
    fleet, db, alive_calls, live = fleet_case
    db.instances.append({**db.instances[1], 'id': 'second-live', 'created_at': '3'})
    live.remove('free-b')
    live.add('second-live')
    before = deepcopy(db.instances)
    assert not fleet.can_reserve(db, 'extract_audio')
    assert db.instances == before and alive_calls == ['free-b']
