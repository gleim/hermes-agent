"""``dfy_index_events`` — cite the FCI index journal (not trader posture).

The watcher posts ``index_event`` on the existing ingest envelope. This tool
returns the stored fact bundle + narrator paragraph so GROUP/COMPUTER can
cite a live-print edge without pulling desk / brief / journal_voice.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from tools.registry import registry, tool_result


def check_dfy_index_events_requirements() -> bool:
    return bool((os.getenv("HERMES_INGEST_TOKEN") or "").strip())


DFY_INDEX_EVENTS_SCHEMA = {
    "name": "dfy_index_events",
    "description": (
        "Read recent FCI index_event prints (held→cleared, cleared→expired, "
        "or near-miss on a frozen harvest card). This is an information index, "
        "not a trade and not a return. Do not mix these facts with trader "
        "posture, IC, PnL, or desk briefs. Use when citing a GM! / harvest "
        "edge the watcher already narrated."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max recent index events to return (default 8).",
                "default": 8,
            },
        },
        "required": [],
    },
}


def dfy_index_events_tool(args: Dict[str, Any], **_kwargs) -> str:
    from gateway.dfy_index_events import citation_payload

    limit = int(args.get("limit") or 8)
    return tool_result(citation_payload(limit=limit))


registry.register(
    name="dfy_index_events",
    toolset="dfy",
    schema=DFY_INDEX_EVENTS_SCHEMA,
    handler=dfy_index_events_tool,
    check_fn=check_dfy_index_events_requirements,
    requires_env=["HERMES_INGEST_TOKEN"],
    description="Cite recent FCI index_event prints (not trader posture).",
    emoji="📡",
)
