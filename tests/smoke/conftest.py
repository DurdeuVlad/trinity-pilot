from __future__ import annotations

import sys
from pathlib import Path

SMOKE_DIR = Path(__file__).resolve().parent
if str(SMOKE_DIR) not in sys.path:
    sys.path.insert(0, str(SMOKE_DIR))


def pytest_ignore_collect(collection_path, config):
    if not config.getoption("--real"):
        return True
    return False
