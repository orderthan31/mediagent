"""Offline API/privacy gates plus opt-in native PostgreSQL guards."""
import pytest
from video_service.postgres import Conflict
from video_service.postgres.unit_recovery import clean_error, public_unit, validate_body


def test_error_codes_never_echo_provider_text():
    assert clean_error('provider_timeout') == 'provider_timeout'
    assert clean_error('https://secret.invalid/key?token=secret') == 'recovery_attempt_failed'
    assert clean_error('sk-secret') == 'recovery_attempt_failed'


def test_public_unit_is_allowlisted():
    row = public_unit({'index': 0, 'status': 'failed', 'input_sha256': 'a'*64,
                       'pin': {'api_key': 'secret'}, 'source': b'private',
                       'error_code': 'secret bearer token'})
    assert 'secret' not in str(row)
    assert row['index'] == 0


def test_revision_validation_rejects_bool_and_unknown_keys():
    body = {'job_revision': 1, 'recovery_revision': 0, 'context_sha256': 'a'*64, 'decisions': []}
    validate_body(body)
    with pytest.raises(Conflict):
        validate_body({**body, 'job_revision': True})
    with pytest.raises(Conflict):
        validate_body({**body, 'pin': {}})


def test_native_recovery_tables_and_immutable_guards(db):
    with db.connection() as c:
        assert c.execute("SELECT to_regclass('model_role_unit_recoveries') AS t").fetchone()['t']
        names = {r['tgname'] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='model_role_unit_attempts'::regclass").fetchall()}
        assert 'unit_attempt_immutable' in names
        assert 'unit_attempt_no_delete' in names

from test_foundation import db
