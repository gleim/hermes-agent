"""Shared DFY ingest fold for api_server and x402_intel.

``index_event`` is handled in Hermes (stream=index) and never passed to
``dfy_intel.ingest.apply_event``, so it cannot land in desk / brief / posture.
Trader kinds still go through dfy_intel when that extra is installed.

Token checks are Hermes-local (``HERMES_INGEST_TOKEN``) so an index_event
batch can land even when ``dfy_intel`` is missing. Hermes being 502 must
not be required for Discord — the watcher posts both transports itself.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from gateway.dfy_index_events import (
    INDEX_EVENT_KIND,
    IndexEventRejected,
    apply_index_event,
)

logger = logging.getLogger(__name__)


def ingest_token() -> str:
    return (os.getenv("HERMES_INGEST_TOKEN") or "").strip()


def verify_ingest_token(authorization: Optional[str]) -> bool:
    expected = ingest_token()
    if not expected:
        return False
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw:
        return False
    try:
        return hmac.compare_digest(raw.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return False


def ingest_auth_error(authorization: Optional[str]) -> Optional[Tuple[Dict[str, Any], int]]:
    """Return ``(body, status)`` when ingest must not proceed, else ``None``."""
    if not ingest_token():
        return {"error": "ingest disabled: set HERMES_INGEST_TOKEN"}, 503
    if not verify_ingest_token(authorization):
        return {"error": "unauthorized"}, 401
    return None


def _event_list(body: Any) -> List[Dict[str, Any]]:
    if isinstance(body, dict) and isinstance(body.get("events"), list):
        return [ev for ev in body["events"] if isinstance(ev, dict)]
    if isinstance(body, dict):
        return [body]
    return []


def fold_ingest_events(body: Any) -> Dict[str, Any]:
    """Apply a single event or ``{"events": [...]}`` batch.

    ``index_event`` is stored locally. Other kinds require ``dfy_intel``.
    A batch that is only index events succeeds without the dfy extra.
    """
    events = _event_list(body)
    ingested = 0
    index_accepted = 0
    rejected: List[Dict[str, Any]] = []
    trader: List[Dict[str, Any]] = []

    for ev in events:
        kind = ev.get("kind")
        if kind == INDEX_EVENT_KIND:
            try:
                row = apply_index_event(ev.get("data"), bot=ev.get("bot"), event=ev)
            except IndexEventRejected as exc:
                rejected.append({"kind": INDEX_EVENT_KIND, "reason": str(exc)})
                continue
            ingested += 1
            if row is not None:
                index_accepted += 1
            continue
        trader.append(ev)

    intel_error = None
    if trader:
        try:
            from gateway.dfy_access import ensure_dfy_intel

            ensure_dfy_intel()
            from dfy_intel.ingest import apply_event  # type: ignore[unresolved-import]
        except Exception as exc:
            intel_error = f"{type(exc).__name__}: {exc}"
            for ev in trader:
                rejected.append(
                    {
                        "kind": ev.get("kind"),
                        "reason": intel_error,
                    }
                )
        else:
            for ev in trader:
                try:
                    apply_event(ev.get("kind"), ev.get("data"), bot=ev.get("bot"))
                    ingested += 1
                except Exception as exc:
                    logger.exception("dfy ingest apply_event failed")
                    rejected.append(
                        {
                            "kind": ev.get("kind"),
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    )

    result: Dict[str, Any] = {
        "ok": True,
        "ingested": ingested,
        "index_events": index_accepted,
        "stream": "index" if index_accepted and not trader else None,
    }
    if rejected:
        result["rejected"] = rejected
    if intel_error and not ingested:
        result["ok"] = False
        result["error"] = "dfy_intel_not_installed"
    # Drop empty stream marker
    if result.get("stream") is None:
        result.pop("stream", None)
    return result
