"""Server-side ingestion of events PUSHED by the dfai traders.

Conforms to the Telegram/Discord delivery model: the trader opens an **outbound**
connection to Hermes and POSTs structured events — Hermes never dials into the
trader, so no inbound port is exposed on the trading host (firewall-safe). The
gateway's HTTP surface (``gateway/platforms/x402_intel.py``) accepts
``POST /v1/dfy/ingest`` with a shared bearer token and calls :func:`apply_event`
to fold each event into the :class:`dfy_intel.store.DfyIntelStore` the oracle reads.

Event envelope (one JSON object per POST)::

    {"kind": "<event kind>", "data": {...}, "ts": "<iso8601>", "bot": "<bot_name>"}

Kinds (mirrors the trader-side pushers):
  trade_event / entry / entry_fill / exit / exit_fill / entry_cancel / exit_cancel
  indicator_digest        — per-pair latest indicators + RL action digest
  open_trades             — full open-trades snapshot
  whitelist | runner | status
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TRADE_KINDS = {"trade_event", "entry", "entry_fill", "exit", "exit_fill", "entry_cancel", "exit_cancel"}
_EXIT_KINDS = {"exit", "exit_fill"}

# Lightweight freshness tracking so the oracle can say "live" vs "corpus-only".
_last_event_at: Dict[str, Any] = {"ts": None, "kind": None, "count": 0, "bot": None}
_last_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def ingest_token() -> str:
    return (os.getenv("HERMES_INGEST_TOKEN") or "").strip()


def verify_ingest_token(provided: Optional[str]) -> bool:
    """Constant-time compare of the bearer token. When no token is configured,
    ingestion is refused (fail closed) rather than left open."""
    expected = ingest_token()
    if not expected:
        return False
    if not provided:
        return False
    provided = provided.strip()
    if provided.lower().startswith("bearer "):
        provided = provided[7:].strip()
    return hmac.compare_digest(provided, expected)


# ---------------------------------------------------------------------------
# Folding
# ---------------------------------------------------------------------------


def feed_freshness() -> Dict[str, Any]:
    with _last_lock:
        ts = _last_event_at["ts"]
        out = dict(_last_event_at)
    out["live"] = ts is not None
    if ts:
        try:
            age = time.time() - datetime.fromisoformat(ts).timestamp()
            out["age_seconds"] = round(age, 1)
        except Exception:
            pass
    return out


def _mark(kind: str, bot: Optional[str]) -> None:
    with _last_lock:
        _last_event_at["ts"] = _now()
        _last_event_at["kind"] = kind
        _last_event_at["bot"] = bot
        _last_event_at["count"] = int(_last_event_at.get("count") or 0) + 1


def apply_event(kind: str, data: Any, *, bot: Optional[str] = None, store=None) -> None:
    """Fold one pushed event into the DFY store. Best-effort; never raises."""
    if store is None:
        from dfy_intel.store import get_dfy_store
        store = get_dfy_store()
    kind = (kind or "").strip()
    try:
        if kind in _TRADE_KINDS:
            _apply_trade_event(store, kind, data or {}, bot)
        elif kind == "indicator_digest":
            _apply_indicator_digest(store, data or {})
        elif kind == "open_trades":
            _apply_open_trades(store, data)
        elif kind == "whitelist":
            if isinstance(data, list):
                store.patch_mechanisms({"whitelist": data, "whitelist_updated": _now()})
        elif kind in ("runner", "status"):
            if isinstance(data, dict):
                store.patch_mechanisms({"runner": {**(store.get_mechanisms().get("runner") or {}), **data}})
        else:
            logger.debug("dfy ingest: unknown kind %s", kind)
            return
        _mark(kind, bot)
        ts_val = (data or {}).get("ts") if isinstance(data, dict) else None
        logger.info(
            "dfy ingest folded: kind=%s bot=%s ts=%s",
            kind,
            bot or "unknown",
            ts_val or _last_event_at.get("ts"),
        )
        # Broadcast to any connected SSE subscribers (non-blocking, best-effort).
        try:
            from dfy_intel import broadcaster
            broadcaster.publish(kind, bot, data)
        except Exception:
            pass
    except Exception as exc:
        logger.debug("dfy ingest apply %s: %s", kind, exc)


def _apply_trade_event(store, kind: str, data: Dict[str, Any], bot: Optional[str]) -> None:
    direction = data.get("direction")
    item = {
        "type": "trade_exit" if kind in _EXIT_KINDS else kind,
        "ts": data.get("ts") or _now(),
        "trade_id": data.get("trade_id"),
        "pair": data.get("pair"),
        "direction": direction,
        "bot": bot,
        "source": "push",
    }
    if kind in _EXIT_KINDS:
        item["exit_reason"] = data.get("exit_reason") or "unknown"
        item["profit_ratio"] = data.get("profit_ratio")
        item["profit_amount"] = data.get("profit_amount")
        item["close_rate"] = data.get("close_rate")
        item["is_final_exit"] = data.get("is_final_exit")
    else:
        item["open_rate"] = data.get("open_rate")
        item["stake_amount"] = data.get("stake_amount")
        item["enter_tag"] = data.get("enter_tag")
    store.append_activity(item)

    # Per-exit-reason attribution (the v7.04 left-tail vector source), folded
    # server-side now that the trader only pushes raw fills.
    if kind == "exit_fill":
        _fold_attribution(store, data.get("exit_reason") or "unknown",
                          float(data.get("profit_ratio") or 0.0))


def _fold_attribution(store, reason: str, r: float) -> None:
    cap = int(os.getenv("DFY_INGEST_ATTR_CAP", "500"))
    mech = store.get_mechanisms()
    existing = mech.get("exit_attribution") or {}
    bucket = existing.get(reason) or {"n": 0, "sum_r": 0.0, "samples": []}
    bucket["n"] += 1
    bucket["sum_r"] += r
    bucket["mean_r"] = bucket["sum_r"] / bucket["n"]
    bucket["samples"] = (list(bucket.get("samples") or []) + [r])[-cap:]
    store.patch_mechanisms({"exit_attribution": {**existing, reason: bucket}})


def _apply_indicator_digest(store, data: Dict[str, Any]) -> None:
    pair = data.get("pair")
    if not pair:
        return
    values = data.get("values") if isinstance(data.get("values"), dict) else {}
    store.set_pair_latest_indicators(pair, {
        "timeframe": data.get("timeframe"),
        "candle_time": data.get("candle_time"),
        "values": values,
        "source": "push",
    })
    store.append_signal({
        "type": "indicator_digest",
        "pair": pair,
        "timeframe": data.get("timeframe"),
        "ts": data.get("ts") or _now(),
        "digest": data.get("digest") or {},
        "column_count": data.get("column_count", len(values)),
        "source": "push",
    })


def _apply_open_trades(store, data: Any) -> None:
    rows = data.get("rows") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return
    store.patch_mechanisms({"open_trades": rows, "open_trades_updated": _now()})
