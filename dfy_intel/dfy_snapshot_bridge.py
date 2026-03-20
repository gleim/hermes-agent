"""Read DFY live snapshot file (written by dfai ``dfy_snapshot_io``)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_SNAPSHOT_PATH_ENV = "DFY_INTEL_SNAPSHOT_PATH"


def dfy_snapshot_path() -> Path:
    raw = (os.getenv(_SNAPSHOT_PATH_ENV) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes" / "dfy_feed" / "dfy_live_snapshot.json"


def read_dfy_snapshot() -> Optional[Dict[str, Any]]:
    path = dfy_snapshot_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def dfy_snapshot_mtime() -> Optional[float]:
    path = dfy_snapshot_path()
    try:
        return path.stat().st_mtime
    except OSError:
        return None
