"""Broker fleet reporting contract; explicit I/O seams, not production acceptance."""

import importlib
import unittest
from contextlib import contextmanager

from video_service.rabbitmq_transport import BrokerError


class ReadOnlyDatabase:
    @contextmanager
    def connection(self):
        yield self

    def execute(self, query, parameters):
        assert query.lstrip().startswith("SELECT ")
        assert len(parameters) == 1
        return self

    def fetchone(self):
        return {"running": 2, "expired": 1, "completed": 3}


class ConnectedClient:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def observe(self, role):
        self.calls.append(role)
        return {"consumers": 2, "messages_ready": 3}


class BrokerFleetTests(unittest.TestCase):
    def fleet(self, client, engine=None):
        module = "video_service.postgres.broker_fleet"
        self.assertIsNotNone(importlib.util.find_spec(module), "AMQP fleet view missing")
        factory = lambda: client
        factory.engine_factory = engine
        return importlib.import_module(module).BrokerFleet(ReadOnlyDatabase(), factory)

    def test_api_selects_broker_view_instead_of_disabled_local_fleet(self):
        from app.renewal import create_app
        from types import SimpleNamespace

        app = create_app(
            ReadOnlyDatabase(),
            allowed_origins=("http://testserver",),
            secure_cookies=False,
            content_store=SimpleNamespace(storage_kind="s3"),
            local_execution=True,
            broker_factory=lambda: ConnectedClient(),
        )
        self.assertEqual(type(app.state.agent_fleet).__name__, "BrokerFleet")

    def test_connected_broker_is_not_local_process_ready_or_user_enabled(self):
        client = ConnectedClient()
        value = self.fleet(client).get("analyze")
        self.assertEqual(value["state"], "connected")
        self.assertEqual(value["runtime"], "amqp")
        self.assertIsNone(value["enabled"])
        self.assertFalse(value["manageable"])
        self.assertIsNone(value["ready_replicas"])
        self.assertEqual(value["consumers"], 2)
        self.assertEqual(value["activity"]["running"], 2)
        self.assertEqual(value["instances"], [])
        self.assertEqual(client.calls, ["analyze"])
    def test_forbidden_observation_is_unknown_and_does_not_leak_diagnostics(self):
        class Forbidden(ConnectedClient):
            def observe(self, role):
                raise BrokerError("broker_observation_forbidden")

        value = self.fleet(Forbidden()).get("analyze")
        self.assertEqual(value["state"], "unknown")
        self.assertIsNone(value["consumers"])
        self.assertIsNone(value["messages_ready"])
        self.assertEqual(value["observations"][0]["error_code"], "broker_observation_forbidden")

    def test_connection_failure_does_not_become_zero_or_emit_secret_diagnostics(self):
        class Failed(ConnectedClient):
            def observe(self, role):
                raise BrokerError("private sentinel endpoint")

        value = self.fleet(Failed()).get("analyze")
        self.assertEqual(value["state"], "unknown")
        self.assertNotIn("sentinel", str(value))

    def test_zero_consumers_is_a_successful_disconnected_observation(self):
        class Empty(ConnectedClient):
            def observe(self, role):
                return {"consumers": 0, "messages_ready": 0}

        value = self.fleet(Empty()).get("analyze")
        self.assertEqual(value["state"], "disconnected")
        self.assertEqual(value["consumers"], 0)

    def test_model_roles_use_engine_factory_only(self):
        cpu, engine = ConnectedClient(), ConnectedClient()
        value = self.fleet(cpu, lambda: engine).get("transcribe")
        self.assertEqual(value["state"], "connected")
        self.assertEqual(cpu.calls, [])
        self.assertEqual(engine.calls, ["transcribe"])

    def test_preprocess_preserves_both_cpu_and_engine_observations(self):
        cpu, engine = ConnectedClient(), ConnectedClient()
        value = self.fleet(cpu, lambda: engine).get("preprocess_audio")
        self.assertEqual(value["consumers"], 4)
        self.assertEqual([r["family"] for r in value["observations"]], ["cpu", "engine"])

    def test_partial_observation_cannot_claim_complete_connectivity(self):
        class Failed(ConnectedClient):
            def observe(self, role):
                raise BrokerError("broker_observation_failed")

        value = self.fleet(ConnectedClient(), lambda: Failed()).get("preprocess_audio")
        self.assertEqual(value["state"], "unknown")
        self.assertIsNone(value["consumers"])
        self.assertEqual(value["observations"][0]["consumers"], 2)

    def test_controller_and_unsupported_nodes_never_claim_worker_connections(self):
        client = ConnectedClient()
        fleet = self.fleet(client)
        self.assertEqual(fleet.get("review")["state"], "controller")
        for kind in ["decision", "control_loop", "control_fallback", "transcribe"]:
            self.assertEqual(fleet.get(kind)["state"], "unsupported")
        self.assertEqual(client.calls, [])

    def test_remote_configuration_is_rejected_without_a_state_write(self):
        from video_service.postgres import Conflict

        with self.assertRaises(Conflict):
            self.fleet(ConnectedClient()).configure("a" * 32, "analyze", enabled=True, replicas=1, revision=0)


if __name__ == "__main__":
    unittest.main()
