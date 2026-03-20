"""
Read-only client for the dfai runner REST API (same RPC surface the Telegram UI uses).

Configure with DFY_FT_API_URL (base including /api/v1), DFY_FT_API_USER, DFY_FT_API_PASSWORD.
Does not expose POST control endpoints (force enter/exit, start/stop); use the API or Telegram for those.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


class FtRestError(Exception):
    """Raised when the REST call fails or returns an error payload."""


def _base_url() -> str:
    return os.getenv("DFY_FT_API_URL", "http://127.0.0.1:8080/api/v1").rstrip("/")


def _auth() -> Optional[tuple[str, str]]:
    user = (os.getenv("DFY_FT_API_USER") or "").strip()
    password = (os.getenv("DFY_FT_API_PASSWORD") or "").strip()
    if user:
        return (user, password)
    return None


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise FtRestError("httpx is required for DFY live REST") from exc

    url = f"{_base_url()}{path}"
    auth = _auth()
    try:
        with httpx.Client(timeout=45.0) as client:
            r = client.get(url, auth=auth, params=params or {})
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        if isinstance(exc, FtRestError):
            raise
        raise FtRestError(str(exc)) from exc


# Maps Discord `view` values to (path, param_builder)
def fetch_live(
    view: str,
    *,
    pair: Optional[str] = None,
    timescale: int = 7,
) -> Any:
    v = (view or "").strip().lower()
    ts = max(1, min(int(timescale), 365))

    pair_param: Dict[str, Any] = {}
    if pair and pair.strip():
        pair_param["pair"] = pair.strip()

    if v == "status":
        return _get("/status")
    if v == "profit":
        return _get("/profit")
    if v == "balance":
        return _get("/balance")
    if v == "performance":
        return _get("/performance")
    if v == "trades":
        return _get("/trades")
    if v == "daily":
        return _get("/daily", {"timescale": ts})
    if v == "weekly":
        return _get("/weekly", {"timescale": ts})
    if v == "monthly":
        return _get("/monthly", {"timescale": ts})
    if v == "stats":
        return _get("/stats")
    if v == "count":
        return _get("/count")
    if v == "locks":
        return _get("/locks")
    if v == "health":
        return _get("/health")
    if v == "version":
        return _get("/version")
    if v == "sysinfo":
        return _get("/sysinfo")
    if v == "whitelist":
        return _get("/whitelist")
    if v == "entries":
        return _get("/entries", pair_param if pair_param else None)
    if v == "exits":
        return _get("/exits", pair_param if pair_param else None)
    if v == "mix_tags":
        return _get("/mix_tags", pair_param if pair_param else None)
    if v == "config":
        return _get("/show_config")
    if v == "logs":
        return _get("/logs")

    raise FtRestError(f"unknown view: {view}")
