"""Explicit AMQP 0-9-1 delivery; no connection, queue or SDK import at import time.

One owner thread performs all Pika operations. Bounded CPU/DB handlers run off that
thread so heartbeat servicing continues. No automatic reconnect or job replay.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

from .agent_protocol import COMMAND, MAX_MESSAGE, RESULT
from .cpu_agents import CPU_AGENTS, canonical, digest
from .node_contracts import node_spec, validate_node

ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,127}\Z")
ID = re.compile(r"[a-f0-9]{32}\Z")


class BrokerError(RuntimeError):
    """Public errors contain fixed codes, never endpoint or SDK exception text."""


class InvalidMessage(ValueError):
    pass


@dataclass(frozen=True)
class BrokerConfig:
    namespace: str
    url_env: str
    allow_loopback: bool = False
    ca_file: str | None = None

    def __post_init__(self):
        if (
            not isinstance(self.namespace, str)
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", self.namespace)
            or self.namespace.startswith("amq.")
            or not isinstance(self.url_env, str)
            or not ENV_NAME.fullmatch(self.url_env)
            or type(self.allow_loopback) is not bool
            or (self.ca_file is not None and not isinstance(self.ca_file, str))
        ):
            raise BrokerError("invalid_broker_config")

    @classmethod
    def from_env(cls, name, *, environ):
        try:
            if not isinstance(name, str) or not ENV_NAME.fullmatch(name):
                raise ValueError
            value = json.loads(environ[name])
            if not isinstance(value, dict) or set(value) - {
                "namespace",
                "url_env",
                "allow_loopback",
                "ca_file",
            }:
                raise ValueError
            return cls(**value)
        except (KeyError, TypeError, ValueError, BrokerError):
            raise BrokerError("invalid_broker_config") from None

    def parameters(self, *, environ, sdk):
        try:
            endpoint = environ[self.url_env]
            url = urlsplit(endpoint)
            try:
                loopback = ipaddress.ip_address(url.hostname).is_loopback
            except ValueError:
                loopback = url.hostname == "localhost"
            if (
                not url.hostname
                or not url.username
                or not url.password
                or url.path in ("", "/")
                or url.query
                or url.fragment
                or not (
                    url.scheme == "amqps"
                    or (url.scheme == "amqp" and loopback and self.allow_loopback)
                )
            ):
                raise ValueError
            params = sdk.URLParameters(endpoint)
            params.heartbeat = 30
            params.blocked_connection_timeout = 10
            params.socket_timeout = 5
            params.stack_timeout = 10
            params.connection_attempts = 1
            if url.scheme == "amqps":
                params.ssl_options = sdk.SSLOptions(
                    ssl.create_default_context(cafile=self.ca_file), url.hostname
                )
            return params
        except (KeyError, TypeError, ValueError, OSError):
            raise BrokerError("invalid_broker_endpoint") from None

    @property
    def commands(self):
        return self.namespace + ".commands.v1"

    @property
    def results(self):
        return self.namespace + ".results.v1"

    @property
    def dead(self):
        return self.namespace + ".dead.v1"

    def queue(self, role):
        if role not in CPU_AGENTS and role != "result":
            raise BrokerError("unsupported_broker_role")
        return self.namespace + "." + role + ".v1"


@dataclass(frozen=True)
class Delivery:
    body: bytes
    message_type: str
    message_id: str
    correlation_id: str
    content_type: str = "application/json"
    content_encoding: str = "utf-8"


def validate_command(command):
    try:
        if (
            not isinstance(command, dict)
            or set(command)
            != {
                "protocol_version",
                "run_id",
                "attempt_id",
                "generation",
                "agent",
                "inputs",
                "options",
            }
            or type(command["protocol_version"]) is not int
            or command["protocol_version"] != 1
            or type(command["generation"]) is not int
            or command["generation"] < 1
            or not ID.fullmatch(command["run_id"])
            or not ID.fullmatch(command["attempt_id"])
            or command["agent"] != {"id": command["agent"]["id"], "revision": "1"}
            or command["agent"]["id"] not in CPU_AGENTS
        ):
            raise ValueError
        for ref in command["inputs"].values():
            if (
                set(ref) != {"storage_key", "sha256", "bytes", "type"}
                or not re.fullmatch(r"[a-f0-9]{64}", ref["sha256"])
                or ref["storage_key"] != "blobs/" + ref["sha256"]
                or type(ref["bytes"]) is not int
                or not 0 < ref["bytes"] <= 256 * 1024 * 1024
            ):
                raise ValueError
        validate_node(
            {
                "node": command["agent"]["id"],
                "inputs": {k: v["type"] for k, v in command["inputs"].items()},
                "options": command["options"],
            }
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise InvalidMessage("invalid_command") from None
    return command


def validate_result(command, result):
    try:
        fields = {
            "protocol_version",
            "run_id",
            "attempt_id",
            "generation",
            "agent",
            "request_sha256",
            "status",
            "outputs",
            "transport",
        }
        failed = isinstance(result, dict) and result.get("status") == "failed"
        if not isinstance(result, dict) or set(result) != fields | (
            {"error"} if failed else set()
        ):
            raise ValueError
        if any(
            result.get(k) != command[k]
            for k in ("protocol_version", "run_id", "attempt_id", "generation", "agent")
        ):
            raise ValueError
        if (
            type(result["protocol_version"]) is not int
            or type(result["generation"]) is not int
            or result["request_sha256"] != digest(command)
            or result["status"] not in ("completed", "failed")
            or result["transport"] != "s3_subprocess"
            or not isinstance(result["outputs"], dict)
        ):
            raise ValueError
        if failed:
            error = result["error"]
            if (
                result["outputs"]
                or not isinstance(error, dict)
                or set(error) != {"code", "retryable"}
                or not isinstance(error["code"], str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"])
                or type(error["retryable"]) is not bool
            ):
                raise ValueError
        else:
            spec = node_spec(command["agent"]["id"])
            if spec is None or set(result["outputs"]) != set(spec["outputs"]):
                raise ValueError
            for port, ref in result["outputs"].items():
                if (
                    not isinstance(ref, dict)
                    or set(ref) != {"storage_key", "sha256", "bytes", "type"}
                    or not isinstance(ref["sha256"], str)
                    or not re.fullmatch(r"[a-f0-9]{64}", ref["sha256"])
                    or ref["storage_key"] != "blobs/" + ref["sha256"]
                    or type(ref["bytes"]) is not int
                    or not 0 < ref["bytes"] <= 268435456
                    or ref["type"] != spec["outputs"][port]
                ):
                    raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise InvalidMessage("invalid_result") from None
    return result


def envelope(owner, command, result=None):
    validate_command(command)
    if not isinstance(owner, str) or not ID.fullmatch(owner):
        raise InvalidMessage("invalid_owner")
    value = {"version": 1, "owner": owner, "command": command}
    if result is not None:
        validate_result(command, result)
        value["result"] = result
    body = canonical(value)
    if len(body) > MAX_MESSAGE:
        raise InvalidMessage("message_too_large")
    return Delivery(
        body,
        RESULT if result is not None else COMMAND,
        command["attempt_id"],
        command["run_id"],
    )


def decode(delivery, *, role=None, result=False):
    try:
        if (
            not isinstance(delivery.body, bytes)
            or len(delivery.body) > MAX_MESSAGE
            or delivery.message_type != (RESULT if result else COMMAND)
            or delivery.content_type != "application/json"
            or delivery.content_encoding != "utf-8"
        ):
            raise ValueError
        value = json.loads(delivery.body)
        if (
            not isinstance(value, dict)
            or set(value)
            != {"version", "owner", "command", *(["result"] if result else [])}
            or type(value["version"]) is not int
            or value["version"] != 1
            or (result and not isinstance(value["result"], dict))
        ):
            raise ValueError
        expected = envelope(value["owner"], value["command"], value.get("result"))
        if (
            expected.message_id != delivery.message_id
            or expected.correlation_id != delivery.correlation_id
            or (role is not None and value["command"]["agent"]["id"] != role)
        ):
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise InvalidMessage("invalid_delivery") from None


class RabbitClient:
    roles = CPU_AGENTS

    def __init__(self, config, connection, sdk):
        self.config, self.connection, self.sdk = config, connection, sdk
        self.owner_thread = threading.get_ident()
        self.channel = connection.channel()
        self.channel.confirm_delivery()

    @classmethod
    def connect(cls, config, *, environ):
        connection = None
        diagnostics = logging.getLogger("pika")
        if not any(
            isinstance(handler, logging.NullHandler) for handler in diagnostics.handlers
        ):
            diagnostics.addHandler(logging.NullHandler())
        diagnostics.propagate = False
        try:
            import pika

            params = config.parameters(environ=environ, sdk=pika)
            connection = pika.BlockingConnection(params)
            return cls(config, connection, pika)
        except Exception:  # noqa: BLE001 -- never expose SDK endpoint/credential diagnostics
            if connection is not None and connection.is_open:
                with suppress(OSError, pika.exceptions.AMQPError):
                    connection.close()
            raise BrokerError("broker_connection_failed") from None

    def _owner(self):
        if threading.get_ident() != self.owner_thread:
            raise BrokerError("broker_thread_mismatch")

    def observe(self, role):
        """Read queue connectivity only; no declaration, consumption or readiness claim."""
        self._owner()
        queue = self.config.queue(role)
        try:
            result = self.channel.queue_declare(queue=queue, passive=True).method
            return {
                "consumers": result.consumer_count,
                "messages_ready": result.message_count,
            }
        except self.sdk.exceptions.ChannelClosedByBroker as exc:
            code = (
                "broker_observation_forbidden"
                if exc.reply_code == 403
                else "broker_observation_failed"
            )
            raise BrokerError(code) from None
        except (OSError, self.sdk.exceptions.AMQPError):
            raise BrokerError("broker_observation_failed") from None

    def declare(self):
        """Explicit provisioning only; never called by connect or serve."""
        self._owner()
        c, cfg = self.channel, self.config
        for exchange in (cfg.commands, cfg.results, cfg.dead):
            c.exchange_declare(
                exchange=exchange,
                exchange_type="direct",
                durable=True,
                auto_delete=False,
            )
        for role in (*sorted(self.roles), "result"):
            queue = cfg.queue(role)
            dead = queue + ".dead"
            c.queue_declare(
                queue=dead,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments={"x-queue-type": "classic"},
            )
            c.queue_bind(queue=dead, exchange=cfg.dead, routing_key=role)
            arguments = {
                "x-queue-type": "classic",
                "x-dead-letter-exchange": cfg.dead,
                "x-dead-letter-routing-key": role,
            }
            if role != "result":
                arguments["x-message-ttl"] = 60000
            c.queue_declare(
                queue=queue,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments=arguments,
            )
            c.queue_bind(
                queue=queue,
                exchange=cfg.results if role == "result" else cfg.commands,
                routing_key=role,
            )

    def publish(self, delivery):
        self._owner()
        value = decode(delivery, result=delivery.message_type == RESULT)
        result = delivery.message_type == RESULT
        try:
            # BlockingChannel returns None on confirmed success; failures raise.
            self.channel.basic_publish(
                exchange=self.config.results if result else self.config.commands,
                routing_key="result" if result else value["command"]["agent"]["id"],
                body=delivery.body,
                mandatory=True,
                properties=self.sdk.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,
                    type=delivery.message_type,
                    message_id=delivery.message_id,
                    correlation_id=delivery.correlation_id,
                    expiration=None if result else "60000",
                ),
            )
        except (OSError, self.sdk.exceptions.AMQPError):
            raise BrokerError("broker_publish_unconfirmed") from None
        return True

    def serve(self, role, handler, stop, *, telemetry=None):
        """One unacked delivery, off-thread work, main-thread heartbeat/confirm/ack."""
        self._owner()
        c = self.channel
        c.queue_declare(queue=self.config.queue(role), passive=True)
        c.basic_qos(prefetch_count=1, global_qos=False)
        active = []
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-delivery")

        def status(state, delivery=None):
            if telemetry is None:
                return
            try:
                if delivery is not None:
                    telemetry.begin(delivery)
                elif state == "stopping":
                    telemetry.emit(state, telemetry.ticket, telemetry.attempt)
                else:
                    telemetry.emit(state)
            except Exception:  # telemetry failure must never alter job delivery/ACK
                return

        status("connected")

        def received(channel, method, properties, body):
            if stop.is_set():
                channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                return
            if active:
                raise BrokerError("broker_prefetch_violation")
            delivery = Delivery(
                body,
                properties.type,
                properties.message_id,
                properties.correlation_id,
                properties.content_type,
                properties.content_encoding,
            )
            status("busy", delivery)
            active.append((method.delivery_tag, pool.submit(handler, delivery)))

        tag = c.basic_consume(
            queue=self.config.queue(role), on_message_callback=received, auto_ack=False
        )
        status("ready")
        cancelled = False
        try:
            while not stop.is_set() or active:
                if stop.is_set() and not cancelled:
                    status("stopping")
                    c.basic_cancel(tag)
                    cancelled = True
                self.connection.process_data_events(time_limit=0.05)
                if telemetry is not None:
                    try:
                        telemetry.tick()
                    except Exception:  # reporting is a separate best-effort channel
                        pass
                if active and active[0][1].done():
                    delivery_tag, future = active.pop()
                    try:
                        outgoing = future.result()
                    except InvalidMessage:
                        c.basic_nack(delivery_tag=delivery_tag, requeue=False)
                        status("ready")
                        continue
                    # A handler/confirm failure leaves the delivery unacked. Closing
                    # requeues it, but the remote attempt marker forbids re-execution.
                    if outgoing is not None:
                        self.publish(outgoing)
                    c.basic_ack(delivery_tag=delivery_tag)
                    status("stopping" if stop.is_set() else "ready")
        except InvalidMessage:
            raise
        except Exception:  # noqa: BLE001 -- handler failure must leave delivery unacked and sanitized
            raise BrokerError("broker_consumer_stopped") from None
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            if c.is_open and not cancelled:
                c.basic_cancel(tag)
            status("stopped")
            if telemetry is not None:
                telemetry.close()

    def close(self):
        self._owner()
        try:
            if self.connection.is_open:
                self.connection.close()
        except (OSError, self.sdk.exceptions.AMQPError):
            raise BrokerError("broker_close_failed") from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
