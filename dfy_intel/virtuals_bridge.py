"""Bridge verified x402 settlements to Virtuals.io agent token allocation (Uniswap).

This module does not submit on-chain transactions in the scaffold. It records
intended distribution steps so a worker or smart contract path can execute swaps.

Environment (planning hooks):
  VIRTUALS_AGENT_TOKEN_ADDRESS — ERC-20 token from Virtuals / agent launch
  VIRTUALS_CHAIN_ID — e.g. 8453 (Base)
  UNISWAP_V3_ROUTER or UNISWAP_UNIVERSAL_ROUTER — pool/router for the pair
  DISTRIBUTION_RPC_URL — optional JSON-RPC for a keeper
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _ledger_path() -> Path:
    home = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
    d = home / "dfy_feed"
    d.mkdir(parents=True, exist_ok=True)
    return d / "virtuals_settlement_ledger.jsonl"


def _load_allocation_policy() -> Dict[str, Any]:
    return {
        "agent_token": os.getenv("VIRTUALS_AGENT_TOKEN_ADDRESS", ""),
        "chain_id": os.getenv("VIRTUALS_CHAIN_ID", ""),
        "router": os.getenv("UNISWAP_V3_ROUTER", "") or os.getenv("UNISWAP_UNIVERSAL_ROUTER", ""),
        "quote_token": os.getenv("VIRTUALS_QUOTE_TOKEN", "USDC"),
    }


def record_settlement(
    *,
    resource_path: str,
    amount_usdc: str,
    payer_ref: str,
    network: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Append a settlement record and return the planned allocation descriptor.

    Downstream: swap incoming USDC (per x402 settlement) into the agent token on Uniswap.
    """
    policy = _load_allocation_policy()
    row: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "resource_path": resource_path,
        "amount_usdc": amount_usdc,
        "payer_ref": payer_ref,
        "network": network,
        "allocation_policy": policy,
        "status": "recorded",
        "extra": extra or {},
    }

    try:
        line = json.dumps(row, default=str) + "\n"
        path = _ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError as exc:
        logger.warning("virtuals_bridge: could not write ledger: %s", exc)

    logger.info(
        "virtuals_bridge: recorded settlement resource=%s amount_usdc=%s payer=%s",
        resource_path,
        amount_usdc,
        payer_ref,
    )
    return row


def planned_swap_intent(settlement_row: Dict[str, Any]) -> Dict[str, Any]:
    """Describe a Uniswap swap intent for a treasury/keeper (no execution here)."""
    policy = settlement_row.get("allocation_policy") or {}
    return {
        "side": "buy_agent_token",
        "spend_asset": settlement_row.get("extra", {}).get("asset", "USDC"),
        "spend_amount_hint": settlement_row.get("amount_usdc"),
        "buy_token": policy.get("agent_token"),
        "chain_id": policy.get("chain_id"),
        "router": policy.get("router"),
    }


def read_recent_ledger(max_lines: int = 50) -> List[Dict[str, Any]]:
    path = _ledger_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in lines[-max_lines:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
