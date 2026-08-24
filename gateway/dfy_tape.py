"""Read-the-tape guide for first-time Live readers and the external grok bot.

A first-time reader auditing a ticker, or opening a promo on X, hits a terse
status line ("the tape")::

    GM! tape, standard.

    HYPE1D is the live card: last-action +0.413 / c0.58, long. Still open,
    1D exit in ~15h. Current print 0.634.

    Core 1D held. HYPE90M 0.553, held. Measurement is public. Method stays
    private. Not investment advice.
    datafi.live

This module is the Hermes-side, dependency-free home for that first exposure:

* :func:`render_tape_guide` / :func:`render_tape_guide_html` — the public
  "How to read the tape" document. Browsers get HTML; machines get JSON.
  Served unpaid at ``GET /v1/dfy/tape-guide`` on the api_server host
  (``hermes.datadefi.ai``) and on the x402 gateway.
* :func:`parse_tape` / :func:`translate_tape` — decode a tape line or card
  into house-accurate plain English (print vs signed, both-bars event, held).
* :func:`render_persona` / :func:`wrap_persona` — the personality wrapper the
  **external** ``@datafi_live`` grok bot fetches over HTTP.

The X bot does not import this module. It consumes ``/v1/dfy/tape-guide``,
``/v1/dfy/persona``, and ``/v1/dfy/translate``. This module does not import
the private ``dfy_intel`` package.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

__all__ = [
    "LIVE_LINK",
    "LIVE_URL",
    "SOUL_URL",
    "SKILLS_URL",
    "DISCLAIMER",
    "TAPE_GLOSSARY",
    "LEGEND_VERSION",
    "EXAMPLE_TAPE",
    "TapeCard",
    "humanize_horizon",
    "split_symbol_horizon",
    "parse_tape",
    "translate_tape",
    "render_legend",
    "render_tape_guide",
    "render_tape_guide_html",
    "negotiate_tape_guide",
    "serve_tape_guide",
    "read_the_tape",
    "GROK_PERSONA",
    "wrap_persona",
    "render_persona",
]

LIVE_LINK = "datafi.live"
LIVE_URL = "https://datafi.live/live"
SOUL_URL = "https://datafi.live/soul.md"
SKILLS_URL = "https://datafi.live/skills.md"
DISCLAIMER = "Not investment advice."
LEGEND_VERSION = "2"

_HORIZON_UNITS = {"M": "minute", "H": "hour", "D": "day", "W": "week"}

TICKER_NAMES = {
    "HYPE": "Hyperliquid",
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "GOLD": "gold",
    "SILVER": "silver",
    "CL": "crude",
}

EXAMPLE_TAPE = (
    "GM! tape, standard.\n\n"
    "HYPE1D is the live card: last-action +0.413 / c0.58, long. Still open, "
    "1D exit in ~15h. Current print 0.634.\n\n"
    "Core 1D held. HYPE90M 0.553, held. Measurement is public. Method stays "
    "private. Not investment advice.\n"
    "datafi.live"
)

LEDE = (
    "The Live page is a probability-density tape under the GM! Index — not a "
    "price chart and not a trade ticket. One name can be live. The rest stay "
    "held. Measurement is public. Method stays private."
)

# House glossary. Keys match the live /v1/dfy/tape-guide contract
# (term / example / plain). token / meaning are aliases for older callers.
TAPE_GLOSSARY: List[Dict[str, str]] = [
    {
        "term": "ticker + horizon",
        "example": "HYPE1D, BTC90M, XYZ-GOLD1D",
        "plain": (
            "The name plus the clock. HYPE1D is Hyperliquid on the one-day book. "
            "BTC90M is Bitcoin on the ninety-minute book. XYZ- prefixes are listed "
            "metals/energy names on the same 1D book."
        ),
    },
    {
        "term": "print",
        "example": "Current print 0.634",
        "plain": (
            "The unsigned conviction number, always in [0, 1]. 0.5 is even. Above "
            "0.5 leans long; below 0.5 leans short. This series does not jump when "
            "an event fires."
        ),
    },
    {
        "term": "signed",
        "example": "last-action +0.413",
        "plain": (
            "The print rewritten as a lean: (print − 0.5) × 2. Zero is even. "
            "Positive is long; negative is short. +0.413 is a clear long lean, not "
            "a price and not a return."
        ),
    },
    {
        "term": "conf / c0.58",
        "example": "c0.58",
        "plain": (
            "Confidence on that same reading, 0 to 1. A large lean with weak "
            "confidence is not an event. A confident whisper is not an event. Both "
            "bars have to clear."
        ),
    },
    {
        "term": "live card / last-action",
        "example": "HYPE1D is the live card",
        "plain": (
            "The one name that currently cleared both bars on the selected rung. "
            "Last-action is the signed / conf / side from that fire. Other names "
            "stay held until they clear too."
        ),
    },
    {
        "term": "held",
        "example": "Core 1D held",
        "plain": (
            "Quiet on that book — neither bar cleared. Held is information, not a "
            "broken feed and not a sell. Blue cells on the Live page are held."
        ),
    },
    {
        "term": "open / exit in ~15h",
        "example": "Still open, 1D exit in ~15h",
        "plain": (
            "The event is still inside its horizon clock. A 1D event expires at the "
            "one-day bar, not when the print wiggles. ~15h left means the claim is "
            "still live."
        ),
    },
    {
        "term": "rung",
        "example": "tape, standard",
        "plain": (
            "Which frozen card is reading the same print. Purist fires least "
            "(strongest lean). Standard is the house default. Active fires earliest. "
            "Prefer standard unless the caller asked otherwise."
        ),
    },
    {
        "term": "GM! Core / GM! Crypto",
        "example": "Core 1D · Crypto 90M",
        "plain": (
            "Two published baskets under the GM! Index flagship. Core is the 1D book "
            "(BTC, ETH, HYPE, GOLD, SILVER, CL). Crypto is the 90M book (BTC, ETH, HYPE)."
        ),
    },
    {
        "term": "Measurement is public. Method stays private.",
        "example": "house closer",
        "plain": (
            "You can see the numbers. We do not publish how the unsigned series is "
            "built. Not investment advice. Not a trade. Not a return."
        ),
    },
]

for _entry in TAPE_GLOSSARY:
    _entry.setdefault("token", _entry["term"])
    _entry.setdefault("meaning", _entry["plain"])

NOT_LIST = [
    "Not a buy or sell.",
    "Not a return, yield, or PnL.",
    "Not the information coefficient.",
    "Not a second index you invent a tighter cutoff on.",
]

GUIDE_CANONICAL = "https://hermes.datadefi.ai/v1/dfy/tape-guide"

GROK_PERSONA = """\
You are the DataFi tape clerk — the public voice that translates the GM! Index for someone who just tapped a promo on X or opened a ticker for the first time.

