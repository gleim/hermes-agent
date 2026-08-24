"""Public tape guide + Grok translator — glossary, not a second index."""

from __future__ import annotations

import re
from pathlib import Path

from gateway.dfy_tape_guide import (
    CRYPTIC_DRAFT,
    GROK_PERSONALITY,
    PLAIN_DRAFT,
    tape_guide_html,
    tape_guide_markdown,
    tape_guide_payload,
    translate_tape_blurb,
)


def test_description_length_on_skill():
    text = Path("skills/research/read-the-tape/SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^description: (.*)$", text, re.MULTILINE)
    assert match is not None
    assert len(match.group(1)) <= 60
    assert match.group(1).endswith(".")


def test_worked_example_covers_the_hype_promo():
    payload = tape_guide_payload()
    assert "HYPE1D" in payload["worked_example"]["cryptic"]
    plain = payload["worked_example"]["plain"].lower()
    assert "hyperliquid" in plain
    assert "one-day" in plain
    assert "0.634" in plain
    assert "15" in plain
    assert "not a trade" in plain
    assert "buy" not in plain
    assert "sell" not in plain


def test_translate_sample_blurb():
    out = translate_tape_blurb(CRYPTIC_DRAFT)
    assert out["live_card"] == "HYPE1D"
    assert out["rung"] == "standard"
    assert out["side"] == "long"
    assert out["last_action"]["signed"] == "+0.413"
    assert "0.58" in out["last_action"]["conf"]
    assert out["print"] == "0.634"
    assert out["exit_hours"] == 15
    assert "hyperliquid" in out["plain"].lower()
    assert "not investment advice" in out["plain"].lower()
    assert "pnl" not in out["plain"].lower()


def test_personality_refuses_method_and_trades():
    voice = GROK_PERSONALITY.lower()
    assert "not investment advice" in voice
    assert "method stays private" in voice or "don't publish" in voice
    assert "do not invent" in voice or "never invent" in voice
    assert "dfy_tape_guide" in voice or "translate" in voice


def test_markdown_and_html_are_embeddable():
    md = tape_guide_markdown()
    html = tape_guide_html()
    assert md.startswith("# How to read the tape")
    assert PLAIN_DRAFT.split()[0] in md
    assert "<h1>" in html
    assert "How to read the tape" in html


def test_empty_blurb_does_not_invent_a_ticker():
    out = translate_tape_blurb("hello there")
    assert out["live_card"] is None
    assert "couldn't parse" in out["plain"].lower()
