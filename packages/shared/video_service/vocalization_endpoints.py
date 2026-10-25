"""Explicit bounded vocalization wire; no SQL admission, activation or quality claim."""

import json
import re

from .model_endpoints import EndpointFailure, GeminiTextAdapter


class GeminiVocalizationAdapter(GeminiTextAdapter):
    """Audio-event wire only. A registered, durable admission runner is still required."""

    def classify(self, model, context, clips, schema):
        import base64
        import hashlib
        import math

        from .audio_contract import audio_info
        from .vocalization_proposals import CONFIRM_SCHEMA, EVENT_SCHEMA, POLICY

        phase = context.get("phase")
        expected = EVENT_SCHEMA if phase == "detect" else CONFIRM_SCHEMA
        if (
            context.get("purpose") != "vocalization_regions_v1"
            or phase not in {"detect", "confirm"}
            or schema != expected
            or not isinstance(clips, list)
            or len(clips) != (1 if phase == "detect" else 2)
            or not re.fullmatch(r"gemini-[A-Za-z0-9._-]{1,190}", model)
            or not re.fullmatch(r"[a-f0-9]{64}", context.get("binding_sha256", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", context.get("source_sha256", ""))
            or type(context.get("source_frames")) is not int
            or not 0 < context["source_frames"] <= 300 * 16000
            or type(context.get("max_calls")) is not int
            or not 1 <= context["max_calls"] <= 128
            or type(context.get("call_index")) is not int
            or not 0 <= context["call_index"] < context["max_calls"]
            or not isinstance(context.get("instruction"), str)
            or not context["instruction"].startswith(POLICY)
            or len(context["instruction"]) > 16384
            or len(context.get("clips", [])) != len(clips)
        ):
            raise ValueError("invalid_vocalization_wire_context")
        parts = []
        durations = []
        if sum(len(raw) for raw in clips) > 2 * 1024 * 1024:
            raise ValueError("vocalization_audio_wire_budget")
        for raw, bound in zip(clips, context["clips"], strict=True):
            info = audio_info(raw)
            start, end = bound.get("start_frame"), bound.get("end_frame")
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= context["source_frames"]
                or end - start > 60 * 16000
                or abs(info["duration_seconds"] - (end - start) / 16000) > 1 / 16000
                or hashlib.sha256(raw).hexdigest() != bound.get("sha256")
            ):
                raise ValueError("vocalization_clip_binding_mismatch")
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "audio/wav",
                        "data": base64.b64encode(raw).decode("ascii"),
                    }
                }
            )
            durations.append((end - start) / 16000)
        value = self._request(
            "POST",
            "/models/" + model + ":generateContent",
            {
                "systemInstruction": {"parts": [{"text": context["instruction"]}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseSchema": schema,
                },
            },
        )
        try:
            result = json.loads(self.final_text(value))
            if phase == "detect":
                if not isinstance(result, list) or len(result) > 1024:
                    raise ValueError()
                for item in result:
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"start", "end", "kind", "certain"}
                        or any(
                            type(item[k]) not in (int, float)
                            or not math.isfinite(item[k])
                            for k in ["start", "end"]
                        )
                        or not 0 <= item["start"] < item["end"] <= durations[0]
                        or item["kind"]
                        not in {"speech", "breath", "grunt", "uncertain"}
                        or type(item["certain"]) is not bool
                    ):
                        raise ValueError()
            elif (
                not isinstance(result, dict)
                or set(result) != {"kind", "safe_to_remove", "speech_overlap"}
                or result["kind"] not in {"speech", "breath", "grunt", "uncertain"}
                or type(result["safe_to_remove"]) is not bool
                or type(result["speech_overlap"]) is not bool
            ):
                raise ValueError()
            return result
        except (TypeError, ValueError, KeyError):
            raise EndpointFailure("Invalid structured vocalization response") from None
