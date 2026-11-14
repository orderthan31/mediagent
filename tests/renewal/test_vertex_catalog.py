import sys
from pathlib import Path
import httpx
import pytest
ROOT = Path(__file__).resolve().parents[2]
for p in ('packages/shared', 'tools/models'):
    sys.path.insert(0, str(ROOT / p))


def test_publisher_pages_preserve_exact_id(monkeypatch):
    from video_service import model_catalog as m
    from mideagent_model_tools import vertex_auth
    monkeypatch.setattr(vertex_auth, 'acquire_token', lambda *a, **kw: 'fake')
    seen=[]
    def send(r):
        seen.append(r)
        assert r.url.path == '/v1beta1/publishers/google/models'
        assert r.url.params['pageSize'] == '100'
        assert r.url.params['listAllVersions'] == 'true'
        assert r.headers['authorization'] == 'Bearer fake'
        return httpx.Response(200, json={'publisherModels':[{'name':'publishers/google/models/exact-id', 'versionId':'999', 'url':'https://evil.invalid'}], **({'nextPageToken':'page2'} if len(seen)==1 else {})})
    result=m.fetch_catalog('vertex_ai','fake-json',transport=httpx.MockTransport(send), approved_origins={'https://aiplatform.googleapis.com','https://oauth2.googleapis.com'})
    assert len(seen)==2 and [r['id'] for r in result]==['exact-id']
    assert result[0]['profile'] is None


def test_vertex_catalog_unapproved_never_sends():
    from video_service.model_catalog import fetch_catalog, CatalogFailure
    with pytest.raises(CatalogFailure):
        fetch_catalog('vertex_ai','fake',transport=httpx.MockTransport(lambda r: pytest.fail('wire')))


def test_repeated_page_token_is_not_partial_success(monkeypatch):
    from video_service.model_catalog import fetch_catalog, CatalogFailure
    from mideagent_model_tools import vertex_auth
    monkeypatch.setattr(vertex_auth,'acquire_token',lambda *a,**kw:'fake')
    seen=[]
    def send(r):
        seen.append(r)
        return httpx.Response(200,json={'publisherModels':[],'nextPageToken':'repeat'})
    with pytest.raises(CatalogFailure,match='pagination'):
        fetch_catalog('vertex_ai','fake-json',transport=httpx.MockTransport(send),approved_origins={'https://aiplatform.googleapis.com','https://oauth2.googleapis.com'})
    assert len(seen)==2


def test_sdk_vertex_namespace_and_declared_audio_modalities(monkeypatch):
    from mideagent_model_tools import sdk_metadata as m
    monkeypatch.setattr(m,'capability_map',lambda:{'selected':{'litellm_provider':'vertex_ai-language-models','mode':'chat','supports_response_schema':True,'supported_modalities':['text','audio']},'image':{'litellm_provider':'vertex_ai-language-models','mode':'image_generation'}})
    assert 'transcription' in m.sdk_profile('vertex_ai','selected')['profile_variants']
    assert m.sdk_profile('vertex_ai','image') is None
    assert m.sdk_profile('gemini','selected') is None