Voice
- Plain first, jargon second. Lead with the name and the clock, not the house telegram.
- Warm, brief, street-desk. No hype-bro, no "GM! tape, standard." as an opener for first-timers.
- One screen of prose. Then the glossary terms in the same breath if they help.
- Never invent method, omega, IC, PnL, yield, buy/sell, or MutantDeFi-as-a-fact.
- Always close public reads with: measurement is public, method stays private, not investment advice.

What the tape is
- DataFi is the brand. GM! Index is the current flagship. The tape is a probability density under that flagship — not a price forecast and not a return.
- A print is the unsigned number in [0, 1]. 0.5 is even. Signed is (print − 0.5) × 2.
- An event fires only when |signed| ≥ band AND confidence ≥ min_conf on a frozen card. One bar is not enough.
- Held is a quiet book, not a broken feed.
- Prefer the standard rung unless the caller asked for purist or active.

How to answer
1. If they paste a cryptic blurb, call dfy_tape_guide with that text (or translate it yourself using the same glossary).
2. Fetch https://datafi.live/soul.md and https://datafi.live/skills.md when you need current cards, mint, or house identity. Do not keep a stale copy.
3. Cite https://datafi.live/live for the public tape. Do not dump narrator paragraphs or desk internals onto the Live page.
4. Do not impersonate DataDeFi (datadefi.ai). Do not tell humans to use slash commands.
5. If they ask how the numbers are built, refuse the method and point at the public measurement.

