"""Typed contracts for existing Worker stages, not a second DAG executor."""
from copy import deepcopy


def node(identity, label, inputs, outputs, role='media', optional=(), choices=None, embedded=()):
    return {'id': identity, 'label': label, 'inputs': inputs, 'outputs': outputs,
            'optional_inputs': list(optional), 'worker_role': role, 'options': choices or {},
            'embedded_operations': list(embedded), 'execution': 'existing_fixed_workflow',
            'entrypoint': 'media_worker.faceswap.runner:execute' if identity == 'faceswap' else 'media_worker.worker:Worker.process'}


NODES = [
    node('analyze', '영상 분석', {'video': 'video'}, {'metadata': 'media_metadata'}),
    node('extract_audio', '오디오 추출', {'video': 'video'}, {'audio': 'audio'}),
    node('preprocess_audio', '음성 전처리', {'audio': 'audio'}, {'audio': 'audio', 'timeline': 'timeline_map'},
         choices={'audio_filter': ['off', 'conservative', 'strong', 'silence3'], 'vad_mode': ['off', 'nvidia']}),
    node('transcribe', '음성 전사', {'audio': 'audio', 'timeline': 'timeline_map'}, {'transcript': 'transcript'},
         role='transcription', embedded=['filter_transcript', 'restore_timeline']),
    node('translate', '자막 번역', {'transcript': 'transcript'}, {'transcript': 'transcript'}, role='translation'),
    node('generate_subtitle', '자막 생성', {'transcript': 'transcript'}, {'subtitles': 'subtitle'}),
    node('encode', '영상 인코딩·번인', {'video': 'video', 'subtitles': 'subtitle'}, {'video': 'video'},
         optional=['subtitles'], choices={'subtitle_mode': ['burn', 'soft', 'none'], 'video_codec': ['h264', 'hevc'],
         'resolution': ['original', '1080p', '720p'], 'quality_profile': ['balanced', 'high', 'compact']}, embedded=['burn_subtitles']),
    node('validate_video', '출력 영상 검증', {'video': 'video'}, {'report': 'validation_report'}),
    node('faceswap', '얼굴 합성', {'video': 'video', 'session': 'faceswap_session', 'preview': 'faceswap_preview'}, {'video': 'video'},
         role='faceswap', choices={'preset': ['fast', 'balanced', 'quality'], 'video_codec': ['h264', 'hevc']}),
]


def node_catalog():
    return {'version': 1, 'nodes': deepcopy(NODES), 'standalone_execution': False,
            'scope': '현재 고정 workflow 및 얼굴 합성 실행기의 처리 단계입니다. 개별 노드 실행 API·캔버스·DAG 엔진은 아직 없습니다.',
            'notes': ['번인은 encode의 subtitle_mode=burn이며 독립 실행 단계가 아닙니다.',
                      '전처리의 NVIDIA VAD·얼굴 합성은 해당 엔진과 모델 환경이 별도로 필요합니다.',
                      '서빙 역할은 단일 media_worker의 논리 역할이며 분산 Worker 등록부가 아닙니다.']}


def validate_node(payload):
    if not isinstance(payload, dict) or set(payload) - {'node', 'inputs', 'options'}:
        raise ValueError('노드 검증 요청 형식을 확인하세요.')
    selected = next((n for n in NODES if n['id'] == payload.get('node')), None)
    if selected is None:
        raise ValueError('현재 실행 경로가 없는 노드입니다.')
    inputs, options = payload.get('inputs'), payload.get('options', {})
    if not isinstance(inputs, dict) or not isinstance(options, dict):
        raise ValueError('입력 포트와 옵션은 객체여야 합니다.')
    if set(inputs) - set(selected['inputs']):
        raise ValueError('지원하지 않는 입력 포트입니다.')
    required = set(selected['inputs']) - set(selected['optional_inputs'])
    if required - set(inputs):
        raise ValueError('필수 입력 포트가 빠졌습니다.')
    if any(value != selected['inputs'][key] for key, value in inputs.items()):
        raise ValueError('입력 포트의 자료 유형이 맞지 않습니다.')
    if set(options) - set(selected['options']):
        raise ValueError('이 노드가 지원하지 않는 옵션입니다.')
    if any(not isinstance(v, str) or v not in selected['options'][k] for k, v in options.items()):
        raise ValueError('지원하지 않는 처리 옵션 조합입니다.')
    if selected['id'] == 'encode' and (options.get('subtitle_mode', 'burn') != 'none') != ('subtitles' in inputs):
        raise ValueError('burn/soft에는 자막 입력이 필요하며 none에는 자막 입력을 연결하지 않습니다.')
    return {'valid': True, 'scope': 'port_types_and_options_only', 'node': selected['id'],
            'outputs': dict(selected['outputs']), 'execution': selected['execution'],
            'notice': '입출력 유형·옵션만 검증했습니다. 파일 존재·소유권·시간축·엔진·과금·실행 성공은 별도 검증이 필요합니다.'}
