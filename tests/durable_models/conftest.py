"""Source-only tests: no DB, provider, process or operational fixtures."""
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
for folder in ("packages/shared", "agents", "tools/models", "tools/media", "runtime/model-executor/src"):
    sys.path.insert(0, str(ROOT / folder))


def pytest_addoption(parser):
    parser.addoption("--durable-scratch", default=None, help="Explicit root for local durable unit fixtures")


@pytest.fixture
def tmp_path(request):
    # Python 3.14's mode=0700 pytest directory loses the managed runner's ACL.
    # Use normal inherited permissions, exclusively under the authorized scratch.
    root = Path(request.config.getoption("--durable-scratch") or tempfile.gettempdir()) / "durable-fixtures"
    folder = root / uuid4().hex
    folder.mkdir(parents=True)
    return folder
