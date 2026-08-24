"""Tests for gateway.dfy_tape — first-reader tape guide, translator, persona.

Pure-module tests: no third-party deps. Endpoint tests live in
test_dfy_tape_endpoints.py (importorskip aiohttp).
"""

import json

import pytest

from gateway import dfy_tape
from gateway.dfy_tape import (
    DISCLAIMER,
    EXAMPLE_TAPE,
    LIVE_LINK,
    LIVE_URL,
    NOT_LIST,
    TapeCard,
    humanize_horizon,
    negotiate_tape_guide,
    parse_tape,
    read_the_tape,
    render_legend,
    render_tape_guide,
    render_tape_guide_html,
    serve_tape_guide,
    split_symbol_horizon,
    translate_tape,
    wrap_persona,
)


# ---------------------------------------------------------------------------
# Horizon helpers
# ---------------------------------------------------------------------------


class TestHorizonHelpers:
    @pytest.mark.parametrize(
        "code,expected",
        [("1D", "1-day"), ("90M", "90-minute"), ("4H", "4-hour"), ("2W", "2-week")],
    )
    def test_humanize_horizon(self, code, expected):
        assert humanize_horizon(code) == expected

    def test_humanize_horizon_none(self):
        assert humanize_horizon(None) is None

    def test_humanize_horizon_unknown_passthrough(self):
        assert humanize_horizon("weekly") == "weekly"

    @pytest.mark.parametrize(
        "code,expected",
        [("HYPE1D", ("HYPE", "1D")), ("HYPE90M", ("HYPE", "90M")), ("btc4h", ("BTC", "4H"))],
    )
    def test_split_symbol_horizon(self, code, expected):
        assert split_symbol_horizon(code) == expected

    def test_split_symbol_horizon_no_horizon(self):
        assert split_symbol_horizon("HYPE") == ("HYPE", None)


# ---------------------------------------------------------------------------
# parse_tape
# ---------------------------------------------------------------------------


class TestParseTape:
    def test_parses_example_fields(self):
        card = parse_tape(EXAMPLE_TAPE)
        assert card.variant == "standard"
        assert card.symbol == "HYPE"
        assert card.horizon == "1D"
        assert card.last_action_move == pytest.approx(0.413)
        assert card.confidence == pytest.approx(0.58)
        assert card.side == "long"
        assert card.open is True
        assert card.exit_horizon == "1D"
        assert card.exit_in == "15h"
        assert card.current_print == pytest.approx(0.634)
        assert card.core_horizon == "1D"
        assert card.core_state == "held"
        assert card.measurement_public is True
        assert card.method_private is True
        assert card.link == LIVE_LINK

    def test_parses_secondary_reading(self):
        card = parse_tape(EXAMPLE_TAPE)
        assert len(card.secondary) == 1
        sec = card.secondary[0]
        assert sec["symbol"] == "HYPE"
        assert sec["horizon"] == "90M"
        assert sec["print"] == pytest.approx(0.553)
        assert sec["state"] == "held"

    def test_short_side_and_closed(self):
        card = parse_tape(
            "BTC4H is the live card: last-action -0.2 / c0.71, short. closed. Current print 0.1."
        )
        assert card.side == "short"
        assert card.last_action_move == pytest.approx(-0.2)
        assert card.confidence == pytest.approx(0.71)
        assert card.open is False

    def test_empty_is_tolerant(self):
        card = parse_tape("")
        assert isinstance(card, TapeCard)
        assert card.symbol is None
        assert card.secondary == []

    def test_garbage_does_not_raise(self):
        card = parse_tape("hello world, nothing to see here")
        assert card.symbol is None
        assert card.last_action_move is None


# ---------------------------------------------------------------------------
# translate_tape
# ---------------------------------------------------------------------------


class TestTranslateTape:
    def test_translation_is_relatable(self):
        text = translate_tape(EXAMPLE_TAPE)
        assert "Hyperliquid" in text
        assert "one-day" in text
        assert "long" in text
        assert "0.58" in text
        assert "0.634" in text
        assert "still open" in text.lower()
        assert "15 hours" in text
        assert "held" in text.lower()
        assert DISCLAIMER in text
        # first-reader voice: name and clock, not the house telegram
        assert not text.startswith("GM!")

    def test_translation_does_not_invent_numbers(self):
        text = translate_tape(EXAMPLE_TAPE)
        for bogus in ("0.999", "1.234", "42"):
            assert bogus not in text

    def test_print_is_not_a_return(self):
        text = translate_tape(EXAMPLE_TAPE).lower()
        assert "unsigned print" in text
        assert "lean" in text
        assert "return" not in text or "not a return" in text

    def test_translate_accepts_dict(self):
        text = translate_tape(
            {"symbol": "ETH", "horizon": "4H", "side": "short", "confidence": 0.8}
        )
        assert "Ethereum" in text or "ETH" in text
        assert "four-hour" in text or "4-hour" in text
        assert "short" in text
        assert "0.8" in text or "high" in text

    def test_translate_accepts_tapecard(self):
        card = parse_tape(EXAMPLE_TAPE)
        assert translate_tape(card) == translate_tape(EXAMPLE_TAPE)

    def test_confidence_bands(self):
        assert "low" in translate_tape({"symbol": "X", "confidence": 0.2})
        assert "0.5" in translate_tape({"symbol": "X", "confidence": 0.5})
        assert "0.7" in translate_tape({"symbol": "X", "confidence": 0.7})
        assert "0.9" in translate_tape({"symbol": "X", "confidence": 0.9})


