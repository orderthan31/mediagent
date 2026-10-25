"""Read-only host/resource observations from an explicitly mounted trusted collector."""

import json
import time
from pathlib import Path

from fastapi import Depends


def mount_system_resources(app, session_dependency):
    authenticated = Depends(session_dependency)

    @app.get("/api/system/resources")
    def resources(_actor=authenticated):
        path = Path("/run/host-status/resources.json")
        try:
            raw = path.read_bytes()
            if len(raw) > 65536:
                raise ValueError("observation size")
            value = json.loads(raw)
            age = time.time() - value["observed_unix"]
            if not 0 <= age <= 120:
                return {
                    "status": "stale",
                    "observed_at": value.get("observed_at"),
                    "nodes": [],
                    "storage": [],
                    "notice": "자원 수집 연결을 확인하세요.",
                }
            return {"status": "connected", "age_seconds": round(age, 1), **value}
        except (OSError, ValueError, KeyError, TypeError):
            return {
                "status": "unavailable",
                "nodes": [],
                "storage": [],
                "notice": "아직 자원 상태를 받지 못했습니다.",
            }
