"""Bounded owner start preferences. No DB, process discovery or execution effects."""
import json

from .canonical import canonical, digest
from .content_store import ID

MAX_MEMBERS = 1000
MAX_POLICY_BYTES = 384 * 1024
MAX_REVISION = 9007199254740991


class QueueConflict(ValueError):
    pass


class QueueMissing(LookupError):
    pass


class QueueUnavailable(ValueError):
    pass


def identity(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid queue identity')
    return value


def initial_policy(owner):
    return dict(version=1, owner_id=identity(owner), revision=0, paused=False, order=[], members=[])


def claim_digest(job_id, consent_id):
    return digest(dict(job=identity(job_id), consent=identity(consent_id), start_queue_policy=1))


def validate_policy(value, owner=None):
    if not isinstance(value, dict) or set(value) != {
        'version', 'owner_id', 'revision', 'paused', 'order', 'members'
    }:
        raise ValueError('Invalid start queue policy')
    if (type(value['version']) is not int or value['version'] != 1
            or type(value['revision']) is not int or not 0 <= value['revision'] <= MAX_REVISION
            or type(value['paused']) is not bool):
        raise ValueError('Invalid start queue revision/state')
    identity(value['owner_id'])
    if owner is not None and value['owner_id'] != identity(owner):
        raise ValueError('Start queue owner differs')
    members, order = value['members'], value['order']
    if (not isinstance(members, list) or len(members) > MAX_MEMBERS
            or not isinstance(order, list) or len(order) > MAX_MEMBERS):
        raise ValueError('Start queue membership bound exceeded')
    ids, claims = set(), set()
    for member in members:
        if not isinstance(member, dict) or set(member) != {'job_id', 'claim_id', 'generation'}:
            raise ValueError('Invalid start queue membership')
        identity(member['job_id'])
        identity(member['claim_id'])
        if (type(member['generation']) is not int or not 0 <= member['generation'] <= MAX_REVISION
                or member['job_id'] in ids or member['claim_id'] in claims):
            raise ValueError('Duplicate/invalid start queue membership')
        ids.add(member['job_id'])
        claims.add(member['claim_id'])
    for id in order:
        identity(id)
    if len(set(order)) != len(order) or not set(order) <= ids:
        raise ValueError('Invalid start queue order')
    return value


def encode_policy(value):
    raw = canonical(validate_policy(value))
    if len(raw) > MAX_POLICY_BYTES:
        raise ValueError('Start queue policy size exceeded')
    return raw


def decode_policy(raw, owner):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_POLICY_BYTES:
        raise ValueError('Start queue policy size exceeded')
    value = validate_policy(json.loads(raw), owner)
    if canonical(value) != raw:
        raise ValueError('Noncanonical start queue policy')
    return value
