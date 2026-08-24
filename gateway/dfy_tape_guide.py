"""Public "how to read the tape" guide + Grok personality wrapper.

First-time readers hit a cryptic X/Live blurb (``HYPE1D``, ``c0.58``,
``held``) with no semantic hook. This module is the canonical translation
layer for:

* the Live page (``GET /v1/dfy/tape-guide`` — public, no bearer)
* Grok / GROUP / COMPUTER (``dfy_tape_guide`` tool + ``/personality datafi``)

House identity and card numbers still live on ``https://datafi.live/soul.md``.
This file does not republish feed construction.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

HOUSE_SOUL_URL = "https://datafi.live/soul.md"
HOUSE_SKILL_URL = "https://datafi.live/skills.md"
LIVE_URL = "https://datafi.live/live"

# Keep this in lockstep with the Live page glossary. Card *numbers* are not
# the source of truth — fetch soul.md for the current frozen cards.
GLOSSARY: List[Dict[str, str]] = [
    {
        "term": "ticker + horizon",
        "example": "HYPE1D, BTC90M, XYZ-GOLD1D",
        "plain": (
            "The name plus the clock. HYPE1D is Hyperliquid on the one-day "
            "book. BTC90M is Bitcoin on the ninety-minute book. XYZ- prefixes "
            "are listed metals/energy names on the same 1D book."
        ),
    },
    {
        "term": "print",
        "example": "Current print 0.634",
        "plain": (
            "The unsigned conviction number, always in [0, 1]. 0.5 is even. "
            "Above 0.5 leans long; below 0.5 leans short. This series does "
            "not jump when an event fires."
        ),
    },
    {
        "term": "signed",
        "example": "last-action +0.413",
        "plain": (
            "The print rewritten as a lean: (print − 0.5) × 2. Zero is even. "
            "Positive is long; negative is short. +0.413 is a clear long lean, "
            "not a price and not a return."
        ),
    },
    {
        "term": "conf / c0.58",
        "example": "c0.58",
        "plain": (
            "Confidence on that same reading, 0 to 1. A large lean with weak "
            "confidence is not an event. A confident whisper is not an event. "
            "Both bars have to clear."
        ),
    },
    {
        "term": "live card / last-action",
        "example": "HYPE1D is the live card",
        "plain": (
            "The one name that currently cleared both bars on the selected "
            "rung. Last-action is the signed / conf / side from that fire. "
            "Other names stay held until they clear too."
        ),
    },
    {
        "term": "held",
        "example": "Core 1D held",
        "plain": (
            "Quiet on that book — neither bar cleared. Held is information, "
            "not a broken feed and not a sell. Blue cells on the Live page "
            "are held."
        ),
    },
    {
        "term": "open / exit in ~15h",
        "example": "Still open, 1D exit in ~15h",
        "plain": (
            "The event is still inside its horizon clock. A 1D event expires "
            "at the one-day bar, not when the print wiggles. ~15h left means "
            "the claim is still live."
        ),
    },
    {
        "term": "rung",
        "example": "tape, standard",
        "plain": (
            "Which frozen card is reading the same print. Purist fires least "
            "(strongest lean). Standard is the house default. Active fires "
            "earliest. Prefer standard unless the caller asked otherwise."
        ),
    },
    {
        "term": "GM! Core / GM! Crypto",
        "example": "Core 1D · Crypto 90M",
        "plain": (
            "Two published baskets under the GM! Index flagship. Core is the "
            "1D book (BTC, ETH, HYPE, GOLD, SILVER, CL). Crypto is the 90M "
            "book (BTC, ETH, HYPE)."
        ),
    },
    {
        "term": "Measurement is public. Method stays private.",
        "example": "house closer",
        "plain": (
            "You can see the numbers. We do not publish how the unsigned "
            "series is built. Not investment advice. Not a trade. Not a return."
        ),
    },
]

CRYPTIC_DRAFT = (
    "GM! tape, standard.\n"
    "\n"
    "HYPE1D is the live card: last-action +0.413 / c0.58, long. "
    "Still open, 1D exit in ~15h. Current print 0.634.\n"
    "\n"
    "Core 1D held. HYPE90M 0.553, held. "
    "Measurement is public. Method stays private. Not investment advice.\n"
    "datafi.live"
)

PLAIN_DRAFT = (
    "Good morning — this is the GM! Index tape on the house-default "
    "standard card.\n"
    "\n"
    "Hyperliquid on the one-day book is the only name that currently "
    "cleared both bars. When that event fired, the lean was +0.413 "
    "(long) with 0.58 confidence. That claim is still open: about 15 "
    "hours left on the one-day clock. The unsigned print right now is "
    "0.634 (above 0.5 still leans long).\n"
    "\n"
    "The rest of the one-day book is held — quiet, not broken. The same "
    "name on the ninety-minute book is also held; its print is 0.553.\n"
    "\n"
    "You can see the numbers. We don't publish how they're made. "
    "This is not a trade recommendation."
)

GROK_PERSONALITY = """You are the DataFi tape clerk — the public voice that translates the GM! Index for someone who just tapped a promo on X or opened a ticker for the first time.

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

