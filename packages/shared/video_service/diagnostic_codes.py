"""Closed factual codes for private diagnostics; never serialize exception text."""
FAILURE_CODES = frozenset({
    'connection_failed', 'outcome_unknown', 'model_reply_unknown',
    'authentication_failed', 'request_rejected', 'rate_limited', 'upstream_failure',
    'invalid_response', 'invalid_timed_transcription', 'call_budget_below_required_chunks',
    'translation_output_capacity', 'interrupted_model_intent',
    'unavailable', 'output_capacity_exceeded',
    'tool_exception', 'delivery_held', 'delivery_exception', 'transport_exception',
})


def safe_code(value):
    return value if type(value) is str and value in FAILURE_CODES else None


def failure_code(error, fallback):
    # Only the adapter's explicit sanitized code is evidence, not str(error).
    return safe_code(getattr(error, 'code', None)) or fallback


def event_level(state):
    return ('ERROR' if state in {'failed', 'error'} else
            'WARNING' if state in {'held', 'cancelled', 'unknown'} else 'INFO')
