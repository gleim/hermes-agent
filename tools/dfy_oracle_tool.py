"""``dfy_oracle`` agent tool — exposes the live DFY trading feed + strategy
sources + published reports to the conversational agent.

This is the chat-GUI counterpart to the Discord ``/dfy-oracle`` slash command:
both build their context from :mod:`dfy_intel.oracle`, so the web / TUI / CLI
chat gets the same strategy-aware, report-aware analysis surface. The tool
returns structured context (it does NOT call a second LLM) — the agent already
holding the conversation reasons over it directly.

Availability is gated by :func:`check_dfy_oracle_requirements`: the tool only
appears when a DFY deployment is present (live snapshot file exists, or one of
the ``DFY_*`` env knobs is configured), so it stays hidden on vanilla Hermes.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from tools.registry import registry, tool_error, tool_result

logger = logging.getLogger(__name__)


def _snapshot_path() -> Path:
    raw = (os.getenv("DFY_INTEL_SNAPSHOT_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".hermes" / "dfy_feed" / "dfy_live_snapshot.json"


def check_dfy_oracle_requirements() -> bool:
    """Available only when Tier-C oracle is explicitly enabled and bearer-configured.

    The vendored corpus alone does NOT enable this tool — posture-only surfaces
    (x402 / api_server read routes) never expose strategy source or raw digests.
    """
    from gateway.dfy_access import oracle_tier_c_allowed

    if not oracle_tier_c_allowed():
        return False
    if any(
        (os.getenv(k) or "").strip()
        for k in (
            "DFY_INTEL_SNAPSHOT_PATH",
            "DFY_ORACLE_STRATEGY_PATHS",
            "DFY_ORACLE_STRATEGY_DIR",
            "DFY_ORACLE_REPORT_PATHS",
            "DFY_ORACLE_REPORT_DIR",
            "DFY_ORACLE_CONFIG_PATHS",
        )
    ):
        return True
    try:
        from dfy_intel.corpus_bundle import bundle_path

        if bundle_path().exists():
            return True
    except Exception:
        pass
    try:
        return _snapshot_path().exists()
    except OSError:
        return False


DFY_ORACLE_SCHEMA = {
    "name": "dfy_oracle",
    "description": (
        "Inspect the live DFY trading bot: its strategy internals, published "
        "analytic reports, and real-time feed (open trades, per-pair indicators, "
        "recent signals, realized exits + per-reason attribution). Use this to "
        "answer questions about what the trader is doing, why, how it lines up "
        "with the strategy code and the research papers, and what to check next.\n\n"
        "Returns structured JSON context for you to analyze and explain — it does "
        "not produce the analysis itself.\n\n"
        "views:\n"
        "- 'oracle' (default): full context — runner meta, mechanisms (open trades + "
        "latest indicators), recent signals, activity, strategy source files, and "
        "published reports.\n"
        "- 'mechanisms': just the live mechanisms block (open trades, indicators, "
        "exit attribution).\n"
        "- 'signals': recent indicator/signal digests.\n"
        "- 'activity': recent trade/activity events (entries, exits, snapshots).\n"
        "- 'index': FCI index_event journal (live-print edges only; not trader posture).\n\n"
        "Set include_sources/include_reports=false on the 'oracle' view to trim the "
        "payload when you only need the live numbers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "view": {
                "type": "string",
                "enum": ["oracle", "mechanisms", "signals", "activity", "index"],
                "description": "Which slice to return. Default 'oracle' (everything).",
                "default": "oracle",
            },
            "focus": {
                "type": "string",
                "description": "Optional free-text focus echoed back into the payload (e.g. a pair or question).",
            },
            "signals_limit": {
                "type": "integer",
                "description": "Max recent signals to include (default 40).",
                "default": 40,
            },
            "activity_limit": {
                "type": "integer",
                "description": "Max recent activity events to include (default 25).",
                "default": 25,
            },
            "include_sources": {
                "type": "boolean",
                "description": "Include strategy source files in the 'oracle' view (default true).",
                "default": True,
            },
            "include_reports": {
                "type": "boolean",
                "description": "Include published analytic reports in the 'oracle' view (default true).",
                "default": True,
            },
        },
        "required": [],
    },
}


def dfy_oracle_tool(args: Dict[str, Any], **_kwargs) -> str:
    view = (args.get("view") or "oracle").strip().lower()
    if view == "index":
        from gateway.dfy_index_events import citation_payload

        limit = int(args.get("activity_limit") or 25)
        return tool_result({"view": view, **citation_payload(limit=limit)})

    try:
        from dfy_intel.oracle import build_oracle_payload
        from dfy_intel.store import get_dfy_store
    except Exception as exc:  # dfy_intel not importable in this deployment
        return tool_error(f"DFY intel feed unavailable: {type(exc).__name__}: {exc}")

    # Live feed arrives by the trader PUSHING events to the Hermes ingest
    # endpoint (gateway, outbound-only from the trader — see dfy_intel.ingest).
    # Report whether anything has been received so the agent can tell live data
    # apart from corpus-only analysis.
    feed_status: Dict[str, Any] = {}
    try:
        from dfy_intel.ingest import feed_freshness

        feed_status = feed_freshness()
    except Exception as exc:
        feed_status = {"error": f"{type(exc).__name__}: {exc}"}
    signals_limit = int(args.get("signals_limit") or 40)
    activity_limit = int(args.get("activity_limit") or 25)

    try:
        if view == "mechanisms":
            return tool_result({"view": view, "mechanisms": get_dfy_store().get_mechanisms()})
        if view == "signals":
            return tool_result(
                {"view": view, "items": get_dfy_store().get_signals(limit=signals_limit)}
            )
        if view == "activity":
            return tool_result(
                {"view": view, "items": get_dfy_store().get_activity(limit=activity_limit)}
            )

        payload = build_oracle_payload(
            focus=args.get("focus") or "",
            signals_limit=signals_limit,
            activity_limit=activity_limit,
            include_sources=bool(args.get("include_sources", True)),
            include_reports=bool(args.get("include_reports", True)),
        )
        from gateway.dfy_index_events import citation_payload

        # Serialize with default=str so datetimes / numpy scalars survive.
        return json.dumps(
            {
                "view": "oracle",
                "live_feed": feed_status,
                "index_events": citation_payload(limit=min(activity_limit, 8)),
                **payload,
            },
            ensure_ascii=False, default=str,
        )
    except Exception as exc:
        logger.exception("dfy_oracle tool error: %s", exc)
        return tool_error(f"dfy_oracle failed: {type(exc).__name__}: {exc}")


registry.register(
    name="dfy_oracle",
    toolset="dfy",
    schema=DFY_ORACLE_SCHEMA,
    handler=dfy_oracle_tool,
    check_fn=check_dfy_oracle_requirements,
    requires_env=["DFY_ORACLE_ENABLED", "HERMES_INGEST_TOKEN"],
    description="Live DFY trading feed + strategy sources + published reports for analysis.",
    emoji="📈",
    max_result_size_chars=200000,
)
