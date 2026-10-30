"""Self-contained model-role delivery. No workflow/jobs/outbox database access."""

import hashlib
import json

from video_service.canonical import canonical
from video_service.object_store import ObjectIntegrityError, ObjectStoreError

from video_service.role_task_contracts import InvalidRoleDelivery, decode, validate


class DeliveryHeld(RuntimeError):
    """Keep this broker delivery unacknowledged; model work is not retried."""


def preserve_held_delivery(channel, active, item, held, *, slots, consumer):
    # Delivered manual-ACK messages survive consumer cancellation, not channel close.
    # Rebind with the original execution credit; changing QoS alone leaves the old
    # RabbitMQ consumer's exhausted credit in place. No held ACK/NACK/replay occurs.
    held.add(item[0])
    active.remove(item)
    tag, queue, callback = consumer
    channel.basic_cancel(tag)
    if len(held) > slots:
        return None  # bounded retained receipts; controls stay available
    channel.basic_qos(prefetch_count=slots)
    return channel.basic_consume(
        queue=queue, on_message_callback=callback, auto_ack=False
    )


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
            c.execute(
                "CREATE TABLE IF NOT EXISTS role_artifact_deliveries(task TEXT NOT NULL,kind TEXT NOT NULL,envelope_sha TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,response TEXT,error_code TEXT,PRIMARY KEY(task,kind))"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS role_cancel_ack_deliveries(task TEXT NOT NULL,kind TEXT NOT NULL,envelope_sha TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL,response TEXT,error_code TEXT,PRIMARY KEY(task,kind))"
            )

    def receive(self, packet):
        packet = validate(
            packet, "result", expected_role=getattr(self.agent, "role", "transcription")
        )
        task = packet["task"]
        source = packet["source"]
        owner = packet["output_owner"]
        reference = source["reference"]
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
                raise InvalidRoleDelivery("cancelled_role_envelope_changed")
            if row and row["envelope_sha"] != digest:
                raise InvalidRoleDelivery("immutable_role_envelope_changed")
            c.execute(
                "INSERT OR IGNORE INTO role_envelopes(task,envelope_sha)VALUES(?,?)",
                (task["task_id"], digest),
            )
        with self.agent.state.connect() as c:
            prior = c.execute(
                "SELECT status,result FROM tasks WHERE id=?", (task["task_id"],)
            ).fetchone()
        if (
            prior
            and prior["result"]
            and prior["status"] in {"completed", "cancelled", "held"}
        ):
            result = json.loads(prior["result"])
        else:
            path = self.inputs.path(source["owner"], reference)
            import wave

            try:
                result = self.agent.run(task, path)
            except (wave.Error, EOFError):
                raise InvalidRoleDelivery("invalid_pcm_audio") from None
            except ValueError as error:
                if type(error) is ValueError and str(error) in {
                    "audio_input_mismatch",
                    "normalized_audio_required",
                    "empty_audio_file",
                    "truncated_pcm_input",
                    "chunk_cache_mismatch",
                    "audio_clock_frame_count_mismatch",
                    "task_input_or_model_changed",
                }:
                    raise InvalidRoleDelivery(str(error)) from None
                raise
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

    def deliver(self, packet, *, kind="result", artifact_attempts=3):
        if type(artifact_attempts) is not int or artifact_attempts < 1:
            raise ValueError("positive_artifact_attempts_required")
        packet = validate(
            packet, kind, expected_role=getattr(self.agent, "role", "transcription")
        )
        task = packet["task_id"] if kind == "cancel_ack" else packet["task"]["task_id"]
        digest = hashlib.sha256(canonical(packet)).hexdigest()
        for store in [self.inputs, self.outputs]:
            if hasattr(store, "bind_delivery"):
                store.bind_delivery(packet, kind)

        def delivery_sql(statement):
            return (
                statement.replace(
                    "role_artifact_deliveries", "role_cancel_ack_deliveries"
                )
                if kind == "cancel_ack"
                else statement
            )

        with self.agent.state.lock(task, "artifact-" + kind):
            with self.agent.state.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                if kind == "cancel_ack":
                    try:
                        self.agent.state.cancel_in(
                            c, task, envelope_sha=packet["request_sha256"]
                        )
                    except ValueError as error:
                        if str(error) == "cancel_role_scope_mismatch":
                            raise InvalidRoleDelivery(
                                "cancel_role_scope_mismatch"
                            ) from None
                        raise
                row = c.execute(
                    delivery_sql(
                        "SELECT * FROM role_artifact_deliveries WHERE task=?AND kind=?"
                    ),
                    (task, kind),
                ).fetchone()
                if kind == "cancel_ack" and row is None:
                    legacy = c.execute(
                        "SELECT * FROM role_artifact_deliveries WHERE task=?AND kind=?",
                        (task, kind),
                    ).fetchone()
                    if (
                        legacy
                        and legacy["envelope_sha"] == digest
                        and legacy["state"] != "rejected"
                    ):
                        c.execute(
                            "INSERT INTO role_cancel_ack_deliveries(task,kind,envelope_sha,attempts,state,response,error_code) SELECT task,kind,envelope_sha,attempts,state,response,error_code FROM role_artifact_deliveries WHERE task=?AND kind=?",
                            (task, kind),
                        )
                        row = c.execute(
                            delivery_sql(
                                "SELECT * FROM role_artifact_deliveries WHERE task=?AND kind=?"
                            ),
                            (task, kind),
                        ).fetchone()
                if row and row["envelope_sha"] != digest:
                    raise InvalidRoleDelivery("immutable_role_delivery_changed")
                if row and row["state"] == "artifact_ready":
                    return json.loads(row["response"])
                if row and row["state"] == "held":
                    raise DeliveryHeld("artifact_delivery_held")
                if row and row["state"] == "rejected":
                    raise InvalidRoleDelivery("role_delivery_rejected")
                used = row["attempts"] if row else 0
                c.execute(
                    delivery_sql(
                        "INSERT OR IGNORE INTO role_artifact_deliveries(task,kind,envelope_sha,state)VALUES(?,?,?,'retrying')"
                    ),
                    (task, kind, digest),
                )
            for attempt in range(used, artifact_attempts):
                with self.agent.state.connect() as c:
                    c.execute(
                        delivery_sql(
                            "UPDATE role_artifact_deliveries SET attempts=attempts+1,state='retrying'WHERE task=?AND kind=?"
                        ),
                        (task, kind),
                    )
                try:
                    result = (
                        self.cancel(packet)
                        if kind == "cancel_ack"
                        else self.receive(packet)
                    )
                except ObjectIntegrityError:
                    with self.agent.state.connect() as c:
                        c.execute(
                            delivery_sql(
                                "UPDATE role_artifact_deliveries SET state='rejected',error_code='artifact_integrity'WHERE task=?AND kind=?"
                            ),
                            (task, kind),
                        )
                    raise InvalidRoleDelivery("artifact_integrity") from None
                except (ObjectStoreError, OSError) as error:
                    with self.agent.state.connect() as c:
                        c.execute(
                            delivery_sql(
                                "UPDATE role_artifact_deliveries SET state=?,error_code=?WHERE task=?AND kind=?"
                            ),
                            (
                                "held"
                                if attempt + 1 == artifact_attempts
                                else "retrying",
                                type(error).__name__,
                                task,
                                kind,
                            ),
                        )
                    if attempt + 1 == artifact_attempts:
                        raise DeliveryHeld("artifact_transport_exhausted") from None
                except InvalidRoleDelivery:
                    with self.agent.state.connect() as c:
                        c.execute(
                            delivery_sql(
                                "UPDATE role_artifact_deliveries SET state='rejected',error_code='invalid_role_input'WHERE task=?AND kind=?"
                            ),
                            (task, kind),
                        )
                    raise
                except Exception as error:
                    with self.agent.state.connect() as c:
                        c.execute(
                            delivery_sql(
                                "UPDATE role_artifact_deliveries SET state='held',error_code=?WHERE task=?AND kind=?"
                            ),
                            (type(error).__name__, task, kind),
                        )
                    raise DeliveryHeld("role_operation_held") from None
                else:
                    with self.agent.state.connect() as c:
                        c.execute(
                            delivery_sql(
                                "UPDATE role_artifact_deliveries SET state='artifact_ready',response=?,error_code=NULL WHERE task=?AND kind=?"
                            ),
                            (canonical(result).decode(), task, kind),
                        )
                    return result
            with self.agent.state.connect() as c:
                c.execute(
                    delivery_sql(
                        "UPDATE role_artifact_deliveries SET state='held',error_code='artifact_transport_exhausted'WHERE task=?AND kind=?"
                    ),
                    (task, kind),
                )
            raise DeliveryHeld("artifact_transport_exhausted")

    def cancel(self, packet):
        packet = validate(
            packet,
            "cancel_ack",
            expected_role=getattr(self.agent, "role", "transcription"),
        )
        try:
            actual = self.agent.state.cancel(
                packet["task_id"], envelope_sha=packet["request_sha256"]
            )
        except ValueError as error:
            if str(error) == "cancel_role_scope_mismatch":
                raise InvalidRoleDelivery("cancel_role_scope_mismatch") from None
            raise
        return {
            "version": 1,
            "role": packet["role"],
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

    from mideagent_model_runtime.cli import ScopedSpeechTool
    from mideagent_agents.transcription.model_graph import TranscriptionAgent

    if config["role"] not in {"transcription", "translation", "vocalization"}:
        raise ValueError("wrong_role_entrypoint")
    slots = config["task_slots"]
    if type(slots) is not int or slots < 1:
        raise ValueError("positive_task_slots_required")
    broker = BrokerConfig(**config["broker"])
    prefix = broker.namespace + "." + config["role"]
    for key in ["input_store", "output_store"]:
        Path(config[key]["cache_root"]).mkdir(parents=True, exist_ok=True)
    from mideagent_model_runtime.cli import ScopedTranslationTool, ScopedVocalTool
    from mideagent_agents.translation.model_graph import TranslationAgent
    from mideagent_model_tools.vocalization import VocalizationAgent

    agent_type = {
        "transcription": TranscriptionAgent,
        "translation": TranslationAgent,
        "vocalization": VocalizationAgent,
    }[config["role"]]
    tool_type = {
        "transcription": ScopedSpeechTool,
        "translation": ScopedTranslationTool,
        "vocalization": ScopedVocalTool,
    }[config["role"]]
    agent = agent_type(
        config["state_root"],
        tool_type(config),
        chunk_concurrency=config["chunk_concurrency"],
    )
    if config.get("storage_lease_enabled") is True:
        from mideagent_model_runtime.storage import TaskLeasedStore

        storage_tool = tool_type(config)
        inputs = TaskLeasedStore(config["input_store"], storage_tool)
        outputs = TaskLeasedStore(config["output_store"], storage_tool)
    else:
        inputs = from_config(config["input_store"])
        outputs = from_config(config["output_store"])
    receiver = RoleReceiver(agent, inputs, outputs, tool_mode=config["tool_mode"])
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
    held = set()
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
        try:
            packet = decode(body, "result", expected_role=config["role"])
        except InvalidRoleDelivery:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        active.append(
            (
                method.delivery_tag,
                pool.submit(
                    receiver.deliver,
                    packet,
                    artifact_attempts=config.get("artifact_delivery_attempts", 3),
                ),
                "result",
            )
        )
        if once:
            stop.set()

    def cancelled(ch, method, properties, body):
        if properties.type != "mideagent.model.cancel.v1":
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        try:
            packet = decode(body, "cancel_ack", expected_role=config["role"])
        except InvalidRoleDelivery:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        active.append(
            (
                method.delivery_tag,
                controls.submit(
                    receiver.deliver,
                    packet,
                    kind="cancel_ack",
                    artifact_attempts=config.get("artifact_delivery_attempts", 3),
                ),
                "cancel_ack",
            )
        )

    tag = channel.basic_consume(
        queue=queue, on_message_callback=received, auto_ack=False
    )
    control_tag = channel.basic_consume(
        queue=control_queue, on_message_callback=cancelled, auto_ack=False
    )
    from video_service.worker_lifecycle import WorkerPulse
    pulse=WorkerPulse()
    pulse.emit('ready')
    command_cancelled = False
    handled = 0
    try:
        while not stop.is_set() or active:
            connection.process_data_events(time_limit=0.05)
            if active:
                if pulse.phase!='busy':pulse.emit('busy',unsettled=len(active)+len(held))
            elif pulse.phase!='ready' and not stop.is_set():pulse.emit('ready',unsettled=len(held))
            pulse.tick()
            if stop.is_set() and not command_cancelled:
                if tag is not None:
                    channel.basic_cancel(tag)
                command_cancelled = True
            for item in list(active):
                delivery_tag, future, kind = item
                if not future.done():
                    continue
                try:
                    result = future.result()
                except DeliveryHeld:
                    if once:
                        raise
                    tag = preserve_held_delivery(
                        channel,
                        active,
                        item,
                        held,
                        slots=slots,
                        consumer=(tag, queue, received),
                    )
                    continue
                except InvalidRoleDelivery:
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
                pulse.emit('busy'if active else 'ready',completed=kind=='result',unsettled=len(active)+len(held))
                handled += 1
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        controls.shutdown(wait=True, cancel_futures=True)
        if connection.is_open:
            if channel.is_open:
                channel.basic_cancel(control_tag)
            connection.close()
        pulse.emit('stopped',unsettled=len(held))
    print(
        json.dumps(
            {
                "role": config["role"],
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
