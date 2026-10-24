"""Renewal port/options catalog; availability is explicit and not an executor."""

import re
from copy import deepcopy

from .agent_protocol import CPU_AGENTS


def node(
    identity,
    label,
    inputs,
    outputs,
    role="media",
    optional=(),
    choices=None,
    embedded=(),
):
    return {
        "id": identity,
        "label": label,
        "inputs": inputs,
        "outputs": outputs,
        "optional_inputs": list(optional),
        "worker_role": role,
        "options": choices or {},
        "embedded_operations": list(embedded),
        "execution": "cpu_subprocess" if identity in CPU_AGENTS else "unavailable",
        "entrypoint": "mideagent-" + identity.replace("_", "-")
        if identity in CPU_AGENTS
        else "",
    }


MODEL_CALL_LIMITS = [
    str(value) for value in (1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096)
]

NODES = [
    node("analyze", "영상 분석", {"video": "video"}, {"metadata": "media_metadata"}),
    node("extract_audio", "오디오 추출", {"video": "video"}, {"audio": "audio"}),
    node(
        "preprocess_audio",
        "음성 전처리",
        {"audio": "audio", "regions": "audio_regions"},
        {"audio": "audio", "timeline": "timeline_map"},
        optional=["regions"],
        choices={
            "audio_filter": ["off", "conservative", "strong", "silence3"],
            "processing_profile": [
                "legacy_v1",
                "silence_pack_v3",
                "regions_pack_v4",
                "nvidia_regions_v4",
            ],
            "vad_mode": ["off", "nvidia"],
        },
    ),
    node(
        "transcribe",
        "음성 전사",
        {"audio": "audio", "timeline": "timeline_map"},
        {"transcript": "transcript"},
        role="transcription",
        choices={
            "batch_policy": ["single", "bounded_60s_v1"],
            "max_model_calls": MODEL_CALL_LIMITS,
        },
        embedded=["filter_transcript", "restore_timeline"],
    ),
    node(
        "translate",
        "자막 번역",
        {"transcript": "transcript"},
        {"transcript": "transcript"},
        role="translation",
        choices={
            "batch_policy": ["single", "bounded_100x16k_v1"],
            "max_model_calls": MODEL_CALL_LIMITS,
        },
    ),
    node(
        "generate_subtitle",
        "자막 생성",
        {"transcript": "transcript"},
        {"subtitles": "subtitle"},
        choices={
            "format": ["srt", "srt_smi"],
            "language": [
                "und",
                "en",
                "ko",
                "ja",
                "zh",
                "de",
                "fr",
                "es",
                "it",
                "pt",
                "ru",
                "vi",
                "th",
                "id",
                "ar",
                "hi",
            ],
        },
    ),
    node(
        "encode",
        "영상 인코딩·번인",
        {"video": "video", "subtitles": "subtitle"},
        {"video": "video"},
        optional=["subtitles"],
        choices={
            "subtitle_mode": ["burn", "soft", "none"],
            "video_codec": ["h264", "hevc"],
            "resolution": ["original", "1080p", "720p"],
            "quality_profile": ["balanced", "high", "compact"],
        },
        embedded=["burn_subtitles"],
    ),
    node(
        "validate_video",
        "출력 영상 검증",
        {"video": "video"},
        {"report": "validation_report"},
    ),
    node(
        "faceswap",
        "얼굴 합성",
        {
            "video": "video",
            "session": "faceswap_session",
            "preview": "faceswap_preview",
        },
        {"video": "video"},
        role="faceswap",
        choices={
            "preset": ["fast", "balanced", "quality"],
            "video_codec": ["h264", "hevc"],
        },
    ),
]

from .decision_conditions import OPTIONS as DECISION_OPTIONS

VALUE_TYPES = [
    "video",
    "audio",
    "transcript",
    "subtitle",
    "timeline_map",
    "media_metadata",
    "validation_report",
    "artifact_manifest",
    "decision_result",
]
NODES.extend(
    [
        {
            **node(
                "decision",
                "AI 판단 · 조건 경로",
                {"value": "video"},
                {"a": "video", "b": "video", "result": "decision_result"},
                role="control",
                choices={"data_type": VALUE_TYPES, **DECISION_OPTIONS},
            ),
            "execution": "explicit_decision_ticket",
            "entrypoint": "controller-owned",
            "port_types_from_options": {
                "inputs": {"value": "data_type"},
                "outputs": {"a": "data_type", "b": "data_type"},
            },
        },
        {
            **node(
                "review",
                "사람 검수",
                {"value": "video"},
                {"value": "video"},
                role="control",
                choices={
                    "data_type": VALUE_TYPES,
                    "review_kind": ["approve_only", "audio_regions_v1"],
                },
            ),
            "execution": "explicit_review_ticket",
            "entrypoint": "controller-owned",
            "conditional_outputs": {
                "review_kind": {"audio_regions_v1": {"regions": "audio_regions"}}
            },
            "port_types_from_options": {
                "inputs": {"value": "data_type"},
                "outputs": {"value": "data_type"},
            },
        },
        {
            **node(
                "select",
                "수동 선택 분기",
                {"value": "video"},
                {"a": "video", "b": "video"},
                role="control",
                choices={"data_type": VALUE_TYPES, "selection": ["a", "b", "both"]},
            ),
            "execution": "explicit_graph_ticket",
            "entrypoint": "controller-owned",
            "port_types_from_options": {
                "inputs": {"value": "data_type"},
                "outputs": {"a": "data_type", "b": "data_type"},
            },
        },
        {
            **node(
                "join",
                "선택 결과 합류 목록",
                {"left": "video", "right": "video"},
                {"manifest": "artifact_manifest"},
                role="control",
                choices={"left_type": VALUE_TYPES, "right_type": VALUE_TYPES},
            ),
            "execution": "explicit_graph_ticket",
            "entrypoint": "controller-owned",
            "port_types_from_options": {
                "inputs": {"left": "left_type", "right": "right_type"}
            },
        },
    ]
)


