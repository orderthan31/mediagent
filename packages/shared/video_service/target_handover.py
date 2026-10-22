"""Offline trusted-host target handover. Inspect/verify only; NEVER start/stop.

The old host must relinquish its existing exclusive lock. The same logical slot
stays disabled. New host startup needs an explicit matching local binding file.
"""

import hashlib
import json
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .agent_control import ControlError, Target
from .postgres import Conflict, Missing
from .postgres.control_recovery import admin, digest

HOST_LOCK = "SELECT pg_try_advisory_lock(hashtextextended(current_database()||':'||current_schema()||':fixed-host-control-v1',0)) AS locked"


def descriptor(target, worker):
    return {
        "container_id": target.container_id,
        "image_id": target.image_id,
        "labels": dict(target.labels),
        "worker_id": worker,
    }


def target_from(value):
    if not isinstance(value, dict) or set(value) != {
        "container_id",
        "image_id",
        "labels",
        "worker_id",
    }:
        raise ControlError("invalid_handover_binding")
    target = Target(
        value["container_id"], value["image_id"], tuple(sorted(value["labels"].items()))
    )
    if dict(target.labels).get("mideagent.worker_id") != value["worker_id"]:
        raise ControlError("worker_identity_pin_required")
    return target


def contract(value):
    target = target_from(value)
    canonical = [
        {
            "container_id": target.container_id,
            "image_id": target.image_id,
            "labels": target.labels,
            "worker_id": value["worker_id"],
        }
    ]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


