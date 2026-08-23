"""Hermes consumer for FCI ``index_event`` ingest.

The watcher (dfy_iq) is the writer: it emits one fact bundle + one dense
paragraph on a live-print edge. Hermes is a pipe + journal. Events land on
the existing ``POST /v1/dfy/ingest`` envelope (same ``HERMES_INGEST_TOKEN``)
and are stored under stream label ``index`` — never folded into desk /
``brief_view`` / trader posture.

Paper overlay / LNFM marks and counsel-sensitive fields are rejected or
stripped here so a noisy producer cannot poison GROUP/COMPUTER citation.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from hermes_constants import get_hermes_home

logger = logging.getLogger(__name__)

INDEX_EVENT_KIND = "index_event"
INDEX_STREAM_LABEL = "index"

# Live-print edges the watcher is allowed to emit. Held is silence, not a post.
ALLOWED_TRANSITIONS = frozenset({"cleared", "expired", "near_miss"})

# Allowed fact keys on the wire. Extra keys are dropped, not stored.
ALLOWED_FACT_KEYS = frozenset(
    {
        "symbol",
        "horizon",
        "side",
        "signed",
        "conf",
        "rung",
        "card",
        "distance_to_band",
        "gap",
        "distance",
        "feed_version",
        "as_of",
        "venue_last_close",
        "source",
        "bookmates",
        "book_held",
        "book_near",
        "transition",
        "bar_close_ts",
        "paragraph",
        "facts",
        "stream",
        "label",
        "card_name",
        "venue",
        "beats",
    }
)

ALLOWED_CARD_KEYS = frozenset({"band", "min_conf", "name", "horizon"})
ALLOWED_SIDES = frozenset({"long", "short"})
ALLOWED_SOURCES = frozenset({"underlying", "live", "index", ""})

# Paper / overlay / LNFM must not fire this journal.
_PAPER_SOURCES = frozenset(
    {"overlay", "lnfm", "paper", "lnfm_overlay", "showcase", "held_showcase"}
)

# Counsel-sensitive / trader-posture keys — never persist, even if sent.
_FORBIDDEN_KEY_RE = re.compile(
    r"(^|_)(ic|pnl|profit|yield|buy|sell|exit_t|exit_time|hash_?walk|mutantdefi)(_|$)",
    re.IGNORECASE,
)
_FORBIDDEN_SUBSTRING_RE = re.compile(r"mutantdefi", re.IGNORECASE)

_MAX_EVENTS = 500
_MAX_PARAGRAPH = 4000

_lock = threading.RLock()
_events: Optional[Deque[Dict[str, Any]]] = None
_dedupe: Optional[set] = None
_subscribers: List[queue.Queue] = []


class IndexEventRejected(ValueError):
    """Raised when an ingest payload must not enter the index journal."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _journal_path() -> Path:
    return get_hermes_home() / "dfy_feed" / "index_events.jsonl"


def reset_index_event_store() -> None:
    """Drop in-memory state (tests). Does not delete the journal file."""
    global _events, _dedupe
    with _lock:
        _events = deque(maxlen=_MAX_EVENTS)
        _dedupe = set()


def _ensure_loaded() -> Tuple[Deque[Dict[str, Any]], set]:
    global _events, _dedupe
    with _lock:
        if _events is not None and _dedupe is not None:
            return _events, _dedupe
        _events = deque(maxlen=_MAX_EVENTS)
        _dedupe = set()
        path = _journal_path()
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(row, dict):
                            continue
                        key = row.get("dedupe_key")
                        if key:
                            if key in _dedupe:
                                continue
                            _dedupe.add(key)
                        _events.append(row)
            except OSError as exc:
                logger.warning("index_event journal unreadable (%s): %s", path, exc)
        return _events, _dedupe


def _append_journal(row: Dict[str, Any]) -> None:
    path = _journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.warning("index_event journal write failed (%s): %s", path, exc)


def subscribe() -> queue.Queue:
    """Subscribe to in-process index_event broadcasts (dashboard / SSE)."""
    q: queue.Queue = queue.Queue(maxsize=256)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def _broadcast(envelope: Dict[str, Any]) -> None:
    line = json.dumps(envelope, ensure_ascii=False, default=str)
    with _lock:
        dead: List[queue.Queue] = []
        for q in _subscribers:
            try:
                q.put_nowait(line)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass
    try:
        from dfy_intel import broadcaster

        for name in ("publish", "broadcast", "emit", "put"):
            fn = getattr(broadcaster, name, None)
            if callable(fn):
                fn(line)
                break
    except Exception:
        pass


