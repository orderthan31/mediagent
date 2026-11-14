"""One newly approved model call on the existing private role bridge.

Only a persisted attempt identity is accepted. Inputs/model/key selection come
from the frozen recovery grant, never from the HTTP caller or old call slots.
"""
import re

from video_service.canonical import canonical
from video_service.postgres import Conflict
from video_service.role_policy import model_binding, endpoint_error_code
from mideagent_model_tools.endpoints import EndpointFailure


class UnitRecoveryToolBridge:
    def __init__(self, runtime, role, *, service=None):
        if role not in {"transcription", "translation"}:
            raise ValueError("unsupported_unit_recovery_role")
        self.runtime = runtime
        self.role = role
        if service is None:
            from video_service.postgres.unit_recovery import RoleUnitRecovery
            service = RoleUnitRecovery(runtime)
        self.service = service

    def _verified_input(self, grant):
        task, pin = grant["task"], grant["pin"]
        candidate = grant["candidate_index"]
        if (
            grant["role"] != self.role or task["role"] != self.role
            or type(candidate) is not int or not 0 <= candidate < len(task["models"])
            or canonical(model_binding(pin)) != canonical(task["models"][candidate])
        ):
            raise Conflict("unit_retry_frozen_model_or_role_changed")
        if self.role == "transcription":
            from video_service.role_receipts import speech_chunks
            chunks = speech_chunks(task, grant["source"])
            selected = next((v for v in chunks if v.chunk_index == grant["unit_index"]), None)
        else:
            from video_service.transcript_batches import split_transcript
            selected = next((v for v in split_transcript(grant["source"], policy_version=2)
                             if v.chunk_index == grant["unit_index"]), None)
        if selected is None or selected.sha256 != grant["input_sha256"]:
            raise Conflict("unit_retry_input_outside_grant")
        return selected

    @staticmethod
    def _view(attempt_id, status, error_code=None):
        value = {"attempt_id": attempt_id, "status": status}
        if error_code:
            value["error_code"] = error_code
        return value

    def invoke(self, packet):
        if (type(packet) is not dict or set(packet) != {"attempt_id", "context_sha256"}
                or type(packet["attempt_id"]) is not str
                or not re.fullmatch("[a-f0-9]{32}", packet["attempt_id"])
                or type(packet["context_sha256"]) is not str
                or not re.fullmatch("[a-f0-9]{64}", packet["context_sha256"])):
            raise ValueError("invalid_unit_retry_capability")
        attempt_id, context = packet["attempt_id"], packet["context_sha256"]
        grant = self.service.load_retry_attempt(attempt_id, context)
        selected = self._verified_input(grant)
        from video_service.postgres.model_call_fence import model_call_fence

        adapter = None
        entered = False
        with model_call_fence(self.runtime.database, grant["owner_id"], grant["job_id"]):
            # A separately committed one-way intent is the only call authority.
            # Sending/unknown/settled attempts never enter an adapter again.
            intent = self.service.begin_attempt(attempt_id, context)
            if not intent["newly_sending"]:
                return self._view(attempt_id, intent["status"])
            try:
                executor = getattr(self.runtime, self.role + "_runtime")
                pin, task = grant["pin"], grant["task"]
                if executor is None or not executor.available(pin):
                    raise EndpointFailure("frozen unit model unavailable", code="unavailable")
                key = (executor.credentials.resolve(pin["owner_id"], pin["connection_id"], pin["credential_ref"])
                       if pin.get("credential_ref") else None)
                adapter = executor.make_adapter(pin, key)
                if self.role == "transcription":
                    from video_service.audio_contract import timed_segments
                    entered = True
                    received = adapter.transcribe(pin["remote_model"], selected.audio, task["source_language"])
                    try:
                        response = timed_segments(received, selected.end - selected.start)
                    except (ValueError, TypeError, KeyError):
                        raise EndpointFailure("invalid unit transcription", code="invalid_response") from None
                else:
                    from video_service.postgres.translation import translation_messages
                    from video_service.translation_output import decode_output, OutputCapacityError
                    plain = [{k: v for k, v in row.items() if k != "id"} for row in selected.segments]
                    messages = translation_messages(plain, task["source_language"], task["target_language"],
                        **({"translation_context": task["translation_context"]} if "translation_context" in task else {}))
                    entered = True
                    response = adapter.chat(pin["remote_model"], messages)
                    try:
                        decode_output(response, selected.segments)
                    except OutputCapacityError:
                        raise EndpointFailure("unit translation output capacity", code="invalid_response", capacity_exceeded=True) from None
                    except (ValueError, TypeError, KeyError, RecursionError):
                        raise EndpointFailure("invalid unit translation", code="invalid_response") from None
                self.service.finish_attempt(attempt_id, "completed", response=response)
                return self._view(attempt_id, "completed")
            except Exception as error:
                if isinstance(error, EndpointFailure):
                    code = endpoint_error_code(error, v2=True)
                    known_codes = {"rate_limited", "upstream_failure", "invalid_response", "unavailable",
                                   "authentication_failed", "request_rejected", "output_capacity_exceeded"}
                    known = code in known_codes
                    if not known:
                        code = "outcome_unknown"
                else:
                    known = not entered
                    code = "unavailable" if known else "outcome_unknown"
                status = "failed" if known else "unknown"
                # If response commit was ambiguous, the terminal-row guard must
                # preserve an already committed completed outcome rather than
                # overwrite it. No exception path sends a second model request.
                self.service.finish_attempt(attempt_id, status, error_code=code)
                return self._view(attempt_id, status, code)
            finally:
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception:
                        # The committed reply remains authoritative. Do not let
                        # cleanup obscure it or manufacture a retry permission.
                        pass
