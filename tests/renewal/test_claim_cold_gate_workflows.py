"""Public workflow routing and full-preflight freshness through actual Execution."""
from copy import deepcopy

import pytest
from psycopg.types.json import Jsonb

from test_claim_cold_gate import admin, db, movie, prepared, observe, demands, counts
from test_agent_control_execution import branching
from test_agent_control_workflow import node, graph
from video_service.canonical import digest
from video_service.postgres import Conflict


def conversion():
    return graph([node('convert', 'video_conversion_agent')], [], video='video')


@pytest.mark.parametrize('selection', ['a', 'b'])
def test_control_routing_only_demands_selected_branch(db, admin, movie, tmp_path, selection):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, branching(selection))
    # First sweep must materialize the select and unselected skip, not shortcut.
    assert runtime.claim_next(owner, job['id']) is None
    assert client.content_reads
    pending = demands(db, job)
    chosen = 'left' if selection == 'a' else 'right'
    assert [p['node_id'] for p in pending] == [chosen + '__encode']
    assert pending[0]['node_run_id'] is None
    client.calls.clear()
    assert runtime.claim_next(owner, job['id']) is None
    assert not client.content_reads
    assert demands(db, job) == pending
    assert counts(db, job) == (2, 0, 0)  # select + unselected branch skip


@pytest.mark.parametrize('change', ['cancel', 'capacity', 'snapshot', 'claim'])
def test_public_preflight_releases_locks_and_rejects_fresh_drift(db, admin, movie, tmp_path, monkeypatch, change):
    from test_claim_cold_gate_model import prepared_model
    runtime, owner, job, client, _, _ = prepared_model(db, admin, movie, tmp_path, monkeypatch)
    assert job['snapshot'].get('audio_pipeline_policy')
    assert runtime.claim_next(owner, job['id']) is None
    assert not client.content_reads
    observe(db, role='transcription')
    preflight = runtime._preflight_cpu_inputs
    checked = []
    before = counts(db, job)

    def verify_then_change(*args, **kwargs):
        verified = preflight(*args, **kwargs)
        assert verified and client.content_reads
        with db.connection() as conn:
            conn.execute("SET LOCAL lock_timeout='500ms'")
            assert conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) locked", ('start-queue:' + owner,)).fetchone()['locked']
            conn.execute('SELECT id FROM jobs WHERE id=%s FOR UPDATE NOWAIT', (job['id'],))
            assert conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended('agent-pool-capacity:transcription',0)) locked").fetchone()['locked']
            if change == 'cancel':
                conn.execute('UPDATE jobs SET cancel_requested=true WHERE id=%s', (job['id'],))
            elif change == 'capacity':
                conn.execute("UPDATE agent_pool_instances SET phase='busy' WHERE role='transcription'")
            elif change == 'claim':
                conn.execute('UPDATE jobs SET active_claim_id=NULL WHERE id=%s', (job['id'],))
            else:
                snapshot = deepcopy(job['snapshot'])
                snapshot['definition']['name'] = 'synthetic drift during verification'
                from psycopg.errors import CheckViolation
                with pytest.raises(CheckViolation, match='snapshot is immutable'):
                    with conn.transaction():
                        conn.execute('UPDATE jobs SET snapshot=%s,snapshot_sha256=%s WHERE id=%s', (Jsonb(snapshot), digest(snapshot), job['id']))
                # SQL forbids snapshot mutation. Also prove stale staged evidence
                # cannot bypass the final context check; no trigger is weakened.
                verified = {**verified, 'snapshot_sha256': digest(snapshot)}
        checked.append(True)
        return verified

    monkeypatch.setattr(runtime, '_preflight_cpu_inputs', verify_then_change)
    if change == 'snapshot':
        with pytest.raises(Conflict, match='context changed'):
            runtime.claim_next(owner, job['id'])
    else:
        assert runtime.claim_next(owner, job['id']) is None
    assert checked == [True] and counts(db, job) == before
    assert demands(db, job)[0]['node_run_id'] is None


def test_ready_public_path_still_uses_fresh_fleet_reservation(db, admin, movie, tmp_path, monkeypatch):
    runtime, owner, job, client = prepared(db, admin, movie, tmp_path, conversion())
    observe(db)

    class LostFleet:
        def __init__(self):
            self.reservations = 0
        def can_reserve(self, *args):
            return True
        def reserve(self, *args):
            self.reservations += 1
            return None

    fleet = LostFleet()
    runtime.fleet = fleet
    assert runtime.claim_next(owner, job['id']) is None
    assert fleet.reservations == 1 and client.content_reads
    assert counts(db, job) == (0, 0, 0)
