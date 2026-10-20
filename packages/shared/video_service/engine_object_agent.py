"""Offline engine execution with S3 claim/result receipts, separate from CPU RPC."""

import json
from pathlib import Path
from .cpu_agents import canonical, digest
from .engine_protocol import envelope, validate_runtime
from .rabbitmq_transport import InvalidMessage
from .local_model_engines import transcribe, translate


class EngineObjectExecutor:
    def __init__(self, store, config):
        if not isinstance(config, dict) or "descriptor" not in config:
            raise ValueError("explicit_engine_locator_required")
        validate_runtime(config["descriptor"])
        expected = {"descriptor", "model_dir"} | (
            {"python"} if config["descriptor"]["role"] == "faceswap" else set()
        )
        if (
            set(config) != expected
            or not isinstance(config["model_dir"], str)
            or not Path(config["model_dir"]).is_absolute()
        ):
            raise ValueError("explicit_engine_locator_required")
        self.store, self.config = store, config

    def execute(self, owner, command):
        envelope(owner, command)
        if command["runtime"] != self.config["descriptor"]:
            raise InvalidMessage("engine_pin_does_not_match_deployment")
        previous = self.store.claim_attempt(owner, command)
        if previous is not None:
            envelope(owner, command, previous)
            for reference in previous["outputs"].values():
                self.store.path(owner, reference)
            return previous
        result = {
            key: command[key]
            for key in [
                "protocol_version",
                "run_id",
                "attempt_id",
                "generation",
                "agent",
            ]
        }
        result.update(request_sha256=digest(command), transport="s3_engine")
        try:
            outputs = self._run(owner, command)
            result.update(
                status="completed",
                outputs={
                    port: self.store.put(owner, [raw], kind)
                    for port, (raw, kind) in outputs.items()
                },
            )
        except Exception:
            result.update(
                status="failed",
                outputs={},
                error={"code": "offline_engine_execution_failed", "retryable": False},
            )
        envelope(owner, command, result)
        self.store.finish_attempt(owner, command, result)
        return result

    def _run(self, owner, command):
        runtime = command["runtime"]
        role = runtime["role"]
        model = Path(self.config["model_dir"])
        if runtime["family"] == "gpu":
            from mideagent_gpu.adapters import execute

            return execute(self.store, owner, command, self.config)
        if role == "transcribe":
            audio = self.store.path(owner, command["inputs"]["audio"])
            timeline = json.loads(self.store.read(owner, command["inputs"]["timeline"]))
            if isinstance(timeline, dict):
                if (
                    set(timeline)
                    != {"version", "audio_sha256", "source_sha256", "spans", "engine"}
                    or type(timeline["version"]) is not int
                    or timeline["version"] != 2
                    or timeline["audio_sha256"] != command["inputs"]["audio"]["sha256"]
                ):
                    raise ValueError("gpu_clock_audio_pin_differs")
                timeline = timeline["spans"]
            from .audio_clock import restore_clock, validate_clock
            import wave

            validate_clock(timeline)
            with wave.open(str(audio), "rb") as stream:
                duration = stream.getnframes() / stream.getframerate()
            if abs(timeline[-1]["packed_end"] - duration) > 1 / 16000:
                raise ValueError("audio_and_timeline_duration_differ")
            segments = transcribe(
                audio,
                model_dir=model,
                model_digest=runtime["model_sha256"],
                language=runtime["source_language"],
            )
            segments = restore_clock(segments, timeline)
            return {"transcript": (canonical(segments), "transcript")}
        if role == "translate":
            segments = json.loads(
                self.store.read(owner, command["inputs"]["transcript"])
            )
            translated = translate(
                segments,
                model_dir=model,
                model_digest=runtime["model_sha256"],
                source_tokenizer=model / "source.spm",
                target_tokenizer=model / "target.spm",
                source_language=runtime["source_language"],
                target_language=runtime["target_language"],
            )
            return {"transcript": (canonical(translated), "transcript")}
        raise ValueError("engine_role_not_implemented")
