"""Pinned maintained synchronous Vertex driver; no SDK credential cache or ADC."""
from copy import deepcopy
from types import SimpleNamespace


def completion(sdk, args, *, messages, response_format, stream=False):
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import VertexLLM, VertexGeminiConfig
    from litellm.llms.vertex_ai.gemini.transformation import get_supports_response_schema
    if stream:
        raise ValueError("Vertex streaming is unsupported")
    model, project, location, token = (args[k] for k in ('model', 'vertex_project', 'vertex_location', 'api_key'))
    params = {k: deepcopy(args[k]) for k in ('temperature', 'top_p', 'max_tokens', 'seed', 'reasoning_effort') if k in args}
    params['response_format'] = response_format
    optional = VertexGeminiConfig().map_openai_params(params, {}, model, drop_params=False)
    if 'response_schema' in optional and get_supports_response_schema(model=model, custom_llm_provider='vertex_ai') is False:
        raise ValueError("Vertex native response schema unsupported")

    class OwnedVertex(VertexLLM):
        def _ensure_access_token(self, **kwargs):
            return token, project

        @staticmethod
        def get_vertex_region(vertex_region, model):
            return vertex_region

    log = SimpleNamespace(pre_call=lambda **kw: None, post_call=lambda **kw: None, optional_params={})
    return OwnedVertex().completion(model=model, messages=deepcopy(messages), model_response=sdk.ModelResponse(),
        print_verbose=lambda *a, **kw: None, custom_llm_provider='vertex_ai', encoding=sdk.encoding,
        logging_obj=log, optional_params=optional, acompletion=False, timeout=args['timeout'],
        vertex_project=project, vertex_location=location, vertex_credentials=None, gemini_api_key=None,
        litellm_params={}, client=args['client'], api_base=None)
