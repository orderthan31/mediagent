"""Keep SQLite on a local Docker volume when a database directory is configured."""
import hashlib
import os
from pathlib import Path


def database_path(root, name):
    configured = os.getenv('JOB_DATABASE_DIR')
    if not configured:
        return root / f'.{name}.sqlite3'
    directory = Path(configured)
    if not directory.is_absolute():
        raise ValueError('JOB_DATABASE_DIR must be absolute')
    directory.mkdir(parents=True, exist_ok=True)
    namespace = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
    return directory / f'{namespace}-{name}.sqlite3'
