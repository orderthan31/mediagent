"""Pure decision-result validation; no legacy workflow or external execution."""

import math
from copy import deepcopy


class DecisionFormatError(ValueError):
    pass


def structured_result(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "label", "confidence", "reason"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["label"], str)
        or value["label"] not in {"pass", "review", "reject"}
        or type(value["confidence"]) not in (int, float)
        or not math.isfinite(value["confidence"])
        or not 0 <= value["confidence"] <= 1
        or not isinstance(value["reason"], str)
        or not 1 <= len(value["reason"].strip()) <= 2000
    ):
        raise DecisionFormatError(
            "판단은 version1/label(pass·review·reject)/유한 confidence0~1/reason만 허용합니다."
        )
    return deepcopy(value)
