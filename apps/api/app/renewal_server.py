"""Explicit loopback renewal launcher; never migrates or consumes a queue."""

import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn-env", required=True)
    storage = parser.add_mutually_exclusive_group(required=True)
    storage.add_argument("--content-root")
    storage.add_argument("--object-config-env")
    parser.add_argument("--agent-config-env")
    parser.add_argument("--origin", required=True)
    parser.add_argument("--allow-cpu", action="store_true")
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if (
        origin.scheme != "http"
        or origin.hostname not in ("127.0.0.1", "localhost")
        or not origin.port
        or origin.path
        or origin.query
        or origin.fragment
        or origin.username
    ):
        parser.error(
            "This launcher accepts an explicit HTTP loopback origin only; production deployment is separate."
        )
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        parser.error("The named DSN environment is not set (value is never logged).")
    import uvicorn
    from starlette.staticfiles import StaticFiles
    from video_service.content_store import ContentStore
    from video_service.postgres import Database

    from app.renewal import create_app

    executor = None
    if args.object_config_env:
        import json

        from video_service.object_store import from_config

        store = from_config(json.loads(os.environ[args.object_config_env]))
        if args.allow_cpu and not args.agent_config_env:
            parser.error(
                "Object execution requires an independent explicit agent config"
            )
        if args.agent_config_env:
            from video_service.object_agent import ObjectAgentExecutor

            executor = ObjectAgentExecutor(args.agent_config_env, environ=os.environ)
    else:
        if args.agent_config_env:
            parser.error("Object agent config requires object storage")
        store = ContentStore(args.content_root)
    app = create_app(
        Database(dsn),
        allowed_origins=(args.origin,),
        secure_cookies=False,
        content_store=store,
        local_execution=args.allow_cpu,
        agent_executor=executor,
    )
    bundle = Path(__file__).resolve().parents[2] / "web" / "dist"
    if bundle.is_dir():
        app.mount("/", StaticFiles(directory=bundle, html=True))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=origin.port,
        access_log=False,
        proxy_headers=False,
        log_level="warning",
        reload=False,
    )


if __name__ == "__main__":
    main()