Translate this shape of promo:
"HYPE1D is the live card: last-action +0.413 / c0.58, long. Still open, 1D exit in ~15h. Current print 0.634."
→ "Hyperliquid just cleared the one-day card — that's the only live read right now. When it fired, lean was +0.413 long at 0.58 confidence. About 15 hours left on that claim. The tape now reads 0.634."
"""

# Editorial walkthrough on the HTML face. Machines still get translate_tape().
WORKED_EXAMPLE_PLAIN = (
    "Good morning — this is the GM! Index tape on the house-default standard card.\n\n"
    "Hyperliquid on the one-day book is the only name that currently cleared both bars. "
    "When that event fired, the lean was +0.413 (long) with 0.58 confidence. That claim "
    "is still open: about 15 hours left on the one-day clock. The unsigned print right "
    "now is 0.634 (above 0.5 still leans long).\n\n"
    "The rest of the one-day book is held — quiet, not broken. The same name on the "
    "ninety-minute book is also held; its print is 0.553.\n\n"
    "You can see the numbers. We don't publish how they're made. This is not a trade "
    "recommendation."
)

WALK_ROWS = [
    (
        "HYPE1D",
        "Hyperliquid on the one-day book — the name plus the clock.",
    ),
    (
        "last-action +0.413 / c0.58, long",
        "When it fired: lean +0.413 long at 0.58 confidence. Both bars cleared, so this is the live card — not a price and not a return.",
    ),
    (
        "Still open, 1D exit in ~15h",
        "The claim is still inside its one-day clock. About 15 hours left. The print wiggling does not end it.",
    ),
    (
        "Current print 0.634",
        "Unsigned conviction now, always in [0, 1]. 0.5 is even; 0.634 still leans long. This series does not jump when an event fires.",
    ),
    (
        "Core 1D held · HYPE90M 0.553, held",
        "Quiet books. Held is information — not a broken feed and not a sell. Blue cells on Live are held.",
    ),
]


# ---------------------------------------------------------------------------
# Structured card
# ---------------------------------------------------------------------------


@dataclass
class TapeCard:
    """A structured view of a tape card. All fields optional (tolerant parse)."""

    variant: Optional[str] = None
    symbol: Optional[str] = None
    horizon: Optional[str] = None
    last_action_move: Optional[float] = None
    confidence: Optional[float] = None
    side: Optional[str] = None
    open: Optional[bool] = None
    exit_horizon: Optional[str] = None
    exit_in: Optional[str] = None
    current_print: Optional[float] = None
    core_horizon: Optional[str] = None
    core_state: Optional[str] = None
    secondary: List[Dict[str, Any]] = field(default_factory=list)
    measurement_public: bool = False
    method_private: bool = False
    link: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant": self.variant,
            "symbol": self.symbol,
            "horizon": self.horizon,
            "last_action_move": self.last_action_move,
            "confidence": self.confidence,
            "side": self.side,
            "open": self.open,
            "exit_horizon": self.exit_horizon,
            "exit_in": self.exit_in,
            "current_print": self.current_print,
            "core_horizon": self.core_horizon,
            "core_state": self.core_state,
            "secondary": list(self.secondary),
            "measurement_public": self.measurement_public,
            "method_private": self.method_private,
            "link": self.link,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TapeCard":
        known = set(cls().to_dict())
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# ---------------------------------------------------------------------------
# Horizon / name helpers
# ---------------------------------------------------------------------------


_HORIZON_PHRASE = {
    "1D": "one-day",
    "90M": "ninety-minute",
    "4H": "four-hour",
    "2W": "two-week",
}


def humanize_horizon(code: Optional[str]) -> Optional[str]:
    """Turn a horizon code like '1D' or '90M' into '1-day' / '90-minute'."""
    if not code:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*([MHDWmhdw])\s*", str(code))
    if not m:
        return str(code).strip() or None
    n, unit = m.group(1), m.group(2).upper()
    word = _HORIZON_UNITS.get(unit, unit.lower())
    return f"{int(n)}-{word}"


def horizon_phrase(code: Optional[str]) -> Optional[str]:
    """House phrasing: '1D' → 'one-day', else fall back to humanize_horizon."""
    if not code:
        return None
    key = str(code).strip().upper()
    return _HORIZON_PHRASE.get(key) or humanize_horizon(key)


def display_name(symbol: Optional[str]) -> Optional[str]:
    """House name for a ticker ('HYPE' → 'Hyperliquid'), else the ticker."""
    if not symbol:
        return None
    key = str(symbol).upper().removeprefix("XYZ-")
    return TICKER_NAMES.get(key, key)


def split_symbol_horizon(code: Optional[str]) -> "tuple[Optional[str], Optional[str]]":
    """Split a card id like 'HYPE1D' or 'XYZ-GOLD1D' into (symbol, horizon)."""
    if not code:
        return (None, None)
    m = re.fullmatch(r"\s*([A-Za-z]+(?:-[A-Za-z]+)?)\s*(\d+[MHDWmhdw])\s*", str(code))
    if not m:
        return (str(code).strip() or None, None)
    return (m.group(1).upper(), m.group(2).upper())


# ---------------------------------------------------------------------------
# Parsing raw tape text
# ---------------------------------------------------------------------------

_RE_VARIANT = re.compile(r"\btape\s*,\s*([A-Za-z][A-Za-z0-9_-]*)", re.IGNORECASE)
_RE_LIVE_CARD = re.compile(
    r"\b([A-Za-z]+(?:-[A-Za-z]+)?\d+[MHDWmhdw])\b\s+is the live card", re.IGNORECASE
)
_RE_LAST_ACTION = re.compile(
    r"last-action\s*([+-]?\d*\.?\d+)\s*/\s*c\s*(\d*\.?\d+)\s*,\s*(long|short)",
    re.IGNORECASE,
)
_RE_EXIT = re.compile(
    r"\b(\d+[MHDWmhdw])\s+exit\s+in\s*~?\s*([0-9]+\s*[A-Za-z]+)", re.IGNORECASE
)
_RE_PRINT = re.compile(r"current\s+print\s*([+-]?\d*\.?\d+)", re.IGNORECASE)
_RE_CORE = re.compile(r"\bcore\s+(\d+[MHDWmhdw])\s+(held|flipped|cut)\b", re.IGNORECASE)
_RE_SECONDARY = re.compile(
    r"\b([A-Za-z]+(?:-[A-Za-z]+)?\d+[MHDWmhdw])\s+(\d*\.?\d+)\s*,\s*(held|flipped|cut)\b",
    re.IGNORECASE,
)


def parse_tape(text: str) -> TapeCard:
    """Best-effort parse of a raw tape post into a :class:`TapeCard`."""
    card = TapeCard()
    if not text:
        return card
    s = str(text)

    m = _RE_VARIANT.search(s)
    if m:
        card.variant = m.group(1).lower()

    m = _RE_LIVE_CARD.search(s)
    if m:
        card.symbol, card.horizon = split_symbol_horizon(m.group(1))

    m = _RE_LAST_ACTION.search(s)
    if m:
        card.last_action_move = float(m.group(1))
        card.confidence = float(m.group(2))
        card.side = m.group(3).lower()

    if re.search(r"\bstill\s+open\b", s, re.IGNORECASE):
        card.open = True
    elif re.search(r"\bclosed\b", s, re.IGNORECASE):
        card.open = False

    m = _RE_EXIT.search(s)
    if m:
        card.exit_horizon = m.group(1).upper()
        card.exit_in = re.sub(r"\s+", "", m.group(2))

    m = _RE_PRINT.search(s)
    if m:
        card.current_print = float(m.group(1))

    m = _RE_CORE.search(s)
    if m:
        card.core_horizon = m.group(1).upper()
        card.core_state = m.group(2).lower()

    for sym_code, value, state in _RE_SECONDARY.findall(s):
        symbol, horizon = split_symbol_horizon(sym_code)
        card.secondary.append(
            {
                "symbol": symbol,
                "horizon": horizon,
                "print": float(value),
                "state": state.lower(),
            }
        )

    card.measurement_public = bool(re.search(r"measurement\s+is\s+public", s, re.IGNORECASE))
    card.method_private = bool(re.search(r"method\s+stays\s+private", s, re.IGNORECASE))
    if re.search(re.escape(LIVE_LINK), s, re.IGNORECASE):
        card.link = LIVE_LINK
    return card


# ---------------------------------------------------------------------------
# Translation — house-accurate plain English
# ---------------------------------------------------------------------------


def _confidence_band(c: float) -> str:
    if c < 0.4:
        return "low"
    if c < 0.6:
        return "moderate"
    if c < 0.8:
        return "solid"
    return "high"


def _humanize_duration(raw: str) -> str:
    m = re.fullmatch(r"\s*(\d+)\s*([A-Za-z]+)\s*", str(raw or ""))
    if not m:
        return str(raw or "").strip()
    n = int(m.group(1))
    unit = m.group(2).lower()
    words = {"h": "hour", "hr": "hour", "m": "minute", "min": "minute", "d": "day", "w": "week"}
    word = words.get(unit, unit)
    if not word.endswith("s") and n != 1:
        word += "s"
    return f"{n} {word}"


def _as_card(source: Union[str, Dict[str, Any], TapeCard]) -> TapeCard:
    if isinstance(source, str):
        return parse_tape(source)
    if isinstance(source, TapeCard):
        return source
    return TapeCard.from_dict(source or {})


def _exit_hours(card: TapeCard) -> Optional[int]:
    raw = card.exit_in or ""
    m = re.fullmatch(r"\s*(\d+)\s*h\s*", raw, re.I)
    return int(m.group(1)) if m else None


def translate_tape(source: Union[str, Dict[str, Any], TapeCard]) -> str:
    """Turn a tape post (or a structured card) into house-accurate prose.

    Print is unsigned conviction in [0, 1]. last-action is the signed lean
    (print − 0.5) × 2, not a return. Held is a quiet book, not a sell.
    """
    card = _as_card(source)

    parts: List[str] = []
    name = display_name(card.symbol) or card.symbol
    clock = horizon_phrase(card.horizon)

    if card.variant == "standard":
        parts.append(
            "This is the GM! Index tape on the standard card (house default is standard)."
        )
    elif card.variant:
        parts.append(f"This is the GM! Index tape on the {card.variant} card.")
    else:
        parts.append("Here's the tape in plain English.")

    if name and clock:
        parts.append(
            f"{name} on the {clock} book is the only name that currently cleared both bars "
            "— that's the live card."
        )
    elif name:
        parts.append(f"{name} is the live card right now.")

    if card.last_action_move is not None and card.side and card.confidence is not None:
        parts.append(
            f"When that event fired, the lean was {card.last_action_move:+g} "
            f"({card.side}) with {card.confidence:g} confidence."
        )
    elif card.last_action_move is not None or card.side or card.confidence is not None:
        bits = []
        if card.last_action_move is not None:
            bits.append(f"lean {card.last_action_move:+g}")
        if card.side:
            bits.append(card.side)
        if card.confidence is not None:
            bits.append(
                f"{card.confidence:g} confidence ({_confidence_band(card.confidence)})"
            )
        parts.append("When that event fired, " + ", ".join(bits) + ".")

    if card.open is True:
        if card.exit_in:
            parts.append(
                f"That claim is still open — about {_humanize_duration(card.exit_in)} "
                "left on the horizon clock."
            )
        else:
            parts.append("That claim is still open.")
    elif card.open is False:
        parts.append("That claim has already expired.")

    if card.current_print is not None:
        if card.current_print > 0.5:
            hint = "above 0.5 leans long"
        elif card.current_print < 0.5:
            hint = "below 0.5 leans short"
        else:
            hint = "even"
        parts.append(f"The unsigned print right now is {card.current_print:g} ({hint}).")

    held: List[str] = []
    if card.core_horizon and card.core_state == "held":
        held.append(f"Core {card.core_horizon}")
    elif card.core_horizon and card.core_state:
        parts.append(
            f"The rest of the {horizon_phrase(card.core_horizon)} book is {card.core_state}."
        )
    for sec in card.secondary:
        if sec.get("state") == "held" and sec.get("symbol") and sec.get("horizon"):
            held.append(f"{sec['symbol']}{sec['horizon']}")
        elif sec.get("state"):
            sec_name = display_name(sec.get("symbol")) or sec.get("symbol") or "another name"
            hz = horizon_phrase(sec.get("horizon"))
            where = f"{sec_name} on the {hz} book" if hz else sec_name
            val = sec.get("print")
            extra = f" at {val:g}" if isinstance(val, (int, float)) else ""
            parts.append(f"{where} is {sec['state']}{extra}.")
    if held:
        parts.append(
            "Held names are quiet on that book — not a broken feed and not a sell: "
            + ", ".join(held)
            + "."
        )

    parts.append(
        "You can see the numbers. We don't publish how they're made. " + DISCLAIMER
    )
    return " ".join(p for p in parts if p)


def read_the_tape(text: str) -> Dict[str, Any]:
    """Original tape + structured decode + plain-English translation."""
    card = parse_tape(text)
    d = card.to_dict()
    return {
        "tape": text,
        "decoded": d,
        "translation": translate_tape(card),
        "source": text,
        "tickers": _tickers_from_card(card),
        "rung": card.variant,
        "live_card": f"{card.symbol}{card.horizon}" if card.symbol and card.horizon else None,
        "side": card.side,
        "last_action": (
            {"signed": f"{card.last_action_move:+g}", "conf": f"{card.confidence:g}"}
            if card.last_action_move is not None and card.confidence is not None
            else None
        ),
        "print": card.current_print,
        "exit_hours": _exit_hours(card),
        "plain": translate_tape(card),
    }


def _tickers_from_card(card: TapeCard) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if card.symbol and card.horizon:
        out.append(
            {"symbol": card.symbol, "horizon": card.horizon, "cell": f"{card.symbol}{card.horizon}"}
        )
    for sec in card.secondary:
        if sec.get("symbol") and sec.get("horizon"):
            out.append(
                {
                    "symbol": sec["symbol"],
                    "horizon": sec["horizon"],
                    "cell": f"{sec['symbol']}{sec['horizon']}",
                }
            )
    return out


# ---------------------------------------------------------------------------
# Guide rendering — JSON for machines, HTML for first-time readers
# ---------------------------------------------------------------------------


def render_tape_guide() -> Dict[str, Any]:
    """Machine JSON for /v1/dfy/tape-guide — matches the live contract."""
    translation = read_the_tape(EXAMPLE_TAPE)
    return {
        "title": "How to read the tape",
        "lede": LEDE,
        "live_url": LIVE_URL,
        "soul_url": SOUL_URL,
        "skills_url": SKILLS_URL,
        "glossary": [
            {"term": e["term"], "example": e["example"], "plain": e["plain"]}
            for e in TAPE_GLOSSARY
        ],
        "worked_example": {
            "cryptic": EXAMPLE_TAPE,
            "plain": WORKED_EXAMPLE_PLAIN,
        },
        "translation": {
            "source": translation["source"],
            "tickers": translation["tickers"],
            "rung": translation["rung"],
            "live_card": translation["live_card"],
            "side": translation["side"],
            "last_action": translation["last_action"],
            "print": translation["print"],
            "exit_hours": translation["exit_hours"],
            "held": ["Core 1D", "HYPE90M"],
            "plain": translation["plain"],
        },
        "personality": {
            "name": "datafi",
            "system_prompt": GROK_PERSONA,
        },
        "not": list(NOT_LIST),
        "version": LEGEND_VERSION,
        "disclaimer": DISCLAIMER,
        "link": LIVE_LINK,
    }


_GUIDE_CSS = """
:root {
  --bg: #05070b;
  --panel: #0b1018;
  --ink: #e8eef6;
  --muted: #8b97a8;
  --line: #1c2533;
  --accent: #3dffc8;
  --accent-2: #5b8cff;
  --warn: #f4d35e;
  --mono: "IBM Plex Mono", "Geist Mono", ui-monospace, SFMono-Regular, monospace;
  --sans: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--ink);
  font: 17px/1.55 var(--sans); }
