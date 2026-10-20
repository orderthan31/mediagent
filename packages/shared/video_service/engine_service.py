"""Thread-pooled engine handler. Connections and ACKs remain on broker IO thread."""

from .engine_protocol import ENGINE_ROLES, decode, envelope


class EngineHandler:
    def __init__(self, role, executor):
        if role not in ENGINE_ROLES or executor.config["descriptor"]["role"] != role:
            raise ValueError("engine_worker_role_mismatch")
        self.role, self.executor = role, executor

    def __call__(self, delivery):
        value = decode(delivery, role=self.role)
        result = self.executor.execute(value["owner"], value["command"])
        return envelope(value["owner"], value["command"], result)


def _main(family, argv):
    import argparse
    import logging
    import signal
    import threading

    parser = argparse.ArgumentParser(
        description="Explicit offline engine AMQP consumer; no job scan"
    )
    roles = (
        ["transcribe", "translate"]
        if family == "model"
        else ["preprocess_audio", "faceswap"]
    )
    parser.add_argument("--enable-broker", action="store_true")
    parser.add_argument("--agent", required=True, choices=roles)
    parser.add_argument("--broker-config-file", required=True)
    parser.add_argument("--object-config-file", required=True)
    parser.add_argument("--runtime-config-file", required=True)
    args = parser.parse_args(argv)
    if not args.enable_broker:
        parser.error("Consumption requires --enable-broker")
    logging.getLogger("pika").disabled = True
    try:
        from .transport_files import document, object_store, engine_broker_factory
        from .engine_protocol import validate_runtime
        from .engine_object_agent import EngineObjectExecutor

        config = document(args.runtime_config_file)
        descriptor = validate_runtime(config["descriptor"])
        if descriptor["family"] != family or descriptor["role"] != args.agent:
            raise ValueError("engine_role_family_mismatch")
        executor = EngineObjectExecutor(object_store(args.object_config_file), config)
        handler = EngineHandler(args.agent, executor)
        factory = engine_broker_factory(args.broker_config_file)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        with factory() as client:
            client.serve(args.agent, handler, stop)
        return 0
    except Exception:
        print('{"status":"failed","code":"engine_broker_stopped"}')
        return 2


def model_main(argv=None):
    return _main("model", argv)


def gpu_main(argv=None):
    return _main("gpu", argv)