def _looks_forbidden_key(name: str) -> bool:
    return bool(_FORBIDDEN_KEY_RE.search(str(name or "")))


def _redact_text(value: Any) -> Any:
    if isinstance(value, str):
        return _FORBIDDEN_SUBSTRING_RE.sub("[redacted]", value)
    return value


def _sanitize_card(card: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(card, dict):
        return None
    out: Dict[str, Any] = {}
    for key, value in card.items():
        if key not in ALLOWED_CARD_KEYS or _looks_forbidden_key(key):
            continue
        out[key] = _redact_text(value)
    return out or None


def _sanitize_bookmates(rows: Any) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item: Dict[str, Any] = {}
        for key in (
            "symbol",
            "horizon",
            "status",
            "signed",
            "conf",
            "distance_to_band",
            "rung",
            "gap",
        ):
            if key in row and not _looks_forbidden_key(key):
                item[key] = _redact_text(row[key])
        if item.get("symbol"):
            out.append(item)
    return out


def _as_data(kind_payload: Any, event: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(kind_payload, dict):
        return dict(kind_payload)
    data = {
        key: value
        for key, value in event.items()
        if key not in {"kind", "bot", "events"}
    }
    return data


def _source_of(data: Dict[str, Any]) -> str:
    raw = data.get("source")
    if raw is None and isinstance(data.get("facts"), dict):
        raw = data["facts"].get("source")
    return str(raw or "").strip().lower()


def _is_paper(data: Dict[str, Any]) -> bool:
    if data.get("paper") or data.get("overlay") or data.get("lnfm"):
        return True
    source = _source_of(data)
    if source in _PAPER_SOURCES:
        return True
    marks = data.get("marks") or data.get("overlay_marks")
    if isinstance(marks, list) and marks:
        return True
    return False


def sanitize_index_event(
    data: Dict[str, Any], *, bot: Optional[str] = None
) -> Dict[str, Any]:
    """Return a journal row, or raise :class:`IndexEventRejected`."""
    if not isinstance(data, dict):
        raise IndexEventRejected("index_event data must be an object")
    if _is_paper(data):
        raise IndexEventRejected("paper/overlay/LNFM marks must not fire index_event")

    facts_in = data.get("facts") if isinstance(data.get("facts"), dict) else {}
    merged: Dict[str, Any] = {}
    merged.update(facts_in)
    merged.update({k: v for k, v in data.items() if k != "facts"})

    for key in list(merged):
        if _looks_forbidden_key(key):
            raise IndexEventRejected(f"forbidden field {key!r}")

    side = str(merged.get("side") or "").strip().lower()
    if side in {"buy", "sell"}:
        raise IndexEventRejected("side must be long/short, not buy/sell")
    if side and side not in ALLOWED_SIDES:
        raise IndexEventRejected(f"unsupported side {side!r}")

    transition = str(merged.get("transition") or "").strip().lower().replace("-", "_")
    if transition == "nearmiss":
        transition = "near_miss"
    if transition and transition not in ALLOWED_TRANSITIONS:
        raise IndexEventRejected(f"unsupported transition {transition!r}")

    source = _source_of(merged)
    if source in _PAPER_SOURCES:
        raise IndexEventRejected("paper/overlay source must not fire index_event")
    if source and source not in ALLOWED_SOURCES:
        # Unknown live sources stay off the journal rather than leaking.
        raise IndexEventRejected(f"unsupported source {source!r}")

    symbol = str(merged.get("symbol") or "").strip().upper()
    if not symbol:
        raise IndexEventRejected("symbol is required")

    rung = str(merged.get("rung") or "").strip().lower()
    bar_close_ts = merged.get("bar_close_ts") or merged.get("as_of") or ""
    dedupe_key = "|".join(
        [
            symbol,
            str(merged.get("horizon") or ""),
            rung,
            transition,
            str(bar_close_ts),
        ]
    )

    card = _sanitize_card(merged.get("card"))
    paragraph = _redact_text(merged.get("paragraph") or "")
    if isinstance(paragraph, str) and len(paragraph) > _MAX_PARAGRAPH:
        paragraph = paragraph[:_MAX_PARAGRAPH]

    facts: Dict[str, Any] = {
        "symbol": symbol,
        "horizon": merged.get("horizon"),
        "side": side or None,
        "signed": merged.get("signed"),
        "conf": merged.get("conf"),
        "rung": rung or None,
        "card": card,
        "distance_to_band": merged.get("distance_to_band", merged.get("gap", merged.get("distance"))),
        "feed_version": merged.get("feed_version"),
        "as_of": merged.get("as_of"),
        "source": source or None,
        "transition": transition or None,
        "bar_close_ts": bar_close_ts or None,
    }
    if source == "underlying" and merged.get("venue_last_close") is not None:
        facts["venue_last_close"] = merged.get("venue_last_close")
        if merged.get("venue"):
            facts["venue"] = _redact_text(merged.get("venue"))

    bookmates = _sanitize_bookmates(merged.get("bookmates"))
    if bookmates:
        facts["bookmates"] = bookmates
    if isinstance(merged.get("book_held"), list):
        facts["book_held"] = [_redact_text(x) for x in merged["book_held"] if x]
    if isinstance(merged.get("book_near"), list):
        facts["book_near"] = [_redact_text(x) for x in merged["book_near"] if x]
    if merged.get("card_name"):
        facts["card_name"] = _redact_text(merged.get("card_name"))
    if merged.get("feed_version"):
        facts["feed_version"] = _redact_text(merged.get("feed_version"))
    if isinstance(merged.get("beats"), dict):
        facts["beats"] = {
            str(k): _redact_text(v)
            for k, v in merged["beats"].items()
            if str(k) in {"from_here", "mechanism", "metric", "constraint", "not_committed"}
        }

    # Drop Nones so the journal stays dense.
    facts = {k: v for k, v in facts.items() if v is not None and v != ""}

    return {
        "kind": INDEX_EVENT_KIND,
        "stream": INDEX_STREAM_LABEL,
        "label": INDEX_STREAM_LABEL,
        "bot": (bot or "fci").strip() or "fci",
        "ts": _now_iso(),
        "dedupe_key": dedupe_key,
        "transition": transition or None,
        "paragraph": paragraph if isinstance(paragraph, str) else "",
        "facts": facts,
        "data": facts,
    }


def apply_index_event(
    data: Any,
    *,
    bot: Optional[str] = None,
    event: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Sanitize, dedupe, persist, and broadcast one index event.

    Returns the stored row, ``None`` on duplicate, or raises
    :class:`IndexEventRejected`.
    """
    payload = _as_data(data, event or {})
    row = sanitize_index_event(payload, bot=bot)
    events, dedupe = _ensure_loaded()
    key = row["dedupe_key"]
    with _lock:
        if key in dedupe:
            return None
        dedupe.add(key)
        events.append(row)
    _append_journal(row)
    _broadcast(
        {
            "kind": INDEX_EVENT_KIND,
            "bot": row["bot"],
            "ts": row["ts"],
            "stream": INDEX_STREAM_LABEL,
            "data": {
                "stream": INDEX_STREAM_LABEL,
                "label": INDEX_STREAM_LABEL,
                "transition": row.get("transition"),
                "paragraph": row.get("paragraph"),
                **row.get("facts", {}),
            },
        }
    )
    return row


def list_index_events(limit: int = 25) -> List[Dict[str, Any]]:
    events, _ = _ensure_loaded()
    limit = max(1, min(int(limit or 25), 200))
    with _lock:
        return list(events)[-limit:]


def index_event_freshness() -> Dict[str, Any]:
    events, _ = _ensure_loaded()
    with _lock:
        if not events:
            return {
                "stream": INDEX_STREAM_LABEL,
                "count": 0,
                "last_ts": None,
                "age_seconds": None,
            }
        last = events[-1]
        last_ts = last.get("ts")
        age = None
        if last_ts:
            try:
                parsed = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
                age = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())
            except ValueError:
                age = None
        return {
            "stream": INDEX_STREAM_LABEL,
            "count": len(events),
            "last_ts": last_ts,
            "age_seconds": age,
            "last_symbol": (last.get("facts") or {}).get("symbol"),
            "last_transition": last.get("transition"),
        }


def citation_payload(limit: int = 8) -> Dict[str, Any]:
    """Shape the agent (GROUP/COMPUTER) can cite without mixing in posture."""
    rows = list_index_events(limit=limit)
    return {
        "stream": INDEX_STREAM_LABEL,
        "label": INDEX_STREAM_LABEL,
        "note": (
            "Information index, not a trade and not a return. "
            "Cite these facts; do not narrate trader posture, IC, or PnL."
        ),
        "freshness": index_event_freshness(),
        "items": [
            {
                "ts": row.get("ts"),
                "transition": row.get("transition"),
                "paragraph": row.get("paragraph"),
                "facts": row.get("facts") or {},
            }
            for row in rows
        ],
    }


def iter_recent(limit: int = 25) -> Iterable[Dict[str, Any]]:
    return list_index_events(limit=limit)
