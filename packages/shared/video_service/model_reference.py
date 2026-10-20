"""Pure immutable model reference validation; no filesystem or legacy registry."""

import re
from copy import deepcopy


def valid_reference(reference):
    if (
        not isinstance(reference, dict)
        or set(reference) != {"model_id", "revision"}
        or not isinstance(reference["model_id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", reference["model_id"])
        or type(reference["revision"]) is not int
        or reference["revision"] < 1
    ):
        raise ValueError("model_id와 정확한 정수 revision을 고정하세요.")
    return deepcopy(reference)