class HandoverHost:
    def __init__(self, ledger, old_adapter, new_adapter, slots, receipts):
        self.ledger, self.database = ledger, ledger.database
        self.old, self.new, self.slots, self.receipts = (
            old_adapter,
            new_adapter,
            slots,
            receipts,
        )
        if set(old_adapter.groups) != set(new_adapter.groups) or set(slots) != set(
            old_adapter.groups
        ):
            raise ControlError("handover_group_mismatch")
        for group, ids in slots.items():
            if (
                len(ids) != 1
                or len(old_adapter._targets(group)) != 1
                or len(new_adapter._targets(group)) != 1
            ):
                raise ControlError("handover_requires_exactly_one_slot")
            a, b = self.bindings(group)
            for label in (
                "com.docker.compose.project",
                "com.docker.compose.service",
                "mideagent.worker_id",
            ):
                if a["labels"].get(label) != b["labels"].get(label):
                    raise ControlError("handover_changes_logical_identity")
            if (
                a["container_id"] == b["container_id"]
                or a["worker_id"] != ids[0]
                or b["worker_id"] != ids[0]
            ):
                raise ControlError("handover_requires_distinct_exact_target")

    def bindings(self, group):
        worker = self.slots[group][0]
        return descriptor(self.old._targets(group)[0], worker), descriptor(
            self.new._targets(group)[0], worker
        )

    @contextmanager
    def exclusive(self, group):
        with psycopg.connect(
            self.database.dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
        ) as owner:
            if not owner.execute(HOST_LOCK).fetchone()["locked"]:
                raise Conflict("handover_old_host_still_owned")
            if not owner.execute(
                "SELECT pg_try_advisory_lock(hashtextextended('dispatch-agent:'||%s,0)) AS locked",
                (group,),
            ).fetchone()["locked"]:
                raise Conflict("handover_sender_still_owned")
            yield owner

    def physical(self, group, context):
        old, _new = self.bindings(group)
        before = self.old.details(group)["instances"][0]
        after = self.new.details(group)["instances"][0]
        observed = context["observation"]
        if (
            before["running"]
            or before["state"] != "exited"
            or before["exit_code"] != 0
            or after["running"]
            or after["state"] not in ("created", "exited")
            or after["exit_code"] != 0
            or before["started_at"] != observed.get("started_at")
            or old["container_id"] != observed["target_id"]
            or old["image_id"] != observed["image_id"]
        ):
            raise Conflict("handover_native_evidence_changed")
        action = dict(context["stop_action"])
        # AckReceipts binds issued_at and full old pin/boot; its key never leaves host.
        proof = self.receipts.read(action, context["contract"], target_from(old))
        if (
            not proof
            or proof["sha256"] != context["ack"]["receipt_sha256"]
            or proof["facts"] != context["ack"]["facts"]
        ):
            raise Conflict("handover_signed_stop_changed")
        return {"old": before, "new": after, "receipt_sha256": proof["sha256"]}

    def prepare(self, group):
        old, new = self.bindings(group)
        with self.exclusive(group), self.database.connection() as db:
            current = self.ledger.group_in(db, group)
            context = self.ledger.context_in(db, current)
            if current["contract_sha256"] != contract(old):
                raise Conflict("handover_old_contract_mismatch")
            physical = self.physical(group, context)
            db.execute(
                "INSERT INTO control_target_contracts(agent_id,epoch,contract_sha256,descriptor) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (group, current["target_epoch"], contract(old), Jsonb(old)),
            )
            root = db.execute(
                "SELECT descriptor,contract_sha256 FROM control_target_contracts WHERE agent_id=%s AND epoch=%s",
                (group, current["target_epoch"]),
            ).fetchone()
            if root["descriptor"] != old or root["contract_sha256"] != contract(old):
                raise Conflict("handover_historical_binding_mismatch")
            result = db.execute(
                "INSERT INTO control_target_candidates(id,agent_id,from_epoch,from_contract,old_descriptor,new_descriptor,new_contract,native_evidence,context,context_sha256) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    uuid4().hex,
                    group,
                    current["target_epoch"],
                    current["contract_sha256"],
                    Jsonb(old),
                    Jsonb(new),
                    contract(new),
                    Jsonb(physical),
                    Jsonb(context),
                    digest(context),
                ),
            ).fetchone()
            return dict(result)

    def _check(self, db, transition):
        admin(db, transition["actor_id"], lock=False)
        current = self.ledger.group_in(db, transition["agent_id"])
        context = self.ledger.context_in(db, current, pending=transition["id"])
        candidate = db.execute(
            "SELECT * FROM control_target_candidates WHERE id=%s",
            (transition["candidate_id"],),
        ).fetchone()
        if digest(context) != candidate["context_sha256"] or self.bindings(
            transition["agent_id"]
        ) != (candidate["old_descriptor"], candidate["new_descriptor"]):
            raise Conflict("handover_evidence_changed")
        if (
            self.physical(transition["agent_id"], context)
            != candidate["native_evidence"]
        ):
            raise Conflict("handover_native_evidence_changed")
        return current, candidate

    def hold(self, identity, code):
        with self.database.connection() as db:
            return dict(
                db.execute(
                    "UPDATE control_target_transitions SET phase='held',error_code=%s,updated_at=now() WHERE id=%s AND phase IN ('planned','applying') RETURNING *",
                    (code, identity),
                ).fetchone()
            )

    def apply(self, identity):
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM control_target_transitions WHERE id=%s", (identity,)
            ).fetchone()
            if not row:
                raise Missing("handover_transition_missing")
            agent = row["agent_id"]
            if row["phase"] in ("applied", "held"):
                return dict(row)
        with self.exclusive(agent):
            with self.database.connection() as db:
                row = db.execute(
                    "SELECT * FROM control_target_transitions WHERE id=%s FOR UPDATE",
                    (identity,),
                ).fetchone()
                if row["phase"] in ("applied", "held"):
                    return dict(row)
                if row["phase"] == "applying":
                    return self.hold_interrupted(db, identity)
                try:
                    self._check(db, row)
                except (Conflict, ControlError, PermissionError):
                    return self.hold_in(
                        db, identity, "handover_evidence_or_authority_changed"
                    )
                db.execute(
                    "UPDATE control_target_transitions SET phase='applying',updated_at=now() WHERE id=%s",
                    (identity,),
                )
            # Applying is durable before the commit window. An interrupted applying
            # state is held on the next EXPLICIT call, never automatically resumed.
            try:
                return self._finish(identity)
            except (Conflict, ControlError, PermissionError):
                return self.hold(identity, "handover_evidence_or_authority_changed")

    @staticmethod
    def hold_in(db, identity, code):
        return dict(
            db.execute(
                "UPDATE control_target_transitions SET phase='held',error_code=%s,updated_at=now() WHERE id=%s RETURNING *",
                (code, identity),
            ).fetchone()
        )

    def hold_interrupted(self, db, identity):
        return self.hold_in(db, identity, "handover_interrupted_requires_review")

    def _finish(self, identity):
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM control_target_transitions WHERE id=%s FOR UPDATE",
                (identity,),
            ).fetchone()
            current, candidate = self._check(db, row)
            db.execute(
                "INSERT INTO control_target_contracts(agent_id,epoch,contract_sha256,descriptor,transition_id) VALUES(%s,%s,%s,%s,%s)",
                (
                    row["agent_id"],
                    current["target_epoch"] + 1,
                    candidate["new_contract"],
                    Jsonb(candidate["new_descriptor"]),
                    identity,
                ),
            )
            db.execute(
                "UPDATE remote_control_groups SET contract_sha256=%s,target_epoch=target_epoch+1,pending_handover=NULL,observed=NULL,observed_at=NULL,revision=revision+1 WHERE agent_id=%s",
                (candidate["new_contract"], row["agent_id"]),
            )
            return dict(
                db.execute(
                    "UPDATE control_target_transitions SET phase='applied',updated_at=now() WHERE id=%s RETURNING *",
                    (identity,),
                ).fetchone()
            )


