from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[2] / 'packages/shared'))
from video_service import editor_contracts as m
v={'nodes':[{'type':'extract_audio','options':{}},{'type':'transcribe','options':{'source_language':'en'}},{'type':'translate','options':{'target_language':'ko'}}]}
r=m.resolve_editor_contracts(v)
assert r['nodes'][1]['options']['clock_policy']=='packed_projection_v5'
assert r['nodes'][1]['options']['max_model_calls']=='auto'
assert r['nodes'][2]['options']['translation_profile']=='language_target_v1'
assert v['nodes'][0]['options']=={}
old={'nodes':[{'type':'transcribe','options':{'batch_policy':'single','clock_policy':'legacy_envelope_v1','max_model_calls':'4'}}]}
assert m.resolve_editor_contracts(old)==old
print('new internal defaults derived; old explicit contracts preserved')
