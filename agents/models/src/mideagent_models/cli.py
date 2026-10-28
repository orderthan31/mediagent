"""Role-only process entrypoint. Configuration contains no workflow or global DB."""

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from .state import RoleState
from .transcription import TranscriptionAgent


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ScopedSpeechTool:
    """One configured HTTP tool capability, not an Execution/accept proxy."""

    def __init__(self, config):
        self.contract = config.get("tool_contract", "controlled_v1")
        if self.contract not in {
            "controlled_v1",
            "registry_scoped_v1",
            "registry_translation_v1",
            "registry_vocalization_v1",
        }:
            raise ValueError("unsupported_scoped_tool_contract")
        self.url = config["tool_url"]
        url = urllib.parse.urlsplit(self.url)
        controlled = (
            config.get("allow_controlled_loopback") is True
            and url.scheme == "http"
            and url.hostname in {"127.0.0.1", "localhost", "::1"}
        )
        if not controlled and url.scheme != "https":
            raise ValueError("verified_tls_tool_required")
        if url.username or url.password or url.fragment:
            raise ValueError("invalid_scoped_tool_url")
        self.timeout = config["timeout_seconds"]
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("finite_tool_timeout_required")
        self.token = os.environ[config["credential_env"]]
        self.maximum = config.get("max_reply_bytes", 16 * 1024 * 1024)
        context = ssl.create_default_context(cafile=config.get("ca_file"))
        self.client = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def for_chunk(self, task, chunk):
        if self.contract != "registry_scoped_v1":
            return self
        return lambda model, audio, language: self._request(
            model,
            audio,
            language,
            {"task_id": task["task_id"], "chunk_index": chunk["index"]},
        )

    def __call__(self, model, audio, language):
        if self.contract == "registry_scoped_v1":
            raise ValueError("scoped_task_chunk_required")
        return self._request(model, audio, language, {})

    def _request(self, model, audio, language, context):
        payload = {
            **context,
            "model": model,
            "source_language": language,
            "audio_base64": base64.b64encode(audio).decode("ascii"),
        }
        return self._post(payload)

    def storage_lease(self, payload):
        return self._post(payload, suffix="/storage-lease")

    def _post(self, payload, *, suffix=""):
        request = urllib.request.Request(
            self.url + suffix,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.token,
            },
            method="POST",
        )
        with self.client.open(request, timeout=self.timeout) as response:
            raw = response.read(self.maximum + 1)
        if len(raw) > self.maximum:
            raise ValueError("tool_response_exceeds_declared_budget")
        return json.loads(raw)


def translation_packet(task, batch, candidate):
    return {
        "task_id": task["task_id"],
        "batch_index": batch.chunk_index,
        "candidate_index": candidate,
        "model": task["models"][candidate],
        "input_sha256": batch.sha256,
    }


class ScopedTranslationTool(ScopedSpeechTool):
    def __call__(self, task, batch, candidate):
        if self.contract != "registry_translation_v1":
            raise ValueError("scoped_translation_contract_required")
        return self._post(translation_packet(task, batch, candidate))


def vocal_packet(task, request, candidate):
    return {
        "task_id": task["task_id"],
        "call_index": request["context"]["call_index"],
        "candidate_index": candidate,
        "model": task["models"][candidate],
        "input_sha256": request["input_sha256"],
    }


class ScopedVocalTool(ScopedSpeechTool):
    def __call__(self, task, request, candidate):
        if self.contract != "registry_vocalization_v1":
            raise ValueError("scoped_vocal_contract_required")
        return self._post(vocal_packet(task, request, candidate))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--audio")
    parser.add_argument("--cancel-task")
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text())
        if config["role"] != "transcription":
            raise ValueError("wrong_role_entrypoint")
        if args.cancel_task:
            import re

            if not re.fullmatch("[a-f0-9]{32}", args.cancel_task):
                raise ValueError("invalid_task_identity")
            actual = RoleState(config["state_root"]).cancel(args.cancel_task)
            print(
                json.dumps(
                    {
                        "task_id": args.cancel_task,
                        "role": "transcription",
                        "status": actual["status"],
                    }
                )
            )
            return
        if not args.audio:
            raise ValueError("verified_audio_path_required")
        task = json.load(sys.stdin)
        agent = TranscriptionAgent(
            config["state_root"],
            ScopedSpeechTool(config),
            chunk_concurrency=config.get("chunk_concurrency", 1),
        )
        result = agent.run(task, args.audio)
        print(json.dumps({**result, "agent_pid": os.getpid()}, ensure_ascii=False))
    except (ValueError, KeyError, OSError):
        print(
            json.dumps(
                {"status": "rejected", "error": "invalid_role_request_or_configuration"}
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
