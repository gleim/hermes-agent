"""Read-the-tape helpers for the DFY / datafi.live "Live" surface.

New users auditing a ticker for the first time, or reading a promo on X, hit a
terse status line ("the tape") that carries a lot of meaning in very little
text, e.g.::

    GM! tape, standard.

    HYPE1D is the live card: last-action +0.413 / c0.58, long. Still open,
    1D exit in ~15h. Current print 0.634.

    Core 1D held. HYPE90M 0.553, held. Measurement is public. Method stays
    private. Not investment advice.
    datafi.live

That density is great for regulars and cryptic for everyone else. This module
is the Hermes-side, dependency-free home for three things that make the tape
approachable without changing what the desk publishes:

* ``TAPE_GLOSSARY`` / :func:`render_legend` — the "How to Read the Tape" guide
  the Live page renders (served unpaid at ``GET /v1/dfy/legend``).
* :func:`parse_tape` / :func:`translate_tape` — turn a tape line (or a
  structured card dict) into a relatable, plain-English explanation
  ("read-the-tape translation").
* ``GROK_PERSONA`` / :func:`wrap_persona` / :func:`render_persona` — a
  consistent, friendly voice for the ``@datafi_live`` grok bot, with the
  standing transparency + "not investment advice" framing.

The ``@datafi_live`` X (grok) bot runs as an **external service**, so it does
not import this module — it consumes the pieces over HTTP from the x402
gateway: ``GET /v1/dfy/persona`` (the personality wrapper + glossary to ground
its own generation), ``GET|POST /v1/dfy/translate`` (deterministic
read-the-tape translation), and ``GET /v1/dfy/legend`` (the guide). In-process
callers (the gateway, CLI, tests) can still import these helpers directly.

Design note: this module deliberately does NOT import the private ``dfy_intel``
package. :func:`parse_tape` works on the public tape text, and
:func:`translate_tape` works on either that parse or a structured card dict, so
it is safe to import wherever needed, regardless of whether the paid feed is
installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

__all__ = [
    "LIVE_LINK",
    "DISCLAIMER",
    "TAPE_GLOSSARY",
    "LEGEND_VERSION",
    "TapeCard",
    "humanize_horizon",
    "split_symbol_horizon",
    "parse_tape",
    "translate_tape",
    "render_legend",
    "read_the_tape",
    "GROK_PERSONA",
    "wrap_persona",
    "render_persona",
]

LIVE_LINK = "datafi.live"
DISCLAIMER = "Not investment advice."
LEGEND_VERSION = "1"

# Horizon codes seen on the tape → human phrasing. Anything not listed is
# decoded generically by :func:`humanize_horizon` (e.g. "45M" → "45-minute").
_HORIZON_UNITS = {"M": "minute", "H": "hour", "D": "day", "W": "week"}

# ---------------------------------------------------------------------------
# Glossary — the canonical "How to Read the Tape" content (single source of
# truth for the endpoint, the docs, and the persona wrapper).
# ---------------------------------------------------------------------------

TAPE_GLOSSARY: List[Dict[str, str]] = [
    {
        "token": "GM! tape, <variant>",
        "example": "GM! tape, standard.",
        "meaning": (
            "The opening line. 'GM' is just 'good morning'. 'tape' means this is a "
            "routine status post; the variant (e.g. 'standard') says which cadence "
            "of update you're looking at."
        ),
    },
    {
        "token": "<SYMBOL><HORIZON>",
        "example": "HYPE1D",
        "meaning": (
            "A card id: the ticker followed by its time horizon. 'HYPE1D' is HYPE on "
            "the 1-day horizon; 'HYPE90M' is HYPE on the 90-minute horizon."
        ),
    },
    {
        "token": "live card",
        "example": "HYPE1D is the live card",
        "meaning": "The single card the desk is featuring right now — the headline read.",
    },
    {
        "token": "last-action",
        "example": "last-action +0.413",
        "meaning": (
            "The measured result since the most recent action on this card. Positive "
            "is in the read's favor, negative is against it. It is a measurement, not "
            "a promised return."
        ),
    },
    {
        "token": "c<0-1>",
        "example": "c0.58",
        "meaning": (
            "Confidence in the read, on a 0-to-1 scale. 0.58 is moderate conviction; "
            "closer to 1 is stronger, closer to 0 is weaker."
        ),
    },
    {
        "token": "long / short",
        "example": "long",
        "meaning": (
            "The direction of the read. 'long' expects the price to rise; 'short' "
            "expects it to fall."
        ),
    },
    {
        "token": "Still open / closed",
        "example": "Still open",
        "meaning": "Whether the tracked position is currently active or already exited.",
    },
    {
        "token": "<HORIZON> exit in ~<time>",
        "example": "1D exit in ~15h",
        "meaning": (
            "When the horizon-based exit is scheduled. '1D exit in ~15h' means the "
            "1-day card is set to close in about 15 hours."
        ),
    },
    {
        "token": "Current print",
        "example": "Current print 0.634",
        "meaning": "The latest live value of the measure for this card, as of the post.",
    },
    {
        "token": "Core <HORIZON> held",
        "example": "Core 1D held",
        "meaning": (
            "The anchor (primary) horizon read did not change at the last check — "
            "'held' means kept as-is, versus flipped (reversed) or cut (closed)."
        ),
    },
    {
        "token": "<SYMBOL><HORIZON> <value>, held",
        "example": "HYPE90M 0.553, held",
        "meaning": (
            "A secondary read: the same ticker on another horizon, its current value, "
            "and whether it held / flipped / cut."
        ),
    },
    {
        "token": "Measurement is public. Method stays private.",
        "example": "Measurement is public. Method stays private.",
        "meaning": (
            "The transparency policy: the desk publishes the numbers it measures, but "
            "not the strategy that produces them."
        ),
    },
    {
        "token": DISCLAIMER,
        "example": DISCLAIMER,
        "meaning": "A standing disclaimer — the tape is information, not a recommendation.",
    },
    {
        "token": LIVE_LINK,
        "example": LIVE_LINK,
        "meaning": "Where to see the live cards and the full tape.",
    },
]

LEGEND_INTRO = (
    "The tape is a short status line the desk posts for each live card. It packs "
    "the ticker, its time horizon, the direction and confidence of the read, "
    "whether the position is open, when it exits, and the latest value — into a "
    "few characters. Here is what each piece means."
)


# ---------------------------------------------------------------------------
# Structured card
# ---------------------------------------------------------------------------


@dataclass
class TapeCard:
    """A structured view of a tape card.

    Every field is optional so the same shape works for a fully-specified card
    coming from the feed and for a best-effort :func:`parse_tape` of a raw post.
    """

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
        known = {f for f in cls().to_dict()}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# ---------------------------------------------------------------------------
# Horizon helpers
# ---------------------------------------------------------------------------


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


def split_symbol_horizon(code: Optional[str]) -> "tuple[Optional[str], Optional[str]]":
    """Split a card id like 'HYPE1D' into ('HYPE', '1D'). Best effort."""
    if not code:
        return (None, None)
    m = re.fullmatch(r"\s*([A-Za-z]+)(\d+[MHDWmhdw])\s*", str(code))
    if not m:
        return (str(code).strip() or None, None)
    return (m.group(1).upper(), m.group(2).upper())


# ---------------------------------------------------------------------------
# Parsing raw tape text
# ---------------------------------------------------------------------------

_RE_VARIANT = re.compile(r"\btape\s*,\s*([A-Za-z][A-Za-z0-9_-]*)", re.IGNORECASE)
_RE_LIVE_CARD = re.compile(r"\b([A-Za-z]+\d+[MHDWmhdw])\b\s+is the live card", re.IGNORECASE)
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
    r"\b([A-Za-z]+\d+[MHDWmhdw])\s+(\d*\.?\d+)\s*,\s*(held|flipped|cut)\b", re.IGNORECASE
)


def parse_tape(text: str) -> TapeCard:
    """Best-effort parse of a raw tape post into a :class:`TapeCard`.

    Tolerant by design: unknown or missing fields simply stay ``None`` rather
    than raising, so a partial or slightly reworded tape still yields whatever
    can be recovered.
    """
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
# Translation — cryptic tape → relatable plain English
# ---------------------------------------------------------------------------


def _confidence_band(c: float) -> str:
    if c < 0.4:
        return "low"
    if c < 0.6:
        return "moderate"
    if c < 0.8:
        return "solid"
    return "high"


def _state_phrase(state: Optional[str]) -> str:
    return {
        "held": "unchanged (held)",
        "flipped": "reversed (flipped)",
        "cut": "closed out (cut)",
    }.get((state or "").lower(), state or "")


def _side_phrase(side: Optional[str]) -> str:
    return {
        "long": "long (expecting the price to rise)",
        "short": "short (expecting the price to fall)",
    }.get((side or "").lower(), side or "")


def translate_tape(source: Union[str, Dict[str, Any], TapeCard]) -> str:
    """Turn a tape post (or a structured card) into plain-English prose.

    Accepts a raw tape string, a card ``dict``, or a :class:`TapeCard`.
    """
    if isinstance(source, str):
        card = parse_tape(source)
    elif isinstance(source, TapeCard):
        card = source
    else:
        card = TapeCard.from_dict(source or {})

    parts: List[str] = []

    if card.variant:
        parts.append(
            f"Good morning — this is the {card.variant} tape, a routine status update."
        )
    else:
        parts.append("Here's the tape in plain English.")

    if card.symbol and card.horizon:
        parts.append(
            f"The featured card right now is {card.symbol} on the "
            f"{humanize_horizon(card.horizon)} horizon."
        )
    elif card.symbol:
        parts.append(f"The featured card right now is {card.symbol}.")

    if card.last_action_move is not None or card.side or card.confidence is not None:
        bits: List[str] = []
        if card.last_action_move is not None:
            bits.append(
                f"since the last action it's measured {card.last_action_move:+g}"
            )
        if card.confidence is not None:
            bits.append(
                f"confidence is {card.confidence:g} out of 1 "
                f"({_confidence_band(card.confidence)})"
            )
        if card.side:
            bits.append(f"the read is {_side_phrase(card.side)}")
        if bits:
            parts.append(_join_clause(bits) + ".")

    if card.open is True:
        if card.exit_horizon and card.exit_in:
            parts.append(
                f"The position is still open, with the {humanize_horizon(card.exit_horizon)} "
                f"exit about {_humanize_duration(card.exit_in)} away."
            )
        else:
            parts.append("The position is still open.")
    elif card.open is False:
        parts.append("The position is already closed.")

    if card.current_print is not None:
        sym = card.symbol or "It"
        parts.append(f"{sym} is currently printing {card.current_print:g}.")

    if card.core_horizon and card.core_state:
        parts.append(
            f"The anchor {humanize_horizon(card.core_horizon)} read is "
            f"{_state_phrase(card.core_state)}."
        )

    for sec in card.secondary:
        sym = sec.get("symbol") or ""
        hz = humanize_horizon(sec.get("horizon"))
        val = sec.get("print")
        state = _state_phrase(sec.get("state"))
        where = f"{sym} on the {hz} horizon" if (sym and hz) else (sym or hz or "another read")
        tail = f" at {val:g}" if isinstance(val, (int, float)) else ""
        state_tail = f", {state}" if state else ""
        parts.append(f"We're also tracking {where}{tail}{state_tail}.")

    if card.measurement_public or card.method_private:
        parts.append("The desk publishes the measurements but keeps the method private.")

    footer = DISCLAIMER
    if card.link:
        footer += f" More at {card.link}."
    parts.append(footer)

    return " ".join(p for p in parts if p)


def _join_clause(bits: List[str]) -> str:
    """Join clauses into one sentence: 'a, b, and c' with a leading cap."""
    if not bits:
        return ""
    if len(bits) == 1:
        text = bits[0]
    else:
        text = ", ".join(bits[:-1]) + f", and {bits[-1]}"
    return text[0].upper() + text[1:]


def _humanize_duration(raw: str) -> str:
    """'15h' → 'about 15 hours', '90m' → '90 minutes', '2d' → '2 days'."""
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


# ---------------------------------------------------------------------------
# Legend rendering — the "How to Read the Tape" guide
# ---------------------------------------------------------------------------


def render_legend(fmt: str = "json") -> Union[Dict[str, Any], str]:
    """Render the guide.

    ``fmt``:
      * ``"json"`` (default) — a dict with ``version``, ``intro``, ``glossary``,
        and pre-rendered ``markdown``/``text`` (handy for a single fetch).
      * ``"markdown"`` — a Markdown document (str).
      * ``"text"`` — a plain-text document (str).
    """
    fmt = (fmt or "json").lower()
    if fmt == "markdown":
        return _legend_markdown()
    if fmt == "text":
        return _legend_text()
    return {
        "version": LEGEND_VERSION,
        "title": "How to Read the Tape",
        "intro": LEGEND_INTRO,
        "glossary": [dict(entry) for entry in TAPE_GLOSSARY],
        "markdown": _legend_markdown(),
        "text": _legend_text(),
        "disclaimer": DISCLAIMER,
        "link": LIVE_LINK,
    }


def _legend_markdown() -> str:
    lines = ["# How to Read the Tape", "", LEGEND_INTRO, "", "| On the tape | Example | What it means |", "| --- | --- | --- |"]
    for e in TAPE_GLOSSARY:
        token = e["token"].replace("|", r"\|")
        example = e["example"].replace("|", r"\|")
        meaning = e["meaning"].replace("|", r"\|")
        lines.append(f"| `{token}` | `{example}` | {meaning} |")
    lines += ["", f"_{DISCLAIMER} See {LIVE_LINK}._"]
    return "\n".join(lines)


def _legend_text() -> str:
    lines = ["How to Read the Tape", "", LEGEND_INTRO, ""]
    for e in TAPE_GLOSSARY:
        lines.append(f"- {e['token']}  (e.g. {e['example']})")
        lines.append(f"    {e['meaning']}")
    lines += ["", f"{DISCLAIMER} See {LIVE_LINK}."]
    return "\n".join(lines)


def read_the_tape(text: str) -> Dict[str, Any]:
    """Convenience bundle for a "what does this mean?" reply: the original tape,
    its structured decode, and the plain-English translation.
    """
    card = parse_tape(text)
    return {
        "tape": text,
        "decoded": card.to_dict(),
        "translation": translate_tape(card),
    }


# ---------------------------------------------------------------------------
# Grok bot personality wrapper
# ---------------------------------------------------------------------------

GROK_PERSONA = """\
You are the voice of @datafi_live — a calm, plain-spoken trading-desk friend, not a hype account.

