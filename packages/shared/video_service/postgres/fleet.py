"""Administrative desired state and exact-command CPU routing, not a queue consumer."""

import threading
from uuid import uuid4

import psycopg

from ..cpu_agents import CPU_AGENTS, digest
from ..renewal_contracts import catalog
from . import Conflict, Missing


class Fleet:
    def __init__(self, database, driver=None):
        self.database, self.driver = database, driver
        self.controller_id = uuid4().hex
        self.guard = threading.RLock()
        self.controller_lock = None
        self.kinds = {n["id"] for n in catalog()["nodes"]}

    def _kind(self, agent):
        if agent not in self.kinds:
            raise Missing("에이전트를 찾을 수 없습니다.")
        return agent

    def _actor(self, db, actor):
        row = db.execute(
            "SELECT role,active FROM accounts WHERE id=%s FOR SHARE", (actor,)
        ).fetchone()
        if not row or row["role"] != "admin" or not row["active"]:
            raise PermissionError("관리자 권한이 필요합니다.")

    def _ownership(self):
        if self.controller_lock is None:
            conn = psycopg.connect(
                self.database.dsn, autocommit=True, connect_timeout=5
            )
            locked = conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(current_database()||':'||current_schema()||':cpu-fleet',0))"
            ).fetchone()[0]
            if not locked:
                conn.close()
                raise Conflict("다른 관리 프로세스가 실행환경을 소유하고 있습니다.")
            self.controller_lock = conn
        # Lost ownership is not permission to adopt or signal another process.
        self.controller_lock.execute("SELECT 1")

    def _refresh(self, db):
        if self.driver is None:
            return
        for row in db.execute(
            "SELECT * FROM agent_instances WHERE controller_id=%s AND state IN ('starting','ready','draining')",
            (self.controller_id,),
        ).fetchall():
            state, error, pid = row["state"], row["error_code"], row["pid"]
            if not self.driver.alive(row["id"]):
                self.driver.stop(row["id"])
                state, error = "failed", "cpu_instance_exited"
            elif state == "starting":
                # configure holds our guard across the ready handshake. A remaining
                # live starting row means that its subsequent DB write failed.
                # Recover only this driver's own confirmed process, never a PID scan.
                state, error = "ready", None
                pid = self.driver.pid(row["id"])
            elif state == "draining" and not row["in_flight"]:
                self.driver.stop(row["id"])
                state = "stopped"
            db.execute(
                "UPDATE agent_instances SET state=%s,error_code=%s,pid=%s,observed_at=now() WHERE id=%s",
                (state, error, pid, row["id"]),
            )

    def get(self, agent):
        self._kind(agent)
        with self.guard, self.database.connection() as db:
            self._refresh(db)
            config = db.execute(
                "SELECT revision,enabled,replicas,updated_at FROM agent_configurations WHERE agent_id=%s",
                (agent,),
            ).fetchone()
            config = config or {
                "revision": 0,
                "enabled": False,
                "replicas": 0,
                "updated_at": None,
            }
            rows = db.execute(
                "SELECT id,controller_id,state,in_flight,completed,pid,runtime,error_code,created_at,observed_at, observed_at>now()-interval '30 seconds' AS fresh FROM agent_instances WHERE agent_id=%s ORDER BY created_at,id",
                (agent,),
            ).fetchall()
            instances = []
            for row in rows:
                row = dict(row)
                if not row.pop("fresh") and row["state"] in (
                    "ready",
                    "draining",
                    "starting",
                ):
                    row["state"] = "unknown"
                row["local"] = row.pop("controller_id") == self.controller_id
                instances.append(
                    {
                        k: v.isoformat() if hasattr(v, "isoformat") else v
                        for k, v in row.items()
                    }
                )
            available = self.driver is not None and self.driver.supports(agent)
            ready = sum(i["state"] == "ready" for i in instances)
            draining = sum(i["state"] == "draining" for i in instances)
            state = (
                ("draining" if draining else "stopped")
                if not config["enabled"]
                else ("ready" if ready == config["replicas"] else "degraded")
            )
            return {
                "agent_id": agent,
                **{
                    k: v.isoformat() if hasattr(v, "isoformat") else v
                    for k, v in config.items()
                },
                "runtime": "cpu_subprocess" if available else "unavailable",
                "manageable": available,
                "state": state,
                "ready_replicas": ready,
                "draining_replicas": draining,
                "max_replicas": 8,
                "concurrency_per_instance": 1,
                "dependencies": ["ffmpeg", "ffprobe"] if agent in CPU_AGENTS else [],
                "unavailable_reason": None
                if available
                else "이 에이전트의 독립 실행환경이 연결되지 않았습니다. 모델/GPU 호출은 수행하지 않습니다.",
                "instances": instances,
            }

    def list(self):
        return [self.get(kind) for kind in sorted(self.kinds)]

    def configure(self, actor, agent, *, revision, enabled, replicas):
        self._kind(agent)
        if (
            type(revision) is not int
            or revision < 0
            or type(enabled) is not bool
            or type(replicas) is not int
            or not 0 <= replicas <= 8
            or enabled != (replicas > 0)
        ):
            raise ValueError("활성화 여부와 실행 개수를 확인하세요.")
        with self.guard:
            if enabled and (self.driver is None or not self.driver.supports(agent)):
                raise Conflict(
                    "설치·연결된 실행환경이 없습니다. 활성화 완료로 표시하지 않습니다."
                )
            with self.database.connection() as db:
                self._actor(db, actor)
                if self.driver is not None:
                    self._ownership()
                db.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(current_schema()||':fleet-configuration',0))"
                )
                old = db.execute(
                    "SELECT * FROM agent_configurations WHERE agent_id=%s FOR UPDATE",
                    (agent,),
                ).fetchone()
                if (old["revision"] if old else 0) != revision:
                    raise Conflict("설정이 변경됐습니다. 최신 상태를 다시 확인하세요.")
                self._refresh(db)
                others = db.execute(
                    "SELECT count(*) n FROM agent_instances WHERE state IN ('starting','ready','draining') AND agent_id<>%s",
                    (agent,),
                ).fetchone()["n"]
                current = db.execute(
                    "SELECT count(*) n FROM agent_instances WHERE agent_id=%s AND state IN ('starting','ready','draining')",
                    (agent,),
                ).fetchone()["n"]
                ready_count = db.execute(
                    "SELECT count(*) n FROM agent_instances WHERE agent_id=%s AND controller_id=%s AND state='ready'",
                    (agent, self.controller_id),
                ).fetchone()["n"]
                if others + current + max(0, replicas - ready_count) > 16:
                    raise Conflict(
                        "CPU 인스턴스 전체 상한 16개를 넘습니다. 드레인 종료 후 다시 적용하세요."
                    )
                db.execute(
                    "INSERT INTO agent_configurations(agent_id,revision,enabled,replicas,updated_by) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(agent_id) DO UPDATE SET revision=excluded.revision,enabled=excluded.enabled,replicas=excluded.replicas,updated_by=excluded.updated_by,updated_at=now()",
                    (agent, revision + 1, enabled, replicas, actor),
                )
                db.execute(
                    "INSERT INTO agent_configuration_events(agent_id,revision,enabled,replicas,actor_id) VALUES (%s,%s,%s,%s,%s)",
                    (agent, revision + 1, enabled, replicas, actor),
                )
                rows = db.execute(
                    "SELECT * FROM agent_instances WHERE agent_id=%s AND controller_id=%s AND state='ready' ORDER BY created_at,id FOR UPDATE",
                    (agent, self.controller_id),
                ).fetchall()
                for row in rows[replicas:]:
                    db.execute(
                        "UPDATE agent_instances SET state='draining',observed_at=now() WHERE id=%s",
                        (row["id"],),
                    )
                # Non-owned records are not PIDs we may adopt/terminate.
                unowned = db.execute(
                    "SELECT count(*) n FROM agent_instances WHERE agent_id=%s AND controller_id<>%s AND state IN ('starting','ready','draining')",
                    (agent, self.controller_id),
                ).fetchone()["n"]
                if unowned:
                    raise Conflict(
                        "이전 관리자의 인스턴스 상태가 남았습니다. 확인 없이 채택·중지·중복 기동하지 않습니다."
                    )
                self._refresh(db)
                count = min(len(rows), replicas)
            for _ in range(replicas - count):
                identity = uuid4().hex
                with self.database.connection() as db:
                    db.execute(
                        "INSERT INTO agent_instances(id,agent_id,controller_id,runtime,state) VALUES (%s,%s,%s,'cpu_subprocess','starting')",
                        (identity, agent, self.controller_id),
                    )
                try:
                    pid = self.driver.start(identity, agent)
                    with self.database.connection() as db:
                        db.execute(
                            "UPDATE agent_instances SET state='ready',pid=%s,observed_at=now() WHERE id=%s",
                            (pid, identity),
                        )
                except (ValueError, OSError, TimeoutError):
                    with self.database.connection() as db:
                        db.execute(
                            "UPDATE agent_instances SET state='failed',error_code='cpu_start_failed',observed_at=now() WHERE id=%s",
                            (identity,),
                        )
            return self.get(agent)

    def reasons(self, db, kinds):
        reasons = []
        for kind in sorted(set(kinds) & CPU_AGENTS):
            config = db.execute(
                "SELECT * FROM agent_configurations WHERE agent_id=%s", (kind,)
            ).fetchone()
            if not config or not config["enabled"]:
                reasons.append("관리자가 비활성화한 에이전트: " + kind)
            elif not db.execute(
                "SELECT 1 FROM agent_instances WHERE agent_id=%s AND controller_id=%s AND state='ready' LIMIT 1",
                (kind, self.controller_id),
            ).fetchone():
                reasons.append("준비된 실행 인스턴스가 없습니다: " + kind)
        return reasons

    def reserve(self, db, agent):
        config = db.execute(
            "SELECT * FROM agent_configurations WHERE agent_id=%s FOR SHARE", (agent,)
        ).fetchone()
        if not config or not config["enabled"] or self.driver is None:
            return None
        row = db.execute(
            "SELECT * FROM agent_instances WHERE agent_id=%s AND controller_id=%s AND state='ready' AND in_flight=0 ORDER BY last_assigned_at NULLS FIRST,completed,created_at,id FOR UPDATE SKIP LOCKED LIMIT 1",
            (agent, self.controller_id),
        ).fetchone()
        if row is None or not self.driver.alive(row["id"]):
            if row is not None:
                db.execute(
                    "UPDATE agent_instances SET state='failed',error_code='cpu_instance_exited' WHERE id=%s",
                    (row["id"],),
                )
            return None
        db.execute(
            "UPDATE agent_instances SET in_flight=1,last_assigned_at=now(),observed_at=now() WHERE id=%s",
            (row["id"],),
        )
        return row["id"]

    def execute(self, instance, owner, command):
        driver = self.driver
        if driver is None:
            raise ValueError("CPU runtime is not connected")
        completed = False
        try:
            result = driver.request(instance, owner, command)
            if any(
                result.get(k) != command[k]
                for k in (
                    "protocol_version",
                    "run_id",
                    "attempt_id",
                    "generation",
                    "agent",
                )
            ) or result.get("request_sha256") != digest(command):
                driver.stop(instance)
                raise ValueError("CPU result envelope mismatch")
            completed = result.get("status") == "completed"
            result["agent_instance_id"] = instance
            return result
        finally:
            with self.guard, self.database.connection() as db:
                db.execute(
                    "UPDATE agent_instances SET in_flight=0,completed=completed+%s,observed_at=now() WHERE id=%s AND controller_id=%s",
                    (int(completed), instance, self.controller_id),
                )
                self._refresh(db)

    def close(self):
        # Explicit API lifecycle shutdown; never scan or signal an arbitrary PID.
        with self.guard:
            if self.driver is not None:
                self.driver.close()
                with self.database.connection() as db:
                    db.execute(
                        "UPDATE agent_instances SET state='stopped',observed_at=now() WHERE controller_id=%s AND state IN ('starting','ready','draining')",
                        (self.controller_id,),
                    )
            if self.controller_lock is not None:
                self.controller_lock.close()
                self.controller_lock = None
