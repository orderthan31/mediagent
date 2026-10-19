"""Isolate mutable native executor context per concurrent node invocation.

No operating factory is registered here. Only an explicitly supplied admitted
plan and source may be used; existing sequential execution remains unchanged.
"""
from copy import deepcopy
from pathlib import Path
from .sequential_nodes import MediaNodeExecutor


class ParallelMediaExecutor:
    def __init__(self, preferences, options, source, plan, *, provider_factory=None, paid_allowed=False):
        if not plan.get('supported'):
            raise ValueError('지원되는 병렬 실행 계획이 필요합니다.')
        self._steps = {step['id']: deepcopy(step) for step in plan['steps']}
        self._preferences = deepcopy(preferences)
        self._options = deepcopy(options)
        self._source = Path(source).resolve()
        self._provider_factory = provider_factory
        self._paid_allowed = paid_allowed

    def __call__(self, step, inputs, work, check):
        selected = self._steps.get(step['id'])
        if selected is None or selected != step or set(inputs) != set(selected['bindings']):
            raise ValueError('확인된 노드/포트/옵션과 다릅니다.')
        provider = self._provider_factory() if self._provider_factory else None
        local = MediaNodeExecutor(deepcopy(self._preferences), deepcopy(self._options),
                                  provider=provider, paid_allowed=self._paid_allowed)
        local.source = self._source
        def producer(port):
            binding = selected.get('native_bindings', selected['bindings'])[port]
            return self._steps[binding['node']]
        if step['type'] == 'transcribe':
            local.audio_filter = producer('audio')['options']['audio_filter']
        if step['type'] == 'generate_subtitle' and producer('transcript')['type'] == 'translate':
            local.language = self._options.get('target_language', 'ko')
        if step['type'] == 'validate_video':
            local.encode_options = deepcopy(producer('video')['options'])
        return local(step, inputs, work, check)
