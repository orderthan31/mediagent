"""Definitions shared only by isolated WF-05 tests/ASGI browser bridge."""
def review_graph():
    nodes = [
        ('extract', 'extract_audio', {}),
        ('prepare', 'preprocess_audio', {'audio_filter': 'off', 'vad_mode': 'off'}),
        ('stt', 'transcribe', {}),
        ('review_text', 'review', {'data_type': 'transcript'}),
        ('subtitle', 'generate_subtitle', {}),
        ('review_srt', 'review', {'data_type': 'subtitle'}),
        ('encode', 'encode', {'subtitle_mode': 'burn'}),
        ('independent', 'analyze', {}),
        ('review_metadata', 'review', {'data_type': 'media_metadata'}),
        ('joined', 'join', {'left_type': 'video', 'right_type': 'media_metadata'}),
    ]
    links = [('$input', 'video', 'extract', 'video'), ('extract', 'audio', 'prepare', 'audio'),
             ('prepare', 'audio', 'stt', 'audio'), ('prepare', 'timeline', 'stt', 'timeline'),
             ('stt', 'transcript', 'review_text', 'value'), ('review_text', 'value', 'subtitle', 'transcript'),
             ('subtitle', 'subtitles', 'review_srt', 'value'), ('$input', 'video', 'encode', 'video'),
             ('review_srt', 'value', 'encode', 'subtitles'), ('$input', 'video', 'independent', 'video'),
             ('independent', 'metadata', 'review_metadata', 'value'), ('encode', 'video', 'joined', 'left'),
             ('review_metadata', 'value', 'joined', 'right')]
    return {'catalog_version': 1, 'revision': 1, 'name': '격리 사람 검수·명시 이어실행', 'inputs': {'video': 'video'},
            'nodes': [{'id': identity, 'type': kind, 'options': options, 'position': {'x': (i % 4)*250, 'y': (i//4)*180}} for i, (identity, kind, options) in enumerate(nodes)],
            'edges': [{'id': 'e' + str(i), 'source': {'node': a, 'port': ap}, 'target': {'node': b, 'port': bp}} for i, (a, ap, b, bp) in enumerate(links)]}
