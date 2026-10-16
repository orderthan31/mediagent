"""Strict structured judgment adapter contract. No route policy or live provider.

Only an explicitly injected provider may run. Reports preserve inputs and the
adapter identity, never provider diagnostics/keys or executable instructions.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from .storage import write_json_atomic

LIMIT = 1024 * 1024
TYPES = {'video', 'audio', 'media_metadata', 'timeline_map', 'validation_report', 'artifact_manifest', 'transcript', 'subtitle', 'decision_result'}


class DecisionFormatError(ValueError):
    pass


class DecisionInputError(ValueError):
    pass


def descriptor(provider):
    value = deepcopy(getattr(provider, 'descriptor', None))
    if (not isinstance(value, dict) or set(value) != {'id', 'revision', 'schema_version', 'paid'}
            or not isinstance(value['id'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', value['id'])
            or not isinstance(value['revision'], str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', value['revision'])
            or type(value['schema_version']) is not int or value['schema_version'] != 1 or type(value['paid']) is not bool):
        raise DecisionFormatError('판단 adapter의 비밀 아닌 ID/revision/schema/비용 설명이 필요합니다.')
    return value


def structured_result(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'label', 'confidence', 'reason'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['label'], str) or value['label'] not in {'pass', 'review', 'reject'}
            or type(value['confidence']) not in (int, float) or not math.isfinite(value['confidence'])
            or not 0 <= value['confidence'] <= 1
            or not isinstance(value['reason'], str) or not 1 <= len(value['reason'].strip()) <= 2000):
        raise DecisionFormatError('판단은 version1/label(pass·review·reject)/유한 confidence0~1/reason만 허용합니다.')
    return deepcopy(value)


def invoke_decision(provider, metadata, source, work):
    directory = Path(work)
    output = directory / 'decision.json'
    if output.exists():
        raise DecisionInputError('기존 판단 결과를 덮어쓰거나 재판정하지 않습니다.')
    profile = descriptor(provider)
    if not isinstance(metadata, dict) or metadata.get('type') not in TYPES:
        raise DecisionInputError('지원하는 소유 자료 metadata가 필요합니다.')
    source = Path(source)
    if not source.is_file() or source.stat().st_size != metadata.get('bytes'):
        raise DecisionInputError('판단 입력 파일/크기가 변경되었습니다.')
    with source.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if sha != metadata.get('sha256'):
        raise DecisionInputError('판단 입력 SHA가 변경되었습니다.')
    content = None
    if metadata['type'] not in {'video', 'audio'}:
        if source.stat().st_size > LIMIT:
            raise DecisionInputError('구조화/텍스트 판단 입력은 1MiB 이하만 지원합니다.')
        try:
            raw = source.read_text(encoding='utf-8')
            content = raw if metadata['type'] == 'subtitle' else json.loads(raw)
            json.dumps(content, allow_nan=False)
        except (ValueError, UnicodeError):
            raise DecisionInputError('판단 입력의 지원 JSON/UTF-8 형식을 확인하세요.') from None
    before = deepcopy(metadata)
    context = {'input': deepcopy(before), 'content': content, 'media_access': 'metadata_only' if content is None else 'bounded_readonly_content'}
    def perform():
        value = provider.decide(context)
        judgment = structured_result(value)
        if descriptor(provider) != profile:
            raise DecisionFormatError('판단 중 adapter ID/revision이 변경되었습니다.')
        with source.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != sha:
                raise DecisionInputError('판단 중 입력 내용이 변경되었습니다.')
        return judgment
    if profile['paid']:
        from .execution_authorization import external_call
        judgment=external_call(getattr(provider,'provider','adapter:'+profile['id']),getattr(provider,'model',profile['revision']),context,perform)
    else:judgment=perform()
    report = {'version': 1, 'kind': 'decision_result', 'input': before, 'adapter': profile, 'judgment': judgment}
    directory = Path(work)
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / 'decision.json'
    if output.exists():
        raise DecisionInputError('기존 판단 결과를 덮어쓰거나 재판정하지 않습니다.')
    write_json_atomic(output, report)
    return report