body {
  min-height: 100vh;
  background:
    radial-gradient(1200px 500px at 10% -10%, rgba(61,255,200,.08), transparent 50%),
    radial-gradient(900px 400px at 90% 0, rgba(91,140,255,.10), transparent 45%),
    var(--bg);
}
a { color: var(--accent); }
.nav {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  padding: .85rem 1.25rem; border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 20;
  background: rgba(5,7,11,.86); backdrop-filter: blur(12px);
}
.brand { font: 800 .78rem/1 var(--sans); letter-spacing: .14em; text-decoration: none;
  color: var(--ink); }
.brand small { color: var(--muted); font-weight: 600; margin-left: .4rem; }
.nav-links { display: flex; gap: 1rem; font: 600 .72rem/1 var(--sans); letter-spacing: .08em; }
.nav-links a { color: var(--muted); text-decoration: none; }
.nav-links a:hover, .nav-links a[aria-current="page"] { color: var(--ink); }
main { max-width: 42rem; margin: 0 auto; padding: 2.4rem 1.25rem 5rem; }
.kicker { font: 600 .72rem/1.2 var(--sans); letter-spacing: .14em; text-transform: uppercase;
  color: var(--accent); margin: 0 0 .7rem; }
h1 { font: 600 2rem/1.2 var(--sans); margin: 0 0 .9rem; letter-spacing: -0.02em; }
.lede { font-size: 1.08rem; color: var(--muted); margin: 0 0 2rem; }
h2 { font: 600 .72rem/1.3 var(--sans); letter-spacing: .12em; text-transform: uppercase;
  color: var(--accent-2); margin: 2.3rem 0 .75rem; }
