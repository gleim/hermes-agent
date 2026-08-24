"""Tests for gateway.dfy_tape — the "read the tape" legend, translator, and
grok persona wrapper, plus the public x402 legend/translate endpoints.

The pure-module tests have no third-party deps and always run. The endpoint
tests importorskip aiohttp (only installed with the messaging/web extras).
"""

import pytest

from gateway import dfy_tape
from gateway.dfy_tape import (
    DISCLAIMER,
    LIVE_LINK,
    TapeCard,
    humanize_horizon,
    parse_tape,
    read_the_tape,
    render_legend,
    split_symbol_horizon,
    translate_tape,
    wrap_persona,
)

# The exact cryptic lead a first-time user sees.
EXAMPLE_TAPE = """GM! tape, standard.

HYPE1D is the live card: last-action +0.413 / c0.58, long. Still open, 1D exit in ~15h. Current print 0.634.

Core 1D held. HYPE90M 0.553, held. Measurement is public. Method stays private. Not investment advice.
datafi.live"""


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
        # decoded, human phrasing
        assert "HYPE" in text
        assert "1-day" in text
        assert "90-minute" in text
        assert "long" in text
        assert "0.58" in text
        assert "0.634" in text
        assert "0.553" in text
        assert "still open" in text.lower()
        assert "15 hours" in text
        # standing framing
        assert DISCLAIMER in text
        assert LIVE_LINK in text

    def test_translation_does_not_invent_numbers(self):
        # Only values present in the tape should appear.
        text = translate_tape(EXAMPLE_TAPE)
        for bogus in ("0.999", "1.234", "42"):
            assert bogus not in text

    def test_translate_accepts_dict(self):
        text = translate_tape(
            {"symbol": "ETH", "horizon": "4H", "side": "short", "confidence": 0.8}
        )
        assert "ETH" in text
        assert "4-hour" in text
        assert "short" in text
        assert "high" in text  # 0.8 → high band

    def test_translate_accepts_tapecard(self):
        card = parse_tape(EXAMPLE_TAPE)
        assert translate_tape(card) == translate_tape(EXAMPLE_TAPE)

    def test_confidence_bands(self):
        assert "low" in translate_tape({"symbol": "X", "confidence": 0.2})
        assert "moderate" in translate_tape({"symbol": "X", "confidence": 0.5})
        assert "solid" in translate_tape({"symbol": "X", "confidence": 0.7})
        assert "high" in translate_tape({"symbol": "X", "confidence": 0.9})


# ---------------------------------------------------------------------------
# render_legend / read_the_tape
# ---------------------------------------------------------------------------


class TestLegend:
    def test_json_shape(self):
        legend = render_legend("json")
        assert legend["title"] == "How to Read the Tape"
        assert isinstance(legend["glossary"], list) and len(legend["glossary"]) >= 8
        for entry in legend["glossary"]:
            assert set(entry) >= {"token", "example", "meaning"}
        assert "How to Read the Tape" in legend["markdown"]
        assert legend["disclaimer"] == DISCLAIMER

    def test_markdown_documents_key_tokens(self):
        md = render_legend("markdown")
        assert md.startswith("# How to Read the Tape")
        for token in ("last-action", "c0.58", "live card", "Current print"):
            assert token in md

    def test_text_format(self):
        txt = render_legend("text")
        assert "How to Read the Tape" in txt
        assert LIVE_LINK in txt

    def test_read_the_tape_bundle(self):
        bundle = read_the_tape(EXAMPLE_TAPE)
        assert bundle["tape"] == EXAMPLE_TAPE
        assert bundle["decoded"]["symbol"] == "HYPE"
        assert "HYPE" in bundle["translation"]


# ---------------------------------------------------------------------------
# wrap_persona
# ---------------------------------------------------------------------------


class TestPersona:
    def test_lead_style(self):
        msg = wrap_persona(EXAMPLE_TAPE, style="lead")
        assert msg.startswith("New here?")
        assert "HYPE" in msg
        assert DISCLAIMER in msg

    def test_reply_style_points_to_guide(self):
        msg = wrap_persona(EXAMPLE_TAPE, style="reply")
        assert LIVE_LINK in msg
        assert "read the tape" in msg.lower()

    def test_plain_style_is_bare_translation(self):
        assert wrap_persona(EXAMPLE_TAPE, style="plain") == translate_tape(EXAMPLE_TAPE)

    def test_persona_prompt_has_guardrails(self):
        p = dfy_tape.GROK_PERSONA.lower()
        assert "not investment advice" in p
        assert "method" in p and "private" in p
        assert "never promise" in p or "never invent" in p

    def test_render_persona_bundle_for_external_bot(self):
        bundle = dfy_tape.render_persona()
        # The external grok bot fetches the voice + vocabulary over HTTP.
        assert bundle["persona"] == dfy_tape.GROK_PERSONA
        assert isinstance(bundle["glossary"], list) and len(bundle["glossary"]) >= 8
        assert bundle["disclaimer"] == DISCLAIMER
        assert bundle["link"] == LIVE_LINK