def node_spec(identity, options=None):
    selected = next((n for n in NODES if n["id"] == identity), None)
    if selected is None:
        return None
    selected = deepcopy(selected)
    supplied = options if isinstance(options, dict) else {}
    if (
        identity == "preprocess_audio"
        and supplied.get("processing_profile") == "regions_pack_v4"
    ):
        selected["optional_inputs"].remove("regions")
    if identity == "generate_subtitle" and supplied.get("format") == "srt_smi":
        selected["outputs"]["sami"] = "subtitle"
    for direction, ports in selected.get("port_types_from_options", {}).items():
        for port, key in ports.items():
            value = supplied.get(key, selected["options"][key][0])
            if isinstance(value, str) and value in selected["options"][key]:
                selected[direction][port] = value
    for key, variants in selected.get("conditional_outputs", {}).items():
        selected["outputs"].update(variants.get(supplied.get(key), {}))
    return selected


def node_catalog():
    return {
        "version": 1,
        "nodes": deepcopy(NODES),
        "standalone_execution": False,
        "scope": "renewal 입출력·옵션 계약입니다. CPU 독립 프로세스와 controller 제어를 구분하며 GPU·모델 미연결 노드는 실행 불가입니다.",
        "notes": [
            "번인은 encode의 subtitle_mode=burn이며 독립 실행 단계가 아닙니다.",
            "전처리의 NVIDIA VAD·얼굴 합성은 해당 엔진과 모델 환경이 별도로 필요합니다.",
            "MQ CPU 역할은 독립 소비자입니다. GPU 엔진 소스 보존은 MQ 연결이나 GPU 검증 완료를 뜻하지 않습니다.",
        ],
    }


def validate_node(payload):
    if not isinstance(payload, dict) or set(payload) - {"node", "inputs", "options"}:
        raise ValueError("노드 검증 요청 형식을 확인하세요.")
    selected = node_spec(payload.get("node"), payload.get("options"))
    if selected is None:
        raise ValueError("현재 실행 경로가 없는 노드입니다.")
    inputs, options = payload.get("inputs"), payload.get("options", {})
    if not isinstance(inputs, dict) or not isinstance(options, dict):
        raise ValueError("입력 포트와 옵션은 객체여야 합니다.")  # noqa: TRY004 -- public validation contract
    if set(inputs) - set(selected["inputs"]):
        raise ValueError("지원하지 않는 입력 포트입니다.")
    required = set(selected["inputs"]) - set(selected["optional_inputs"])
    if required - set(inputs):
        raise ValueError("필수 입력 포트가 빠졌습니다.")
    if any(value != selected["inputs"][key] for key, value in inputs.items()):
        raise ValueError("입력 포트의 자료 유형이 맞지 않습니다.")
    if set(options) - set(selected["options"]):
        raise ValueError("이 노드가 지원하지 않는 옵션입니다.")
    if any(
        not isinstance(v, str)
        or (
            not re.fullmatch(r"[a-z]{2,3}", v)
            if selected["id"] == "generate_subtitle" and k == "language"
            else v not in selected["options"][k]
        )
        for k, v in options.items()
    ):
        raise ValueError("지원하지 않는 처리 옵션 조합입니다.")
    if selected["id"] == "preprocess_audio":
        nvidia_regions = options.get("processing_profile") == "nvidia_regions_v4"
        if nvidia_regions and options.get("vad_mode") != "nvidia":
            raise ValueError("nvidia_regions_v4 requires explicit NVIDIA engine")
        cpu_regions = options.get("processing_profile") == "regions_pack_v4"
        if cpu_regions and (
            options.get("vad_mode", "off") != "off" or "regions" not in inputs
        ):
            raise ValueError(
                "regions_pack_v4 requires CPU mode and a region decision input"
            )
        if "regions" in inputs and not (nvidia_regions or cpu_regions):
            raise ValueError(
                "audio regions require an explicit region processing contract"
            )
    if (
        selected["id"] == "preprocess_audio"
        and options.get("processing_profile") == "silence_pack_v3"
        and options.get("vad_mode", "off") != "off"
    ):
        raise ValueError(
            "silence_pack_v3 is a CPU-only profile; NVIDIA VAD needs its explicit engine contract"
        )
    if (
        selected["id"] == "review"
        and options.get("review_kind") == "audio_regions_v1"
        and options.get("data_type") != "audio"
    ):
        raise ValueError("audio region review requires audio input")
    if selected["id"] == "decision":
        from .decision_conditions import conditions

        conditions(options)
    if selected["id"] == "encode" and (
        options.get("subtitle_mode", "burn") != "none"
    ) != ("subtitles" in inputs):
        raise ValueError(
            "burn/soft에는 자막 입력이 필요하며 none에는 자막 입력을 연결하지 않습니다."
        )
    return {
        "valid": True,
        "scope": "port_types_and_options_only",
        "node": selected["id"],
        "outputs": dict(selected["outputs"]),
        "execution": selected["execution"],
        "notice": "입출력 유형·옵션만 검증했습니다. 파일 존재·소유권·시간축·엔진·과금·실행 성공은 별도 검증이 필요합니다.",
    }
