"""
x402 microtransaction HTTP gateway for the DFY feed.

Serves strategy mechanisms, signals, and activity as JSON. When payment is
required, responds with HTTP 402 and an x402-shaped challenge body.

Enable with X402_INTEL_ENABLED=true (or gateway config). Requires aiohttp.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover
    AIOHTTP_AVAILABLE = False
    web = None  # type: ignore[assignment]

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8643

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Intel-Payment-MAC, X-Payment-Response",
}


def check_x402_intel_requirements() -> bool:
    return AIOHTTP_AVAILABLE


if AIOHTTP_AVAILABLE:

    @web.middleware
    async def _cors(request, handler):
        if request.method == "OPTIONS":
            return web.Response(status=200, headers=_CORS_HEADERS)
        response = await handler(request)
        response.headers.update(_CORS_HEADERS)
        return response


class X402IntelAdapter(BasePlatformAdapter):
    """Minimal platform adapter: only runs an aiohttp server (no messaging)."""

    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.X402_INTEL)
        extra = config.extra or {}
        self._host: str = extra.get("host", os.getenv("X402_INTEL_HOST", DEFAULT_HOST))
        self._port: int = int(extra.get("port", os.getenv("X402_INTEL_PORT", str(DEFAULT_PORT))))
        self._app: Optional["web.Application"] = None
        self._runner: Optional["web.AppRunner"] = None
        self._site: Optional["web.TCPSite"] = None

    def _pay_params(self, resource: str) -> Dict[str, str]:
        return {
            "network": os.getenv("X402_NETWORK", "base"),
            "pay_to": os.getenv("X402_PAYTO_ADDRESS", ""),
            "asset": os.getenv("X402_ASSET_SYMBOL", "USDC"),
            "max_amount": os.getenv("X402_MAX_AMOUNT_ATOMIC", "1000"),
            "description": os.getenv("X402_RESOURCE_DESCRIPTION", "dfy_execution_feed"),
            "resource": resource,
        }

    async def _gate_or_serve(
        self,
        request: "web.Request",
        resource_path: str,
        build_body: Any,
    ) -> "web.Response":
        from dfy_intel import virtuals_bridge
        from dfy_intel.x402_payment import (
            build_payment_required_payload,
            verify_settled_payment,
        )

        pay = self._pay_params(resource_path)

        try:
            raw = await request.read()
        except Exception:
            raw = b""

        ok, reason = await verify_settled_payment(request, resource_path, raw)
        if not ok:
            if not pay["pay_to"] and os.getenv("X402_SKIP_PAYMENT", "").lower() not in (
                "1",
                "true",
                "yes",
            ):
                return web.json_response(
                    {
                        "error": "server_misconfigured",
                        "detail": "Set X402_PAYTO_ADDRESS or X402_SKIP_PAYMENT=true for dev",
                    },
                    status=500,
                )
            payload = build_payment_required_payload(
                resource=pay["resource"],
                network=pay["network"],
                pay_to=pay["pay_to"],
                asset=pay["asset"],
                max_amount=pay["max_amount"],
                description=pay["description"],
            )
            return web.json_response(payload, status=402)

        virtuals_bridge.record_settlement(
            resource_path=resource_path,
            amount_usdc=pay["max_amount"],
            payer_ref=request.headers.get("X-Payer-Ref", request.remote or ""),
            network=pay["network"],
            extra={"asset": pay["asset"], "verify_note": reason or "ok"},
        )

        payload = build_body()
        return web.json_response(payload)

    async def _handle_health(self, request: "web.Request") -> "web.Response":
        return web.json_response({"status": "ok", "service": "hermes-x402-dfy"})

    async def _handle_mechanisms(self, request: "web.Request") -> "web.Response":
        from dfy_intel.store import get_dfy_store

        return await self._gate_or_serve(
            request,
            "/v1/dfy/mechanisms",
            get_dfy_store().get_mechanisms,
        )

    async def _handle_signals(self, request: "web.Request") -> "web.Response":
        from dfy_intel.store import get_dfy_store

        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))

        return await self._gate_or_serve(
            request,
            "/v1/dfy/signals",
            lambda: {"items": get_dfy_store().get_signals(limit=limit)},
        )

    async def _handle_activity(self, request: "web.Request") -> "web.Response":
        from dfy_intel.store import get_dfy_store

        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))

        return await self._gate_or_serve(
            request,
            "/v1/dfy/activity",
            lambda: {"items": get_dfy_store().get_activity(limit=limit)},
        )

    async def connect(self) -> bool:
        if not AIOHTTP_AVAILABLE:
            logger.warning("[%s] aiohttp not installed", self.name)
            return False

        try:
            self._app = web.Application(middlewares=[_cors])
            self._app.router.add_get("/health", self._handle_health)
            self._app.router.add_get("/v1/dfy/mechanisms", self._handle_mechanisms)
            self._app.router.add_get("/v1/dfy/signals", self._handle_signals)
            self._app.router.add_get("/v1/dfy/activity", self._handle_activity)

            self._runner = web.AppRunner(self._app)
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, self._host, self._port)
            await self._site.start()

            self._mark_connected()
            logger.info(
                "[%s] x402 intel gateway http://%s:%s",
                self.name,
                self._host,
                self._port,
            )
            return True
        except Exception as e:
            logger.error("[%s] failed to start: %s", self.name, e)
            return False

    async def disconnect(self) -> None:
        self._mark_disconnected()
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        self._app = None
        logger.info("[%s] stopped", self.name)

    async def send(self, chat_id: str, content: str, reply_to=None, metadata=None) -> SendResult:
        return SendResult(success=False, error="x402 intel is HTTP-only")

    async def get_chat_info(self, chat_id: str) -> Dict[str, Any]:
        return {"name": "x402_intel", "host": self._host, "port": self._port}