_TICKER_RE = re.compile(
    r"\b((?:XYZ-)?[A-Z]{2,12})(1D|90M|4H)\b"
)
_LAST_ACTION_RE = re.compile(
    r"last-action\s+([+-]?\d+(?:\.\d+)?)\s*/\s*c?(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_PRINT_RE = re.compile(
    r"(?:current\s+)?print\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_EXIT_RE = re.compile(
    r"exit(?:s)?\s+(?:1D|90M|4H)?\s*(?:in\s+)?~?(\d+)\s*h",
    re.IGNORECASE,
)
_RUNG_RE = re.compile(r"\b(purist|standard|active)\b", re.IGNORECASE)
_SIDE_RE = re.compile(r"\b(long|short)\b", re.IGNORECASE)
_HELD_RE = re.compile(
    r"\b((?:Core|Crypto)\s+\d+[A-Z]?|(?:XYZ-)?[A-Z]{2,12}(?:1D|90M|4H)?)\s+.*?held",
    re.IGNORECASE,
)
_LIVE_CARD_RE = re.compile(
    r"\b((?:XYZ-)?[A-Z]{2,12}(?:1D|90M|4H))\s+is the live card",
    re.IGNORECASE,
)

_HORIZON_PLAIN = {
    "1D": "one-day",
    "90M": "ninety-minute",
    "4H": "four-hour",
}

_NAME_PLAIN = {
    "HYPE": "Hyperliquid",
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "GOLD": "gold",
    "SILVER": "silver",
    "CL": "crude",
    "XYZ-GOLD": "gold",
    "XYZ-SILVER": "silver",
    "XYZ-CL": "crude",
}


def _plain_name(symbol: str) -> str:
    return _NAME_PLAIN.get(symbol.upper(), symbol)


def _plain_horizon(horizon: str) -> str:
    return _HORIZON_PLAIN.get(horizon.upper(), horizon)


def translate_tape_blurb(text: str) -> Dict[str, Any]:
    """Best-effort parse of a public tape / X blurb into a plain reading."""
    raw = (text or "").strip()
    tickers = [
        {"symbol": m.group(1), "horizon": m.group(2), "cell": f"{m.group(1)}{m.group(2)}"}
        for m in _TICKER_RE.finditer(raw)
    ]
    last_action = _LAST_ACTION_RE.search(raw)
    print_m = _PRINT_RE.search(raw)
    exit_m = _EXIT_RE.search(raw)
    rung_m = _RUNG_RE.search(raw)
    side_m = _SIDE_RE.search(raw)
    live_m = _LIVE_CARD_RE.search(raw)
    held = [m.group(1).strip() for m in _HELD_RE.finditer(raw)]

    sentences: List[str] = []
    if rung_m:
        sentences.append(
            f"This is the GM! Index tape on the {rung_m.group(1).lower()} card "
            "(house default is standard)."
        )
    if live_m:
        cell = live_m.group(1).upper()
        parsed = _TICKER_RE.search(cell)
        if parsed:
            sentences.append(
                f"{_plain_name(parsed.group(1))} on the "
                f"{_plain_horizon(parsed.group(2))} book is the only name that "
                "currently cleared both bars — that's the live card."
            )
        else:
            sentences.append(f"{cell} is the live card — the only name that currently cleared.")
    if last_action:
        signed = last_action.group(1)
        conf = last_action.group(2)
        if not conf.startswith("0") and "." not in conf:
            conf = f"0.{conf}" if not conf.startswith("0.") else conf
        if conf.startswith("0") and not conf.startswith("0."):
            # c0.58 was split as 0.58 already; c58 → 0.58
            pass
        side = side_m.group(1).lower() if side_m else "that side"
        sentences.append(
            f"When that event fired, the lean was {signed} ({side}) with "
            f"{conf} confidence."
        )
    if exit_m:
        sentences.append(
            f"That claim is still open — about {exit_m.group(1)} hours left "
            "on the horizon clock."
        )
    if print_m:
        value = float(print_m.group(1))
        lean = "long" if value > 0.5 else ("short" if value < 0.5 else "even")
        sentences.append(
            f"The unsigned print right now is {print_m.group(1)} "
            f"({'above 0.5 leans long' if lean == 'long' else 'below 0.5 leans short' if lean == 'short' else 'even at 0.5'})."
        )
    if held:
        sentences.append(
            "Held names are quiet on that book — not a broken feed and not a sell: "
            + ", ".join(held)
            + "."
        )
    if not sentences:
        sentences.append(
            "I couldn't parse a ticker cell from that text. "
            "Ask with a name like HYPE1D plus print / last-action / held."
        )
    sentences.append(
        "You can see the numbers. We don't publish how they're made. "
        "Not investment advice."
    )
    return {
        "source": raw,
        "tickers": tickers,
        "rung": rung_m.group(1).lower() if rung_m else None,
        "live_card": live_m.group(1).upper() if live_m else None,
        "side": side_m.group(1).lower() if side_m else None,
        "last_action": (
            {"signed": last_action.group(1), "conf": last_action.group(2)}
            if last_action
            else None
        ),
        "print": print_m.group(1) if print_m else None,
        "exit_hours": int(exit_m.group(1)) if exit_m else None,
        "held": held,
        "plain": " ".join(sentences),
    }


