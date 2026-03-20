"""x402-style payment gating (HTTP 402) for DFY HTTP routes.

Uses a relaxed verifier for development (shared secret) and a placeholder for
Coinbase facilitator / full x402 verify flow. Align response bodies with:
https://docs.cdp.coinbase.com/x402/docs/http-402
when tightening production behavior.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, Optional, Tuple

def build_payment_required_payload(
    *,
    resource: str,
    network: str,
    pay_to: str,
    asset: str,
    max_amount: str,
    description: str,
) -> Dict[str, Any]:
    """Shape mirrors common x402 'accepts' arrays; refine against live facilitator schema."""
    return {
        "x402Version": 1,
        "error": "payment_required",
        "accepts": [
            {
                "scheme": "exact",
                "network": network,
                "maxAmountRequired": max_amount,
                "resource": resource,
                "description": description,
                "payTo": pay_to,
                "asset": asset,
            }
        ],
    }


def _relaxed_verify(request: Any, resource_path: str) -> bool:
    if os.getenv("X402_RELAXED_AUTH", "false").lower() not in ("1", "true", "yes"):
        return False
    secret = os.getenv("X402_DEV_SHARED_SECRET", "")
    if not secret:
        return False
    auth = request.headers.get("Authorization", "")
    token = ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
    if token == secret:
        return True
    sig = request.headers.get("X-Intel-Payment-MAC", "")
    body = f"{request.method}:{resource_path}:{secret}".encode()
    expect = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expect)


async def verify_settled_payment(
    request: Any,
    resource_path: str,
    body: bytes,
) -> Tuple[bool, Optional[str]]:
    """
    Return (ok, error_reason).

    Production: POST body / headers to your x402 facilitator verify endpoint.
    """
    if os.getenv("X402_SKIP_PAYMENT", "false").lower() in ("1", "true", "yes"):
        return True, None

    if _relaxed_verify(request, resource_path):
        return True, None

    facilitator_url = os.getenv("X402_FACILITATOR_VERIFY_URL", "").strip()
    if facilitator_url and body:
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    facilitator_url,
                    data=body,
                    headers={
                        "Content-Type": request.headers.get("Content-Type", "application/json"),
                        "X-Resource-Path": resource_path,
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return True, None
                    text = await resp.text()
                    return False, f"facilitator_{resp.status}:{text[:200]}"
        except Exception as exc:  # pragma: no cover
            return False, f"facilitator_error:{exc}"

    return False, "payment_not_verified"
