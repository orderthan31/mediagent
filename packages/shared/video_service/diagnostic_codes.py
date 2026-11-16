"""Closed factual codes for private diagnostics; never serialize exception text."""
FAILURE_CODES = frozenset({
    'connection_failed', 'outcome_unknown', 'model_reply_unknown',
    'authentication_failed', 'request_rejected', 'rate_limited', 'upstream_failure',
    'invalid_response', 'invalid_timed_transcription', 'call_budget_below_required_chunks',
    'translation_output_capacity', 'interrupted_model_intent',
    'unavailable', 'output_capacity_exceeded',
    'tool_exception', 'delivery_held', 'delivery_exception', 'transport_exception',
    'tool_transport_timeout_outcome_unknown',
})


def safe_code(value):
    return value if type(value) is str and value in FAILURE_CODES else None


_TOOL_TRANSPORT_TIMEOUT = object()


def mark_tool_transport_timeout(error):
    """Producer HTTP-boundary evidence only; retain exception type and identity."""
    try:
        error._mideagent_tool_transport_timeout = _TOOL_TRANSPORT_TIMEOUT
    except BaseException:
        # Diagnostics must never replace the original transport exception.
        pass


def failure_code(error, fallback):
    # Explicit adapter evidence wins. Never infer from exception text, elapsed
    # time or a bare TimeoutError outside the marked producer HTTP boundary.
    code = safe_code(getattr(error, 'code', None))
    if code:
        return code
    if getattr(error, '_mideagent_tool_transport_timeout', None) is _TOOL_TRANSPORT_TIMEOUT:
        return 'tool_transport_timeout_outcome_unknown'
    return fallback


def event_level(state):
    return ('ERROR' if state in {'failed', 'error'} else
            'WARNING' if state in {'held', 'cancelled', 'unknown'} else 'INFO')
