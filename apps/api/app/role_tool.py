"""Private TLS credential bridge for independent roles; no queue scan or model at startup."""

import argparse
import hmac
import json
import signal
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from video_service.cpu_agents import canonical
from video_service.model_role_tool import RoleToolBridge
from video_service.postgres import Database
from video_service.postgres.execution import Execution
from video_service.postgres.model_roles import ModelRoles

from .operator import runtime_components
from .server import load_bootstrap


class ToolServer(ThreadingHTTPServer):
    def __init__(self, address, bridge, token, *, role="transcription"):
        if role not in {"transcription", "translation", "vocalization"}:
            raise ValueError("unsupported_role_tool")
        route = {
            "transcription": "/speech",
            "translation": "/translate",
            "vocalization": "/vocal",
        }[role]
        invoke = {
            "transcription": bridge.invoke,
            "translation": bridge.invoke_translation,
            "vocalization": bridge.invoke_vocalization,
        }[role]
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("scoped_tool_token_required")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                if self.path not in {
                    route,
                    route + "/storage-lease",
                } or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + token
                ):
                    self.send_error(403)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 3 * 1024 * 1024:
                        raise ValueError()
                    payload = json.loads(self.rfile.read(size))
                    if self.path == route + "/storage-lease":
                        from video_service.role_storage_leases import RoleStorageLeases

                        reply = RoleStorageLeases(bridge.roles, role).grant(payload)
                    else:
                        reply = invoke(payload)
                except Exception:
                    body = b'{"error":"scoped_call_held"}'
                    status = 409
                else:
                    body = canonical(reply)
                    status = 200
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        super().__init__(address, Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ["bootstrap-file", "token-file", "cert-file", "key-file"]:
        parser.add_argument("--" + arg, required=True)
    parser.add_argument(
        "--role",
        choices=["transcription", "translation", "vocalization"],
        default="transcription",
    )
    parser.add_argument("--port", type=int, default=8444)
    parser.add_argument("--chunk-concurrency", type=int, default=1)
    parser.add_argument("--enable-nonpaid-models", action="store_true")
    args = parser.parse_args(argv)
    try:
        config, dsn = load_bootstrap(args.bootstrap_file)
        database = Database(dsn)
        store, _credentials, factory = runtime_components(
            database,
            config,
            enable_broker=True,
            enable_registered=True,
            enable_nonpaid=args.enable_nonpaid_models,
        )
        runtime = Execution(
            database,
            store,
            transcription_runtime=factory.transcription_runtime,
            translation_runtime=factory.translation_runtime,
            vocalization_runtime=factory.vocalization_runtime,
        )
        bridge = RoleToolBridge(
            ModelRoles(
                runtime, result_store=factory.model_role_result_stores[args.role]
            ),
            chunk_concurrency=args.chunk_concurrency,
        )
        server = ToolServer(
            ("0.0.0.0", args.port),
            bridge,
            Path(args.token_file).read_text().strip(),
            role=args.role,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert_file, args.key_file)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        for sig in [signal.SIGTERM, signal.SIGINT]:
            signal.signal(
                sig,
                lambda *_: threading.Thread(
                    target=server.shutdown, daemon=True
                ).start(),
            )
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            server.server_close()
        return 0
    except Exception:
        print('{"status":"failed","error":"private_role_tool_startup_or_runtime"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
