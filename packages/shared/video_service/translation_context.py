"""Opt-in reference data; absent historical requests never acquire context.

New nonempty goal descriptions compile to reference_v1 native options, then a
version1 translation_context on a role-policy-v2 task. The tool packet also has
translation_context_version=1: an old strict task reader OR old bridge must
reject before sending, rather than silently omit reference data. Activation is
explicit on the coordinated TranslationRuntime; model registration is unrelated.
"""


def description(value):
    if type(value) is not str or len(value) > 2000:
        raise ValueError("번역 참고 설명은 2000자 이내의 문자열이어야 합니다.")
    return value


def validate(value):
    if (type(value) is not dict or set(value) != {"version", "video_description"}
            or type(value["version"]) is not int or value["version"] != 1
            or not description(value["video_description"])):
        raise ValueError("invalid_translation_reference_context")
    return value


def from_options(options):
    text = description(options["video_description"]) if "video_description" in options else ""
    if "translation_context_profile" in options:
        if options["translation_context_profile"] != "reference_v1" or not text:
            raise ValueError("explicit_translation_reference_context_required")
        return {"version": 1, "video_description": text}
    if text:
        raise ValueError("explicit_translation_reference_context_required")
    return None
