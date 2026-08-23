"""FCI index_event ingest: Hermes journal, not trader posture."""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest  # type: ignore[unresolved-import]

from gateway.dfy_index_events import (
    INDEX_STREAM_LABEL,
    IndexEventRejected,
    apply_index_event,
    citation_payload,
    index_event_freshness,
    list_index_events,
    reset_index_event_store,
    sanitize_index_event,
)
from gateway.dfy_ingest import fold_ingest_events, ingest_token, verify_ingest_token


ETH_CLEARED_DATA: Dict[str, Any] = {
    "transition": "cleared",
    "symbol": "ETH",
    "horizon": "1D",
    "side": "long",
    "signed": 0.348,
    "conf": 0.51,
    "rung": "purist",
    "card": {"band": 0.29, "min_conf": 0.45, "name": "Core 1D"},
    "distance_to_band": 0.058,
    "feed_version": "harvest-v3",
    "as_of": "2026-08-23T00:00:00Z",
    "bar_close_ts": "2026-08-23T00:00:00Z",
    "source": "underlying",
    "venue_last_close": 4210.5,
    "book_near": ["HYPE1D"],
    "paragraph": (
        "From here: ETH1D is in on the Core 1D card. "
        "Mechanism: both bars have to clear; this print did (0.29 / 0.45). "
        "Metric: signed +0.348, conf 0.51; HYPE1D is +0.279, 1bp short. "
        "Constraint: the read expires at 1D. Crypto 90M uses 0.14 / 0.40 and is held. "
        "Not committed: information index, not a trade, not a return."
    ),
}
ETH_CLEARED: Dict[str, Any] = {
    "kind": "index_event",
    "bot": "fci-watcher",
    "data": ETH_CLEARED_DATA,
}


@pytest.fixture(autouse=True)
def _clean_index_store():
    reset_index_event_store()
    yield
    reset_index_event_store()


def test_sanitize_labels_stream_index_not_posture():
    row = sanitize_index_event(ETH_CLEARED_DATA, bot="fci")
    assert row["stream"] == INDEX_STREAM_LABEL
    assert row["label"] == "index"
    assert row["facts"]["symbol"] == "ETH"
    assert row["facts"]["transition"] == "cleared"
    assert "pnl" not in json.dumps(row).lower()


def test_rejects_paper_overlay_marks():
    with pytest.raises(IndexEventRejected):
        sanitize_index_event({**ETH_CLEARED_DATA, "source": "overlay"})
    with pytest.raises(IndexEventRejected):
        sanitize_index_event({**ETH_CLEARED_DATA, "paper": True})
    with pytest.raises(IndexEventRejected):
        sanitize_index_event({**ETH_CLEARED_DATA, "overlay_marks": [{"n": 195}]})


def test_rejects_held_and_unknown_transitions():
    with pytest.raises(IndexEventRejected, match="transition"):
        sanitize_index_event({**ETH_CLEARED_DATA, "transition": "held"})


def test_rejects_forbidden_trader_fields():
    with pytest.raises(IndexEventRejected, match="forbidden"):
        sanitize_index_event({**ETH_CLEARED_DATA, "pnl": 12.4})
    with pytest.raises(IndexEventRejected, match="forbidden"):
        sanitize_index_event({**ETH_CLEARED_DATA, "exit_t": "2026-08-24T00:00:00Z"})
    with pytest.raises(IndexEventRejected, match="buy/sell"):
        sanitize_index_event({**ETH_CLEARED_DATA, "side": "buy"})


def test_dedupe_on_symbol_rung_transition_bar():
    first = apply_index_event(ETH_CLEARED_DATA, bot="fci")
    again = apply_index_event(ETH_CLEARED_DATA, bot="fci")
    assert first is not None
    assert again is None
    assert len(list_index_events()) == 1


def test_fold_does_not_call_trader_apply_event():
    result = fold_ingest_events(ETH_CLEARED)
    assert result["ok"] is True
    assert result["ingested"] == 1
    assert result["index_events"] == 1
    assert result.get("stream") == "index"
    assert not result.get("rejected")
    cited = citation_payload()
    assert cited["label"] == "index"
    assert cited["items"][0]["facts"]["symbol"] == "ETH"
    assert "not a trade" in cited["note"]
    assert "pnl" not in json.dumps(cited["items"][0]["facts"]).lower()


def test_fold_batch_index_survives_without_dfy_intel(monkeypatch):
    result = fold_ingest_events(
        {
            "events": [
                ETH_CLEARED,
                {"kind": "entry_fill", "data": {"pair": "ETH/USDT"}, "bot": "desk"},
            ]
        }
    )
    assert result["index_events"] == 1
    # trader kind cannot land without dfy_intel in this environment
    assert any(r.get("kind") == "entry_fill" for r in result.get("rejected", []))
    assert list_index_events()[0]["stream"] == "index"


def test_paper_event_not_stored():
    result = fold_ingest_events(
        {
            "kind": "index_event",
            "data": {**ETH_CLEARED_DATA, "source": "lnfm"},
        }
    )
    assert result["ingested"] == 0
    assert result["index_events"] == 0
    assert list_index_events() == []


def test_freshness_empty_then_populated():
    empty = index_event_freshness()
    assert empty["count"] == 0
    apply_index_event(ETH_CLEARED_DATA, bot="fci")
    ready = index_event_freshness()
    assert ready["count"] == 1
    assert ready["last_symbol"] == "ETH"
    assert ready["last_transition"] == "cleared"


def test_verify_ingest_token(monkeypatch):
    monkeypatch.setenv("HERMES_INGEST_TOKEN", "secret-token")
    assert ingest_token() == "secret-token"
    assert verify_ingest_token("Bearer secret-token")
    assert not verify_ingest_token("Bearer other")
    assert not verify_ingest_token(None)


def test_redacts_mutantdefi_from_paragraph():
    row = sanitize_index_event(
        {**ETH_CLEARED_DATA, "paragraph": "see MutantDeFi desk"},
        bot="fci",
    )
    assert "MutantDeFi" not in row["paragraph"]
    assert "[redacted]" in row["paragraph"]
