"""Explicit, repeatable legacy archive import. Defaults to dry-run; no job dispatch."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument("--manifest-file", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.server import load_bootstrap
        from video_service.postgres import Database
        from video_service.postgres.legacy_archive import LegacyArchive

        config, dsn = load_bootstrap(args.bootstrap_file)
        archive = LegacyArchive(Database(dsn))
        manifest = json.loads(Path(args.manifest_file).read_text(encoding="utf-8"))
        result = archive.apply(manifest, dry_run=not args.apply)
        result["summary"] = archive.summary()
        print(json.dumps(result, ensure_ascii=False, default=str))
    except Exception:
        print(
            '{"status":"failed","code":"legacy_archive_import_failed_preserve_source"}'
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