def grok_personality() -> str:
    return GROK_PERSONALITY


def tape_guide_payload(blurb: Optional[str] = None) -> Dict[str, Any]:
    example_source = blurb.strip() if blurb and blurb.strip() else CRYPTIC_DRAFT
    translated = translate_tape_blurb(example_source)
    return {
        "title": "How to read the tape",
        "lede": (
            "The Live page is a probability-density tape under the GM! Index, "
            "not a price chart and not a trade ticket. One name can be live. "
            "The rest stay held. Measurement is public. Method stays private."
        ),
        "live_url": LIVE_URL,
        "soul_url": HOUSE_SOUL_URL,
        "skills_url": HOUSE_SKILL_URL,
        "glossary": GLOSSARY,
        "worked_example": {
            "cryptic": CRYPTIC_DRAFT,
            "plain": PLAIN_DRAFT,
        },
        "translation": translated,
        "personality": {
            "name": "datafi",
            "system_prompt": GROK_PERSONALITY,
        },
        "not": [
            "Not a buy or sell.",
            "Not a return, yield, or PnL.",
            "Not the information coefficient.",
            "Not a second index you invent a tighter cutoff on.",
        ],
    }


def tape_guide_markdown(blurb: Optional[str] = None) -> str:
    payload = tape_guide_payload(blurb)
    lines = [
        f"# {payload['title']}",
        "",
        payload["lede"],
        "",
        f"Public tape: {payload['live_url']}",
        f"House identity: {payload['soul_url']}",
        "",
        "## Worked example",
        "",
        "Cryptic promo:",
        "",
        "```",
        payload["worked_example"]["cryptic"],
        "```",
        "",
        "Plain reading:",
        "",
        payload["worked_example"]["plain"],
        "",
        "## Glossary",
        "",
    ]
    for row in payload["glossary"]:
        lines.append(f"**{row['term']}** (`{row['example']}`)")
        lines.append(f": {row['plain']}")
        lines.append("")
    lines.extend(
        [
            "## What this is not",
            "",
            *[f"- {item}" for item in payload["not"]],
            "",
            "## Grok / bot voice",
            "",
            "Set `/personality datafi` or send `personality.system_prompt` "
            "from `GET /v1/dfy/tape-guide` as the wrapper.",
            "",
        ]
    )
    if blurb and blurb.strip() and blurb.strip() != CRYPTIC_DRAFT:
        lines.extend(
            [
                "## This blurb",
                "",
                payload["translation"]["plain"],
                "",
            ]
        )
    return "\n".join(lines)


def tape_guide_html(blurb: Optional[str] = None) -> str:
    payload = tape_guide_payload(blurb)
    items = "".join(
        (
            f"<div class='term'><dt>{_escape(row['term'])}</dt>"
            f"<dd><code>{_escape(row['example'])}</code> — {_escape(row['plain'])}</dd></div>"
        )
        for row in payload["glossary"]
    )
    nots = "".join(f"<li>{_escape(item)}</li>" for item in payload["not"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{_escape(payload["title"])}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{ font: 16px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 0 auto;
            max-width: 40rem; padding: 1.5rem; background: #0b0d12; color: #e8e6df; }}
    h1, h2 {{ font-weight: 600; letter-spacing: .02em; }}
    .lede {{ color: #c4c1b6; }}
    pre {{ white-space: pre-wrap; background: #161821; padding: 1rem; border-radius: 8px; }}
    .plain {{ background: #13231a; padding: 1rem; border-radius: 8px; }}
    dt {{ font-weight: 600; margin-top: 1rem; }}
    code {{ color: #9ad7c8; }}
    a {{ color: #8eb4ff; }}
  </style>
</head>
<body>
  <h1>{_escape(payload["title"])}</h1>
  <p class="lede">{_escape(payload["lede"])}</p>
  <p><a href="{_escape(payload["live_url"])}">Open the Live tape</a>
     · <a href="{_escape(payload["soul_url"])}">House soul</a></p>
  <h2>Worked example</h2>
  <pre>{_escape(payload["worked_example"]["cryptic"])}</pre>
  <p class="plain">{_escape(payload["worked_example"]["plain"])}</p>
  <h2>Glossary</h2>
  <dl>{items}</dl>
  <h2>What this is not</h2>
  <ul>{nots}</ul>
</body>
</html>
"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
