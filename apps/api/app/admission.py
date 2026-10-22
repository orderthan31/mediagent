"""Explicit startup admission policy. No configuration discovery or transitions."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AdmissionPolicy:
    mode: str = "normal"
    agent_id: str | None = None
    slot_id: str | None = None
    handover: bool = False

    def __post_init__(self):
        if self.mode == "normal":
            if (
                self.agent_id is not None
                or self.slot_id is not None
                or self.handover is not False
            ):
                raise ValueError("invalid_admission_policy")
        elif self.mode == "maintenance":
            if (
                not isinstance(self.agent_id, str)
                or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", self.agent_id)
                or not isinstance(self.slot_id, str)
                or not re.fullmatch(r"[a-f0-9]{32}", self.slot_id)
                or type(self.handover) is not bool
            ):
                raise ValueError("invalid_admission_policy")
        else:
            raise ValueError("invalid_admission_policy")

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            raise ValueError("explicit_admission_policy_required")  # noqa: TRY004 -- startup config error contract
        expected = (
            {"mode"}
            if value.get("mode") == "normal"
            else {"mode", "agent_id", "slot_id", "handover"}
        )
        if set(value) != expected:
            raise ValueError("invalid_admission_policy")
        return cls(**value)

    def permits(self, method, path):
        if self.mode == "normal":
            return True
        if (method, path) in {
            ("GET", "/healthz"),
            ("GET", "/api/auth/session"),
            ("POST", "/api/auth/login"),
            ("POST", "/api/auth/logout"),
            ("GET", f"/api/admin/agents/{self.agent_id}"),
            ("PUT", f"/api/admin/agents/{self.agent_id}/configuration"),
        }:
            return True
        root = f"/api/admin/agents/{self.agent_id}/target-handover"
        return self.handover and (method, path) in {
            ("GET", root),
            ("POST", root + "/preview"),
            ("POST", root + "/decisions"),
        }

    def check_slot(self, db):
        row = db.execute(
            "SELECT capacity,slot_ids FROM remote_control_groups WHERE agent_id=%s",
            (self.agent_id,),
        ).fetchone()
        if not row or row["capacity"] != 1 or row["slot_ids"] != [self.slot_id]:
            raise ValueError("maintenance_slot_not_registered")

    def preflight(self, database, remote_control):
        if self.mode == "normal":
            return
        if remote_control is None or remote_control.database is not database:
            raise ValueError("maintenance_requires_fixed_host_mailbox")
        with database.connection() as db:
            self.check_slot(db)
            if self.handover:
                # Catalogs need no new application GRANT. 019 is atomic; never
                # migrate here or infer readiness from a recovered HTTP error.
                for table in (
                    "control_target_contracts",
                    "control_target_candidates",
                    "control_target_plans",
                    "control_target_transitions",
                    "control_target_events",
                ):
                    if not db.execute(
                        "SELECT to_regclass(%s) AS object", (table,)
                    ).fetchone()["object"]:
                        raise ValueError("maintenance_requires_schema_019")
                found = db.execute(
                    "SELECT attname FROM pg_attribute WHERE attrelid=to_regclass('remote_control_groups') "
                    "AND attname IN ('target_epoch','pending_handover') AND NOT attisdropped"
                ).fetchall()
                if {r["attname"] for r in found} != {
                    "target_epoch",
                    "pending_handover",
                }:
                    raise ValueError("maintenance_requires_schema_019")