Audience: many readers are seeing the "tape" for the first time and find it cryptic. Your job is to make it relatable without dumbing it down or overpromising.

Voice:
- Warm, concise, grounded. Sound like a knowledgeable friend explaining what a status line means, not a salesperson.
- The FIRST time a piece of jargon appears in a message, decode it inline in a few words (e.g. "long (betting price rises)", "c0.58 = 0.58 confidence out of 1").
- Prefer everyday words over desk shorthand. Keep it short enough for X.

Hard rules:
- Never promise or imply returns. The tape reports measurements, not outcomes. "last-action +0.413" is a measured result, not a guarantee.
- Never reveal or speculate about the method/strategy. Only the measurements are public; the method stays private. If asked how it works, say exactly that.
- Do not give personalized financial advice. Every public lead ends with "Not investment advice." and, when natural, points to datafi.live.
- Never invent numbers. Only restate values that appear in the tape or card you were given.

When someone is confused by a tape, translate it into one relatable paragraph, then (if it helps) point them to the "How to Read the Tape" guide.\
"""


def wrap_persona(
    source: Union[str, Dict[str, Any], TapeCard],
    *,
    style: str = "lead",
) -> str:
    """Produce a relatable, on-persona message for the grok bot.

    ``style``:
      * ``"lead"`` — a first-touch/promo lead: a short relatable hook, the
        plain-English translation, then the standing footer.
      * ``"reply"`` — an answer to "what does this mean?": the translation plus
        a pointer to the full guide.
      * ``"plain"`` — just the translation (no hook), still on-voice.
    """
    style = (style or "lead").lower()
    translation = translate_tape(source)

    if style == "plain":
        return translation

    if style == "reply":
        return (
            f"{translation}\n\n"
            "Want the full key? Here's how to read the tape: "
            f"{LIVE_LINK}"
        )

    # lead
    return (
        "New here? Here's the tape in plain English:\n\n"
        f"{translation}"
    )


def render_persona() -> Dict[str, Any]:
    """Everything the external ``@datafi_live`` grok bot needs to adopt the
    voice: the persona system prompt, the tape glossary (to ground its own
    jargon-decoding), and the standing framing. Served at GET /v1/dfy/persona.
    """
    return {
        "version": LEGEND_VERSION,
        "persona": GROK_PERSONA,
        "glossary": [dict(entry) for entry in TAPE_GLOSSARY],
        "disclaimer": DISCLAIMER,
        "link": LIVE_LINK,
    }
