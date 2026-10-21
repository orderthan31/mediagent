"""Read-only independent consumer observations, separate from local fleet control.

A consumer connection is not inference readiness. No instance IDs, PIDs, target
replicas or configuration are invented from queue counts. No topology is created.
"""

from datetime import datetime, timezone

from ..cpu_agents import CPU_AGENTS
from ..rabbitmq_transport import BrokerError
from ..renewal_contracts import catalog
from . import Conflict, Missing

CONTROLLER_NODES = frozenset({"select", "join", "review", "control_if", "control_switch"})
ENGINE_NODES = frozenset({"transcribe", "translate", "faceswap"})


class BrokerFleet:
    def __init__(self, database, factory, *, telemetry=None):
        self.database = database
        self.telemetry = telemetry
        self.factory = factory
        self.engine_factory = getattr(factory, "engine_factory", None)
        self.kinds = {node["id"] for node in catalog()["nodes"]}

    def _activity(self, agent):
        with self.database.connection() as db:
            return dict(
                db.execute(
                    "SELECT count(*) FILTER (WHERE status='running' AND lease_expires_at>now()) AS running, "
                    "count(*) FILTER (WHERE status='running' AND lease_expires_at<=now()) AS expired, "
                    "count(*) FILTER (WHERE status='completed') AS completed "
                    "FROM node_runs WHERE node_type=%s",
                    (agent,),
                ).fetchone()
            )

    def get(self, agent):
        if agent not in self.kinds:
            raise Missing("에이전트를 찾을 수 없습니다.")
        value = {
            "agent_id": agent,
            "revision": 0,
            "enabled": None,
            "replicas": None,
            "ready_replicas": None,
            "draining_replicas": None,
            "runtime": "amqp",
            "observation_source": "amqp",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "manageable": False,
            "max_replicas": 0,
            "concurrency_per_instance": 1,
            "dependencies": [],
            "instances": [],
            "activity": self._activity(agent),
            "consumers": None,
            "messages_ready": None,
            "observations": [],
            "unavailable_reason": "원격 시작·중지·확장 제어는 아직 연결되지 않았습니다.",
        }
        if agent in CONTROLLER_NODES:
            return {
                **value,
                "runtime": "application_controller",
                "state": "controller",
                "unavailable_reason": "애플리케이션 제어 노드입니다. 독립 worker의 켜짐/꺼짐 상태가 아닙니다.",
            }
        factories = []
        if agent in CPU_AGENTS:
            factories.append(("cpu", self.factory))
        if agent in ENGINE_NODES or agent == "preprocess_audio":
            if self.engine_factory is not None:
                factories.append(("engine", self.engine_factory))
        if not factories:
            return {
                **value,
                "runtime": "unavailable",
                "state": "unsupported",
                "unavailable_reason": "이 노드의 독립 실행 경로는 아직 연결되지 않았습니다.",
            }
        if self.telemetry is not None:
            observed = self.telemetry.role(agent)
            workers = observed["workers"]
            state = "unknown"
            if observed["collector"]["healthy"] and workers:
                for candidate in ("busy", "ready", "connected", "stopping", "heartbeat_lost", "stopped"):
                    if any(worker["state"] == candidate for worker in workers):
                        state = candidate
                        break
            return {**value, **observed, "telemetry": True, "state": state,
                    "observed_at": observed["collector"]["received_at"]}
        for family, factory in factories:
            try:
                with factory() as client:
                    counts = client.observe(agent)
                observation = {"family": family, "status": "observed", **counts}
            except BrokerError as error:
                code = str(error)
                observation = {
                    "family": family,
                    "status": "unknown",
                    "error_code": code
                    if code in {"broker_observation_forbidden", "broker_observation_failed"}
                    else "broker_observation_failed",
                    "consumers": None,
                    "messages_ready": None,
                }
            value["observations"].append(observation)
        if any(item["status"] == "unknown" for item in value["observations"]):
            return {**value, "state": "unknown"}
        consumers = sum(item["consumers"] for item in value["observations"])
        return {
            **value,
            "state": "connected" if consumers else "disconnected",
            "consumers": consumers,
            "messages_ready": sum(item["messages_ready"] for item in value["observations"]),
        }

    def list(self):
        return [self.get(agent) for agent in sorted(self.kinds)]

    def configure(self, actor, agent, **configuration):
        if agent not in self.kinds:
            raise Missing("에이전트를 찾을 수 없습니다.")
        raise Conflict("AMQP 원격 제어가 연결되지 않았습니다. 설정만 켜짐으로 저장하지 않습니다.")
