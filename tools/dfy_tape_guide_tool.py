"""``dfy_tape_guide`` — translate DataFi tape jargon for first-time readers."""

from __future__ import annotations

from typing import Any, Dict

from tools.registry import registry, tool_result


DFY_TAPE_GUIDE_SCHEMA = {
    "name": "dfy_tape_guide",
    "description": (
        "Explain the DataFi / GM! Live tape in plain language and translate a "
        "cryptic promo or ticker blurb (HYPE1D, last-action, c0.58, held). "
        "This is an information index, not a trade. Use when a user is "
        "auditing a ticker for the first time or pasted an X draft."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "blurb": {
                "type": "string",
                "description": (
                    "Optional cryptic tape / X text to translate. "
                    "Omit to return the Live-page glossary and worked example."
                ),
            },
        },
        "required": [],
    },
}


def dfy_tape_guide_tool(args: Dict[str, Any], **_kwargs) -> str:
    from gateway.dfy_tape_guide import tape_guide_payload

    blurb = args.get("blurb")
    if blurb is not None:
        blurb = str(blurb)
    return tool_result(tape_guide_payload(blurb=blurb))


registry.register(
    name="dfy_tape_guide",
    toolset="dfy",
    schema=DFY_TAPE_GUIDE_SCHEMA,
    handler=dfy_tape_guide_tool,
    description="Translate DataFi tape jargon for first-time readers.",
    emoji="📗",
)
