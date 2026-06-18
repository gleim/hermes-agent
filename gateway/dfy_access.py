"""Tier-C access gates for DFY oracle surfaces (Hermes-side).

Tier A (posture-only) is served via ``guidance_projection`` on x402/api_server read
routes. Tier C (raw feed + strategy source + reports) requires explicit operator
opt-in plus a configured ingest bearer — never auto-enabled from a vendored corpus.
"""

from __future__ import annotations

import os


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def oracle_enabled() -> bool:
    """Explicit operator opt-in for Tier-C oracle surfaces."""
    return _truthy("DFY_ORACLE_ENABLED")


def oracle_tier_c_allowed() -> bool:
    """Tier-C: oracle tool, raw api_server/discord feeds, strategy + report corpus."""
    if not oracle_enabled():
        return False
    try:
        from dfy_intel.ingest import ingest_token

        return bool(ingest_token())
    except Exception:
        return False
