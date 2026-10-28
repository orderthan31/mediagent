"""Refresh storage authority at each I/O boundary, including after a long model run."""

import threading
from datetime import UTC, datetime

from video_service.cpu_agents import digest
from video_service.object_store import from_config

from .protocol import require


class TaskLeasedStore:
    def __init__(self, config, tool):
        self.config, self.tool, self.local = config, tool, threading.local()

    def bind_delivery(self, packet, kind):
        self.local.grant = {
            "task_id": packet["task_id"]
            if kind == "cancel_ack"
            else packet["task"]["task_id"],
            "request_sha256": packet["request_sha256"]
            if kind == "cancel_ack"
            else digest(packet),
            "kind": kind,
        }

    def _invoke(self, method, *args, **kwargs):
        request = getattr(self.local, "grant", None)
        require(request is not None, "storage_delivery_context_required")
        lease = self.tool.storage_lease(request)
        require(
            lease.get("version") == 1
            and lease.get("task_id") == request["task_id"]
            and lease.get("request_sha256") == request["request_sha256"],
            "storage_lease_scope_changed",
        )
        expiry = datetime.fromisoformat(lease["expires_at"])
        require(
            expiry.tzinfo is not None
            and (expiry - datetime.now(UTC)).total_seconds() > 30,
            "storage_lease_expired",
        )
        credentials = lease["credentials"]
        values = {
            self.config[k]: credentials[v]
            for k, v in [
                ("access_key_env", "access_key_id"),
                ("secret_key_env", "secret_access_key"),
                ("session_token_env", "session_token"),
            ]
        }
        store = from_config(self.config, environ=values)
        try:
            return getattr(store, method)(*args, **kwargs)
        finally:
            store.client.close()

    def path(self, *args, **kwargs):
        return self._invoke("path", *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._invoke("put", *args, **kwargs)

    def read(self, *args, **kwargs):
        return self._invoke("read", *args, **kwargs)
