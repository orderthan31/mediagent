"""Goal-owned task agents; entries bind existing role graphs, not single model calls."""
from copy import deepcopy

AGENTS = {
    'transcribe': {
        'id': 'transcribe', 'name': '전사 에이전트',
        'goal': '음성에서 시간 정보가 맞는 전사문을 완성합니다.',
        'role': 'transcription', 'entrypoint': 'mideagent_models.transcription:TranscriptionAgent.run',
        'allowed_tools': ['speech.prepare_audio', 'speech.transcribe', 'speech.validate_chunk', 'speech.merge_segments'],
        'model_driven_selection': False,
    },
    'translate': {
        'id': 'translate', 'name': '번역 에이전트',
        'goal': '원문 구간과 시간을 유지한 대상 언어 번역문을 완성합니다.',
        'role': 'translation', 'entrypoint': 'mideagent_models.translation:TranslationAgent.run',
        'allowed_tools': ['text.prepare_batches', 'text.translate', 'text.validate_batch', 'text.merge_batches'],
        'model_driven_selection': False,
    },
}
ALIASES = {'transcription': 'transcribe', 'translation': 'translate'}

def registration(identity):
    value = AGENTS.get(ALIASES.get(identity, identity))
    return deepcopy(value) if value else None
