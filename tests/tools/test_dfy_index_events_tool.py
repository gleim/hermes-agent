"""dfy_index_events tool — cite the index journal, not desk posture."""

from __future__ import annotations

import json

import pytest

from gateway.dfy_index_events import apply_index_event, reset_index_event_store
from tools.dfy_index_events_tool import (
    check_dfy_index_events_requirements,
    dfy_index_events_tool,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_index_event_store()
    yield
    reset_index_event_store()


def test_check_fn_requires_ingest_token(monkeypatch):
    monkeypatch.delenv("HERMES_INGEST_TOKEN", raising=False)
    assert check_dfy_index_events_requirements() is False
    monkeypatch.setenv("HERMES_INGEST_TOKEN", "tok")
    assert check_dfy_index_events_requirements() is True


def test_tool_returns_index_label_and_facts():
    apply_index_event(
        {
            "transition": "near_miss",
            "symbol": "HYPE",
            "horizon": "1D",
            "side": "long",
            "signed": 0.279,
            "conf": 0.62,
            "rung": "balanced",
            "card": {"band": 0.29, "min_conf": 0.45},
            "distance_to_band": 0.011,
            "bar_close_ts": "2026-08-23T00:00:00Z",
            "source": "underlying",
            "paragraph": "From here: HYPE1D is 1bp short of the Core 1D card.",
        },
        bot="fci",
    )
    payload = json.loads(dfy_index_events_tool({"limit": 4}))
    assert payload["label"] == "index"
    assert payload["stream"] == "index"
    assert "not a trade" in payload["note"]
    assert payload["items"][0]["facts"]["symbol"] == "HYPE"
    assert payload["items"][0]["transition"] == "near_miss"
    assert "pnl" not in json.dumps(payload["items"][0]["facts"]).lower()


def test_oracle_index_view_does_not_need_dfy_intel():
    from tools.dfy_oracle_tool import dfy_oracle_tool

    apply_index_event(
        {
            "transition": "expired",
            "symbol": "ETH",
            "horizon": "1D",
            "side": "long",
            "signed": 0.10,
            "conf": 0.40,
            "rung": "active",
            "card": {"band": 0.14, "min_conf": 0.40},
            "bar_close_ts": "2026-08-22T00:00:00Z",
            "source": "live",
            "paragraph": "From here: ETH1D expired on the active card.",
        },
        bot="fci",
    )
    payload = json.loads(dfy_oracle_tool({"view": "index", "activity_limit": 3}))
    assert payload["view"] == "index"
    assert payload["label"] == "index"
    assert payload["items"][0]["transition"] == "expired"
