"""Self-contained model-role delivery. No workflow/jobs/outbox database access."""

import hashlib
import json
import re

from video_service.cpu_agents import canonical
from video_service.object_store import validate_reference


class RoleReceiver:
    def __init__(self, agent, inputs, outputs, *, tool_mode="unverified_tool"):
        self.agent, self.inputs, self.outputs, self.tool_mode = (
            agent,
            inputs,
            outputs,
            tool_mode,
        )
        with agent.state.connect() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS role_envelopes(task TEXT PRIMARY KEY,envelope_sha TEXT NOT NULL)"
            )

    def receive(self, packet):
        packet = json.loads(canonical(packet))
        if (
            set(packet) != {"version", "role", "task", "source", "output_owner"}
            or type(packet["version"]) is not int
            or packet["version"] != 1
            or packet["role"] != "transcription"
        ):
            raise ValueError("invalid_self_contained_role_envelope")
        task = packet["task"]
        source = packet["source"]
        owner = packet["output_owner"]
        if task["role"] != packet["role"] or not re.fullmatch(
            "[a-f0-9]{32}", task["task_id"]
        ):
            raise ValueError("role_scope_mismatch")
        if (
            set(source) != {"owner", "reference"}
            or not re.fullmatch("[a-f0-9]{32}", source["owner"])
            or not re.fullmatch("[a-f0-9]{32}", owner)
        ):
            raise ValueError("invalid_artifact_scope")
        reference = source["reference"]
        validate_reference(reference)
        if any(task["audio"][k] != reference[k] for k in ["sha256", "bytes"]):
            raise ValueError("role_input_reference_mismatch")
        digest = hashlib.sha256(canonical(packet)).hexdigest()
        with self.agent.state.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT envelope_sha FROM role_envelopes WHERE task=?",
                (task["task_id"],),
            ).fetchone()
            cancelled = c.execute(
                "SELECT envelope_sha FROM role_cancellations WHERE task=?",
                (task["task_id"],),
            ).fetchone()
            if cancelled and cancelled["envelope_sha"] != digest:
                raise ValueError("cancelled_role_envelope_changed")
            if row and row["envelope_sha"] != digest:
                raise ValueError("immutable_role_envelope_changed")
            c.execute(
                "INSERT OR IGNORE INTO role_envelopes(task,envelope_sha)VALUES(?,?)",
                (task["task_id"], digest),
            )
        path = self.inputs.path(source["owner"], reference)
        result = self.agent.run(task, path)
        payload = {
            "version": 1,
            "role": packet["role"],
            "request_sha256": digest,
            "task": task,
            "source": source,
            "tool_mode": self.tool_mode,
            "result": result,
        }
        output = self.outputs.put(owner, [canonical(payload)], "model_result")
        return {
            "version": 1,
            "role": packet["role"],
            "task_id": task["task_id"],
            "request_sha256": digest,
            "status": result["status"],
            "output_owner": owner,
            "result_ref": output,
        }

    def cancel(self, packet):
        if (
            set(packet) != {"version", "role", "task_id", "request_sha256"}
            or type(packet["version"]) is not int
            or packet["version"] != 1
            or packet["role"] != "transcription"
            or not re.fullmatch("[a-f0-9]{32}", packet["task_id"])
            or not re.fullmatch("[a-f0-9]{64}", packet["request_sha256"])
        ):
            raise ValueError("invalid_role_cancel_scope")
        actual = self.agent.state.cancel(
            packet["task_id"], envelope_sha=packet["request_sha256"]
        )
        return {
            "version": 1,
            "role": "transcription",
            "task_id": packet["task_id"],
            "request_sha256": packet["request_sha256"],
            "status": actual["status"],
            "kind": "cancel_ack",
        }


def consume(config, *, once=False):
    import os
    import signal
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import pika
    from video_service.object_store import from_config
    from video_service.rabbitmq_transport import BrokerConfig

    from .cli import ScopedSpeechTool
    from .transcription import TranscriptionAgent

    if config["role"] != "transcription":
        raise ValueError("wrong_role_entrypoint")
    slots = config["task_slots"]
    if type(slots) is not int or slots < 1:
        raise ValueError("positive_task_slots_required")
    broker = BrokerConfig(**config["broker"])
    prefix = broker.namespace + ".transcription"
    for key in ["input_store", "output_store"]:
        Path(config[key]["cache_root"]).mkdir(parents=True, exist_ok=True)
    agent = TranscriptionAgent(
        config["state_root"],
        ScopedSpeechTool(config),
        chunk_concurrency=config["chunk_concurrency"],
    )
    receiver = RoleReceiver(
        agent,
        from_config(config["input_store"]),
        from_config(config["output_store"]),
        tool_mode=config["tool_mode"],
    )
    connection = pika.BlockingConnection(
        broker.parameters(environ=os.environ, sdk=pika)
    )
    channel = connection.channel()
    channel.confirm_delivery()
    queue = prefix + ".inbox.v1"
    control_queue = prefix + ".cancel.v1"
    for q in [queue, control_queue]:
        channel.queue_declare(queue=q, passive=True)
    channel.basic_qos(prefetch_count=1 if once else slots)
    stop = threading.Event()
    active = []
    pool = ThreadPoolExecutor(max_workers=slots, thread_name_prefix="role-command")
    controls = ThreadPoolExecutor(max_workers=slots, thread_name_prefix="role-control")
    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, lambda *_: stop.set())

    def received(ch, method, properties, body):
        if stop.is_set():
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return
        if properties.type != "mideagent.model.command.v1":
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        packet = json.loads(body)
        active.append(
            (method.delivery_tag, pool.submit(receiver.receive, packet), "result")
        )
        if once:
            stop.set()

    def cancelled(ch, method, properties, body):
        if properties.type != "mideagent.model.cancel.v1":
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        packet = json.loads(body)
        active.append(
            (
                method.delivery_tag,
                controls.submit(receiver.cancel, packet),
                "cancel_ack",
            )
        )

    tag = channel.basic_consume(
        queue=queue, on_message_callback=received, auto_ack=False
    )
    control_tag = channel.basic_consume(
        queue=control_queue, on_message_callback=cancelled, auto_ack=False
    )
    command_cancelled = False
    handled = 0
    try:
        while not stop.is_set() or active:
            connection.process_data_events(time_limit=0.05)
            if stop.is_set() and not command_cancelled:
                channel.basic_cancel(tag)
                command_cancelled = True
            for item in list(active):
                delivery_tag, future, kind = item
                if not future.done():
                    continue
                try:
                    result = future.result()
                except ValueError:
                    channel.basic_nack(delivery_tag=delivery_tag, requeue=False)
                    active.remove(item)
                    continue
                channel.basic_publish(
                    exchange=prefix + ".results.v1",
                    routing_key="result",
                    body=canonical(result),
                    mandatory=True,
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=2,
                        type="mideagent.model." + kind + ".v1",
                        message_id=result["task_id"],
                    ),
                )
                channel.basic_ack(delivery_tag=delivery_tag)
                active.remove(item)
                handled += 1
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        controls.shutdown(wait=True, cancel_futures=True)
        if connection.is_open:
            if channel.is_open:
                channel.basic_cancel(control_tag)
            connection.close()
    print(
        json.dumps(
            {
                "role": "transcription",
                "handled_deliveries": handled,
                "mode": config["tool_mode"],
            }
        )
    )


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        consume(json.loads(Path(args.config).read_text()), once=args.once)
    except Exception as error:
        print(json.dumps({"status": "held", "error": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
