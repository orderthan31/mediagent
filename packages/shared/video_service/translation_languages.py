"""Pure language validation shared by role admission and the registered runtime."""

import re


def languages(source, target):
    if (
        not isinstance(source, str)
        or not isinstance(target, str)
        or not (
            re.fullmatch(r"auto|[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})?", source)
            or len(source) <= 64
            and re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", source)
        )
        or not (
            re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})?", target)
            or len(target) <= 64
            and re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", target)
        )
    ):
        raise ValueError("번역 원문/대상 언어를 선택하세요.")