# ---------------------------------------------------------------------------
# render_tape_guide / legend / HTML
# ---------------------------------------------------------------------------


class TestTapeGuide:
    def test_json_matches_live_contract(self):
        guide = render_tape_guide()
        assert guide["title"] == "How to read the tape"
        assert "probability-density tape" in guide["lede"]
        assert guide["live_url"] == LIVE_URL
        assert guide["soul_url"].endswith("/soul.md")
        assert guide["skills_url"].endswith("/skills.md")
        assert isinstance(guide["glossary"], list) and len(guide["glossary"]) >= 8
        for entry in guide["glossary"]:
            assert set(entry) >= {"term", "example", "plain"}
        assert set(guide["worked_example"]) >= {"cryptic", "plain"}
        assert "HYPE1D" in guide["worked_example"]["cryptic"]
        assert "Hyperliquid" in guide["worked_example"]["plain"]
        tr = guide["translation"]
        assert tr["live_card"] == "HYPE1D"
        assert tr["rung"] == "standard"
        assert tr["side"] == "long"
        assert tr["print"] == pytest.approx(0.634)
        assert tr["exit_hours"] == 15
        assert tr["held"] == ["Core 1D", "HYPE90M"]
        assert guide["personality"]["name"] == "datafi"
        assert "tape clerk" in guide["personality"]["system_prompt"]
        assert guide["not"] == list(NOT_LIST)

    def test_html_is_a_first_reader_page(self):
        page = render_tape_guide_html()
        assert page.startswith("<!DOCTYPE html>")
        assert "How to read the tape" in page
        assert "HYPE1D" in page
        assert "Hyperliquid" in page
        assert "Both bars have to clear" in page
        assert "Walk it" in page
        assert LIVE_URL in page
        assert "Not a buy or sell." in page
        assert "application/json" not in page  # this is the human face
        # house visual language, not a generic dump
        assert "IBM Plex" in page
        assert "#05070b" in page

    def test_legend_compat_title(self):
        legend = render_legend("json")
        assert legend["title"] == "How to read the tape"
        md = render_legend("markdown")
        assert md.startswith("# How to read the tape")
        txt = render_legend("text")
        assert "How to read the tape" in txt

    def test_read_the_tape_bundle(self):
        bundle = read_the_tape(EXAMPLE_TAPE)
        assert bundle["tape"] == EXAMPLE_TAPE
        assert bundle["decoded"]["symbol"] == "HYPE"
        assert "Hyperliquid" in bundle["translation"]
        assert bundle["exit_hours"] == 15


class TestNegotiate:
    def test_browser_accept_gets_html(self):
        body, ctype = negotiate_tape_guide(
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", ""
        )
        assert "text/html" in ctype
        assert body.startswith("<!DOCTYPE html>")

    def test_json_accept_gets_json(self):
        body, ctype = negotiate_tape_guide("application/json", "")
        assert "application/json" in ctype
        data = json.loads(body)
        assert data["title"] == "How to read the tape"

    def test_curl_default_gets_json(self):
        body, ctype = negotiate_tape_guide("*/*", "")
        assert "application/json" in ctype
        json.loads(body)

    def test_format_query_wins(self):
        body, ctype = negotiate_tape_guide("application/json", "html")
        assert "text/html" in ctype
        assert "<!DOCTYPE html>" in body

    def test_serve_never_raises(self):
        body, ctype = serve_tape_guide("text/html", "html")
        assert "text/html" in ctype
        assert "How to read the tape" in body


# ---------------------------------------------------------------------------
# wrap_persona
# ---------------------------------------------------------------------------


class TestPersona:
    def test_lead_style_is_plain_first(self):
        msg = wrap_persona(EXAMPLE_TAPE, style="lead")
        assert "Hyperliquid" in msg
        assert DISCLAIMER in msg
        assert not msg.startswith("GM!")
        assert not msg.startswith("New here?")

    def test_reply_style_points_to_live(self):
        msg = wrap_persona(EXAMPLE_TAPE, style="reply")
        assert LIVE_URL in msg
        assert "tape guide" in msg.lower()

    def test_plain_style_is_bare_translation(self):
        assert wrap_persona(EXAMPLE_TAPE, style="plain") == translate_tape(EXAMPLE_TAPE)

    def test_persona_prompt_has_guardrails(self):
        p = dfy_tape.GROK_PERSONA.lower()
        assert "not investment advice" in p
        assert "method" in p and "private" in p
        assert "never invent" in p
        assert "datafi" in p
        assert "datadefi" in p  # do-not-impersonate

    def test_render_persona_bundle_for_external_bot(self):
        bundle = dfy_tape.render_persona()
        assert bundle["persona"] == dfy_tape.GROK_PERSONA
        assert isinstance(bundle["glossary"], list) and len(bundle["glossary"]) >= 8
        assert bundle["disclaimer"] == DISCLAIMER
        assert bundle["link"] == LIVE_LINK
        assert bundle["live_url"] == LIVE_URL