.cryptic {
  margin: 0 0 1.2rem; padding: 1rem 1.1rem; background: var(--panel);
  border: 1px solid var(--line); border-left: 3px solid var(--accent);
  white-space: pre-wrap; font: 0.86rem/1.5 var(--mono); color: var(--ink);
}
.plain { white-space: pre-wrap; margin: 0 0 1.4rem; color: var(--ink); }
.walk { margin: 0; border: 1px solid var(--line); background: var(--panel); }
.walk .row { display: grid; grid-template-columns: minmax(9rem, 0.9fr) 1.3fr;
  gap: .85rem 1.1rem; padding: .9rem 1rem; border-top: 1px solid var(--line); }
.walk .row:first-child { border-top: 0; }
.walk .saw { font: 0.8rem/1.45 var(--mono); color: var(--accent); margin: 0; }
.walk .means { margin: 0; color: var(--ink); font-size: .95rem; }
.bars { display: grid; grid-template-columns: 1fr auto 1fr; gap: .75rem; align-items: start;
  margin: 0 0 .8rem; }
.bar { background: var(--panel); border: 1px solid var(--line); padding: .85rem 1rem; }
.bar .label { font: 600 .72rem/1.2 var(--mono); letter-spacing: .06em; color: var(--accent);
  text-transform: uppercase; margin: 0 0 .35rem; }
