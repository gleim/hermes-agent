"""dfy_tape_guide tool — public translator, no ingest token."""

from __future__ import annotations

import json

from tools.dfy_tape_guide_tool import dfy_tape_guide_tool


def test_tool_returns_glossary_without_blurb():
    body = json.loads(dfy_tape_guide_tool({}))
    assert body["title"] == "How to read the tape"
    assert body["glossary"]
    assert body["personality"]["name"] == "datafi"


def test_tool_translates_blurb():
    body = json.loads(
        dfy_tape_guide_tool(
            {
                "blurb": (
                    "GM! tape, standard. HYPE1D is the live card: "
                    "last-action +0.413 / c0.58, long."
                )
            }
        )
    )
    assert body["translation"]["live_card"] == "HYPE1D"
    assert "hyperliquid" in body["translation"]["plain"].lower()