def resolve_active(ledger, group, configured, approved):
    """New host must explicitly allow the EXACT approved active descriptor locally."""
    with ledger.database.connection() as db:
        current = ledger.group_in(db, group)
        if current["pending_handover"]:
            raise ControlError("handover_pending_host_start_blocked")
        if current["target_epoch"] == 0:
            return configured
        active = db.execute(
            "SELECT * FROM control_target_contracts WHERE agent_id=%s AND epoch=%s",
            (group, current["target_epoch"]),
        ).fetchone()
        root = db.execute(
            "SELECT * FROM control_target_contracts WHERE agent_id=%s AND epoch=0",
            (group,),
        ).fetchone()
        if (
            not active
            or not root
            or configured not in (root["descriptor"], active["descriptor"])
        ):
            raise ControlError("handover_root_binding_mismatch")
        if (
            approved != active["descriptor"]
            or contract(approved) != current["contract_sha256"]
        ):
            raise ControlError("handover_exact_local_binding_required")
        return approved


def main():
    import argparse
    from pathlib import Path

    from .control_ack_receipts import AckReceipts
    from .control_runtime import PinnedEngine
    from .durable_control import SignalControl
    from .postgres import Database
    from .postgres.control_recovery import public
    from .postgres.remote_control import RemoteControl
    from .postgres.target_handover import TargetHandover

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--candidate-file", required=True)
    parser.add_argument("--operation", choices=("prepare", "apply"), required=True)
    parser.add_argument("--transition-id")
    parser.add_argument("--enable-handover", action="store_true")
    args = parser.parse_args()
    if not args.enable_handover:
        parser.error("Explicit --enable-handover is required")
    try:

        def read(path):
            raw = Path(path).read_bytes()
            if len(raw) > 32768:
                raise ControlError("invalid_handover_configuration")
            return json.loads(raw)

        config, manifest = read(args.config_file), read(args.candidate_file)
        if set(manifest) != {"agent", "old", "new"}:
            raise ControlError("invalid_handover_manifest")
        group = manifest["agent"]
        spec = config["groups"][group]
        if len(spec["slots"]) != 1:
            raise ControlError("handover_requires_exactly_one_slot")
        configured = spec["slots"][0]
        ledger = TargetHandover(
            RemoteControl(
                Database(Path(config["database_dsn_file"]).read_text().strip())
            )
        )
        if args.operation == "apply":
            with ledger.database.connection() as db:
                previous = db.execute(
                    "SELECT t.*,c.old_descriptor,c.new_descriptor FROM control_target_transitions t JOIN control_target_candidates c ON c.id=t.candidate_id WHERE t.id=%s",
                    (args.transition_id,),
                ).fetchone()
                if previous and previous["phase"] in ("applied", "held"):
                    if (
                        previous["agent_id"] != group
                        or previous["old_descriptor"] != manifest["old"]
                        or previous["new_descriptor"] != manifest["new"]
                    ):
                        raise ControlError("handover_manifest_mismatch")
                    print(json.dumps(dict(previous), default=public))
                    return
        if args.operation == "apply":
            # A pending transition blocks normal HOST STARTUP, not this explicit
            # offline verifier. It must still match the immutable configured root
            # and the exact currently registered old contract.
            with ledger.database.connection() as db:
                current = ledger.group_in(db, group)
                root = db.execute(
                    "SELECT descriptor FROM control_target_contracts WHERE agent_id=%s AND epoch=0",
                    (group,),
                ).fetchone()
                if (
                    not root
                    or configured != root["descriptor"]
                    or contract(manifest["old"]) != current["contract_sha256"]
                ):
                    raise ControlError("handover_root_binding_mismatch")
            resolved = manifest["old"]
        else:
            resolved = resolve_active(ledger, group, configured, manifest["old"])
        if resolved != manifest["old"]:
            raise ControlError("handover_old_manifest_mismatch")

        class InspectOnly(PinnedEngine):
            def __call__(self, args):
                if args[:2] != ["container", "inspect"]:
                    raise ControlError("handover_native_mutation_forbidden")
                return super().__call__(args)

        engine = InspectOnly(
            config["docker_socket"],
            (target_from(resolved), target_from(manifest["new"])),
        )
        old = SignalControl({group: (target_from(resolved),)}, runner=engine)
        new = SignalControl({group: (target_from(manifest["new"]),)}, runner=engine)
        receipts = AckReceipts(
            config["receipt_root"], Path(config["receipt_key_file"]).read_bytes()
        )
        host = HandoverHost(
            ledger, old, new, {group: [resolved["worker_id"]]}, receipts
        )
        result = (
            host.prepare(group)
            if args.operation == "prepare"
            else host.apply(args.transition_id)
        )
        print(json.dumps(result, default=public))
    except Exception:  # noqa: BLE001 - never expose DSNs/native diagnostics at CLI boundary
        print(
            json.dumps({"status": "blocked", "code": "target_handover_not_completed"})
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