.bar p { margin: 0; color: var(--muted); font-size: .92rem; }
.and { align-self: center; font: 700 .72rem/1 var(--sans); letter-spacing: .1em; color: var(--warn); }
.bars-note { color: var(--muted); margin: 0; }
dl.words { margin: 0; }
dl.words dt { font: 600 .95rem/1.3 var(--sans); margin: 1rem 0 .2rem; }
dl.words dt:first-child { margin-top: 0; }
dl.words .ex { display: block; font: 0.78rem/1.4 var(--mono); color: var(--muted); font-weight: 400; }
dl.words dd { margin: 0; color: var(--muted); }
ul.not { margin: 0; padding-left: 1.15rem; color: var(--muted); }
ul.not li { margin: .3rem 0; }
.site-footer { margin-top: 2.6rem; padding-top: 1.1rem; border-top: 1px solid var(--line);
  font: 0.86rem/1.55 var(--sans); color: var(--muted); }
.site-footer nav { display: flex; flex-wrap: wrap; gap: .35rem 1rem; margin-bottom: .7rem; }
.site-footer a { color: var(--accent); text-decoration: none; }
.site-footer a:hover { text-decoration: underline; }
@media (max-width: 640px) {
  h1 { font-size: 1.55rem; }
  .walk .row { grid-template-columns: 1fr; gap: .3rem; }
  .bars { grid-template-columns: 1fr; }
  .and { text-align: left; }
}
"""


def render_tape_guide_html() -> str:
    """First-reader HTML for a browser opening /v1/dfy/tape-guide."""
    guide = render_tape_guide()
    words = []
    for e in guide["glossary"]:
        words.append(
            f"<dt>{html.escape(e['term'])}"
            f"<span class='ex'>{html.escape(e['example'])}</span></dt>"
            f"<dd>{html.escape(e['plain'])}</dd>"
        )
    rows = []
    for saw, means in WALK_ROWS:
        rows.append(
            "<div class='row'>"
            f"<p class='saw'>{html.escape(saw)}</p>"
            f"<p class='means'>{html.escape(means)}</p>"
            "</div>"
        )
    nots = "".join(f"<li>{html.escape(n)}</li>" for n in guide["not"])
    cryptic = html.escape(guide["worked_example"]["cryptic"])
    plain = html.escape(guide["worked_example"]["plain"])
    lede = html.escape(guide["lede"])
    live = html.escape(LIVE_URL)
    soul = html.escape(SOUL_URL)
    skills = html.escape(SKILLS_URL)
    canon = html.escape(GUIDE_CANONICAL)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>How to read the tape · DataFi</title>\n"
        f'<meta name="description" content="{lede}">\n'
        f'<link rel="canonical" href="{canon}">\n'
        f'<meta property="og:title" content="How to read the tape · DataFi">\n'
        f'<meta property="og:description" content="{lede}">\n'
        f'<meta property="og:url" content="{canon}">\n'
        '<meta property="og:type" content="article">\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700'
        '&amp;family=IBM+Plex+Sans:wght@400;500;600&amp;display=swap" rel="stylesheet">\n'
        f"<style>{_GUIDE_CSS}</style>\n"
        "</head>\n<body>\n"
        '<header class="nav">'
        f'<a class="brand" href="{live}">DATAFI <small>GM!</small></a>'
        '<nav class="nav-links" aria-label="House">'
        f'<a href="{live}">LIVE</a>'
        f'<a href="{soul}">SOUL</a>'
        f'<a href="{skills}">SKILLS</a>'
        '<a href="?format=json" title="Machine JSON">JSON</a>'
        "</nav></header>\n"
        "<main>\n"
        '<p class="kicker">How to read the tape</p>\n'
        "<h1>One name can be live. The rest stay held.</h1>\n"
        f'<p class="lede">{lede}</p>\n'
        "<h2>A promo you might see</h2>\n"
        f'<blockquote class="cryptic">{cryptic}</blockquote>\n'
        "<h2>Walk it</h2>\n"
        f'<div class="walk">{"".join(rows)}</div>\n'
        "<h2>What that means</h2>\n"
        f'<p class="plain">{plain}</p>\n'
        "<h2>Both bars have to clear</h2>\n"
        '<div class="bars">'
        '<div class="bar"><p class="label">|signed| ≥ band</p>'
        "<p>How far the print sits from even. Signed is (print − 0.5) × 2. "
        "Zero is even. Positive is long; negative is short.</p></div>"
        '<div class="and">AND</div>'
        '<div class="bar"><p class="label">confidence ≥ min_conf</p>'
        "<p>How sure that same reading is, 0 to 1. A large lean with weak "
        "confidence is not an event. A confident whisper is not an event.</p></div>"
        "</div>\n"
        '<p class="bars-note">One bar is not enough. Quiet windows are a held book, '
        "not a broken feed. Prefer the standard rung unless you asked for purist or "
        "active.</p>\n"
        "<h2>The words</h2>\n"
        f'<dl class="words">{"".join(words)}</dl>\n'
        "<h2>This is not</h2>\n"
        f'<ul class="not">{nots}</ul>\n'
        "</main>\n"
        '<footer class="site-footer"><nav>'
        f'<a href="{live}">See the live tape</a>'
        f'<a href="{soul}">House identity</a>'
        f'<a href="{skills}">Mint and checkout</a>'
        '<a href="?format=json">JSON for machines</a>'
        "</nav>"
        "<p>Measurement is public. Method stays private. "
        f"{html.escape(DISCLAIMER)}</p>"
        "</footer>\n"
        "</body>\n</html>\n"
    )


def _legend_markdown() -> str:
    lines = [
        "# How to read the tape",
        "",
        LEDE,
        "",
        "## A promo you might see",
        "",
        "```",
        EXAMPLE_TAPE,
        "```",
        "",
        "## What that means",
        "",
        translate_tape(EXAMPLE_TAPE),
        "",
        "## The words",
        "",
    ]
    for e in TAPE_GLOSSARY:
        lines.append(f"**{e['term']}** — `{e['example']}`")
        lines.append(f": {e['plain']}")
        lines.append("")
    lines += ["## This is not", ""]
    for n in NOT_LIST:
        lines.append(f"- {n}")
    lines += ["", f"See {LIVE_URL}. {DISCLAIMER}"]
    return "\n".join(lines)


def _legend_text() -> str:
    lines = ["How to read the tape", "", LEDE, "", "A promo you might see", "", EXAMPLE_TAPE, "", "What that means", "", translate_tape(EXAMPLE_TAPE), "", "The words", ""]
    for e in TAPE_GLOSSARY:
        lines.append(f"- {e['term']}  (e.g. {e['example']})")
        lines.append(f"    {e['plain']}")
    lines += ["", "This is not"]
    for n in NOT_LIST:
        lines.append(f"- {n}")
    lines += ["", f"See {LIVE_URL}. {DISCLAIMER}"]
    return "\n".join(lines)


def render_legend(fmt: str = "json") -> Union[Dict[str, Any], str]:
    """Compat wrapper. Prefer :func:`render_tape_guide` / HTML for first readers."""
    fmt = (fmt or "json").lower()
    if fmt == "markdown":
        return _legend_markdown()
    if fmt == "text":
        return _legend_text()
    if fmt == "html":
        return render_tape_guide_html()
    guide = render_tape_guide()
    guide["markdown"] = _legend_markdown()
    guide["text"] = _legend_text()
    guide["intro"] = LEDE
    return guide


def negotiate_tape_guide(accept: str = "", fmt: str = "") -> Tuple[str, str]:
    """Pick a representation for /v1/dfy/tape-guide.

    Query ``format=`` wins. Otherwise a browser ``Accept: text/html`` gets the
    first-reader HTML page; everyone else gets the machine JSON.
    """
    fmt = (fmt or "").strip().lower()
    accept = (accept or "").lower()
    if not fmt:
        # Prefer HTML only when the client actually asked for a document.
        html_q = "text/html" in accept
        json_q = "application/json" in accept
        if html_q and not (json_q and accept.find("application/json") < accept.find("text/html")):
            fmt = "html"
        else:
            fmt = "json"
    if fmt == "html":
        return render_tape_guide_html(), "text/html; charset=utf-8"
    if fmt == "markdown":
        return _legend_markdown(), "text/markdown; charset=utf-8"
    if fmt == "text":
        return _legend_text(), "text/plain; charset=utf-8"
    return json.dumps(render_tape_guide(), ensure_ascii=False), "application/json; charset=utf-8"


def serve_tape_guide(accept: str = "", fmt: str = "") -> Tuple[str, str]:
    """Never-500 wrapper for the public tape-guide route."""
    try:
        return negotiate_tape_guide(accept, fmt)
    except Exception:
        return (
            json.dumps(render_tape_guide(), ensure_ascii=False),
            "application/json; charset=utf-8",
        )


# ---------------------------------------------------------------------------
# Persona wrapper (external grok bot)
# ---------------------------------------------------------------------------


def wrap_persona(
    source: Union[str, Dict[str, Any], TapeCard],
    *,
    style: str = "lead",
) -> str:
    """On-persona message. Lead with the name and the clock, not the telegram."""
    style = (style or "lead").lower()
    translation = translate_tape(source)
    if style == "plain":
        return translation
    if style == "reply":
        return (
            f"{translation}\n\nThe full key is on the tape guide. Live tape: {LIVE_URL}"
        )
    return translation


def render_persona() -> Dict[str, Any]:
    """Payload the external grok bot fetches at GET /v1/dfy/persona."""
    return {
        "version": LEGEND_VERSION,
        "persona": GROK_PERSONA,
        "system_prompt": GROK_PERSONA,
        "name": "datafi",
        "glossary": [
            {"term": e["term"], "example": e["example"], "plain": e["plain"]}
            for e in TAPE_GLOSSARY
        ],
        "disclaimer": DISCLAIMER,
        "link": LIVE_LINK,
        "live_url": LIVE_URL,
        "soul_url": SOUL_URL,
        "skills_url": SKILLS_URL,
    }
