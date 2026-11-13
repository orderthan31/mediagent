"""New automatic budgets: immutable normalized work × frozen candidate width.

Workflow/snapshot options retain ``auto``. Only a new input-bound command receives
an integer; historical numeric commands are neither reinterpreted nor rewritten.
No provider calls, duration estimates, retries, or observed-request counters.
"""
import json
import wave

from .canonical import digest

KINDS = {'transcribe': 'transcription', 'translate': 'translation'}
POLICIES = {'transcribe': 'bounded_60s_v1', 'translate': 'bounded_100x16k_v1'}


def automatic(command):
    return (command['agent']['id'] in KINDS
            and command.get('options', {}).get('max_model_calls') == 'auto')


def resolve(store, owner, command, *, policy_version):
    role = command['agent']['id']
    config = command[KINDS[role]]
    value = command['options'].get('max_model_calls')
    if value != 'auto':
        if not isinstance(value, str) or not value.isdecimal() or int(value) < 1:
            raise ValueError('explicit_model_call_cap_required')
        return {'max_model_calls': int(value)}
    width = len(config['candidates'])
    if not 1 <= width <= 4 or config.get('batch_policy') != POLICIES[role]:
        raise ValueError('automatic_budget_requires_bounded_candidates_and_batches')
    if role == 'transcribe':
        from .audio_batches import MAX_BATCH_AUDIO_BYTES, MAX_BATCH_AUDIO_SECONDS, RATE
        reference = command['inputs']['audio']
        if not 44 <= reference['bytes'] <= MAX_BATCH_AUDIO_BYTES:
            raise ValueError('invalid_automatic_budget_audio_size')
        # CAS path verifies the immutable digest and length. Stream the complete
        # PCM payload, not merely a WAV header or the original media's duration.
        with wave.open(str(store.path(owner, reference)), 'rb') as stream:
            frames = stream.getnframes()
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                    stream.getcomptype()) != (1, 2, RATE, 'NONE') or not 0 < frames <= RATE * MAX_BATCH_AUDIO_SECONDS:
                raise ValueError('automatic_budget_requires_normalized_pcm')
            remaining = frames
            while remaining:
                count = min(remaining, RATE * 60)
                if len(stream.readframes(count)) != count * 2:
                    raise ValueError('automatic_budget_incomplete_pcm')
                remaining -= count
        units = (frames + RATE * 60 - 1) // (RATE * 60)
    else:
        from .transcript_batches import MAX_BATCH_TRANSCRIPT_BYTES, split_transcript
        source = json.loads(store.read(owner, command['inputs']['transcript'], limit=MAX_BATCH_TRANSCRIPT_BYTES))
        units = sum(1 for _ in split_transcript(source, policy_version=policy_version))
    return {
        'max_model_calls': units * width,
        'model_call_plan': {
            'version': 1, 'mode': 'input_derived', 'planned_units': units,
            'candidate_count': width, 'inputs_sha256': digest(command['inputs']),
        },
    }


def frozen_cap(command):
    """Check frozen derivation arithmetic/binding without changing signed bytes."""
    role = command['agent']['id']
    config = command[KINDS[role]]
    cap = config.get('max_model_calls')
    plan = config.get('model_call_plan')
    if not automatic(command):
        if type(cap) is not int or cap < 1:
            raise ValueError('invalid_role_frozen_call_budget')
        return cap
    if (not isinstance(plan, dict) or set(plan) != {
            'version', 'mode', 'planned_units', 'candidate_count', 'inputs_sha256'}
            or type(plan['version']) is not int or plan['version'] != 1
            or plan['mode'] != 'input_derived'
            or type(plan['planned_units']) is not int
            or plan['planned_units'] < (1 if role == 'transcribe' else 0)
            or type(plan['candidate_count']) is not int
            or not 1 <= plan['candidate_count'] <= 4
            or plan['candidate_count'] != len(config['candidates'])
            or plan['inputs_sha256'] != digest(command['inputs'])
            or config.get('batch_policy') != POLICIES[role]
            or type(cap) is not int
            or cap != plan['planned_units'] * plan['candidate_count']):
        raise ValueError('automatic_call_budget_binding_changed')
    return cap


def verify(store, owner, command, *, policy_version):
    """Enrollment rechecks the deterministic plan; it never resolves old requests."""
    cap = frozen_cap(command)
    if automatic(command):
        expected = resolve(store, owner, command, policy_version=policy_version)
        config = command[KINDS[command['agent']['id']]]
        if any(config.get(key) != value for key, value in expected.items()):
            raise ValueError('automatic_call_budget_input_plan_changed')
    return cap


def preview(node):
    """Consent describes the rule, not a guessed cap before normalized input exists."""
    value = node['options'].get('max_model_calls')
    if value == 'auto' and node['type'] in KINDS:
        return {'budget_mode': 'input_derived', 'max_calls': None,
                'planned_units': None, 'candidate_count': 1 + len(node.get('fallback_refs', []))}
    return {'budget_mode': 'explicit', 'max_calls': int(value) if value is not None else None}
