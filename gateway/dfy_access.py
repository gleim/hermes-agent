"""Tier-C access gates for DFY oracle surfaces (Hermes-side).

Tier A (posture-only) is served via ``guidance_projection`` on x402/api_server read
routes. Tier C (raw feed + strategy source + reports) requires explicit operator
opt-in plus a configured ingest bearer — never auto-enabled from a vendored corpus.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Tuple


class DfyIntelUnavailable(ImportError):
    """Raised when dfy_intel is not installed (``uv sync --extra dfy``)."""


def ensure_dfy_intel() -> None:
    """Import dfy_intel or raise :class:`DfyIntelUnavailable` with install hint."""
    try:
        importlib.import_module("dfy_intel")
    except ImportError as exc:
        raise DfyIntelUnavailable(
            "dfy_intel is not installed. Run: uv sync --extra dfy "
            "(or: uv pip install -e ../dfy-trader-intel/packages/dfy_intel)"
        ) from exc


def dfy_unavailable_json() -> Tuple[dict[str, Any], int]:
    """503 payload when the optional dfy extra was not installed."""
    return (
        {
            "error": "dfy_intel_not_installed",
            "detail": (
                "Install the dfy extra: uv sync --extra dfy — "
                "or editable: uv pip install -e ../dfy-trader-intel/packages/dfy_intel"
            ),
        },
        503,
    )


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
        ensure_dfy_intel()
        from dfy_intel.ingest import ingest_token

        return bool(ingest_token())
    except Exception:
        return False
