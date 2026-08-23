"""
x402 microtransaction HTTP gateway for the DFY feed.

Serves **posture-only** Tier-A guidance (``guidance_projection``) — never raw
store rows, indicator digests, or strategy source. When payment is required,
responds with HTTP 402 and an x402-shaped challenge body.

Raw snapshot / ingest / events stay bearer-gated for internal hydration only.

Enable with X402_INTEL_ENABLED=true (or gateway config). Requires aiohttp.
"""

from __future__ import annotations

import asyncio
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
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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
        from gateway.dfy_access import DfyIntelUnavailable, dfy_unavailable_json, ensure_dfy_intel

        try:
            ensure_dfy_intel()
        except DfyIntelUnavailable:
            body, status = dfy_unavailable_json()
            return web.json_response(body, status=status)
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

    def _posture_store(self):
        from dfy_intel.store import get_dfy_store

        return get_dfy_store()

    async def _handle_regime(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import regime_view

        store = self._posture_store()
        symbol = (request.query.get("symbol") or "").strip() or None
        return await self._gate_or_serve(
            request,
            "/v1/dfy/regime",
            lambda: regime_view(store, symbol=symbol),
        )

    async def _handle_posture(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import posture_view

        store = self._posture_store()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/posture",
            lambda: posture_view(store),
        )

    async def _handle_attribution(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import attribution_view

        store = self._posture_store()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/attribution",
            lambda: attribution_view(store),
        )

    async def _handle_brief(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import brief_view

        store = self._posture_store()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/brief",
            lambda: brief_view(store),
        )

    async def _handle_desk(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import desk_view

        store = self._posture_store()
        symbol = (request.query.get("symbol") or "BTC").strip()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/desk",
            lambda: desk_view(store, symbol),
        )

    async def _handle_crypto_guidance(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import crypto_guidance

        store = self._posture_store()
        symbol = (request.query.get("symbol") or "BTC").strip()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/guidance/crypto",
            lambda: crypto_guidance(store, symbol),
        )

    # Legacy paths — posture-only aliases (raw mechanisms/signals/activity removed).
    async def _handle_mechanisms(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import posture_view

        store = self._posture_store()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/mechanisms",
            lambda: {
                **posture_view(store),
                "deprecated": "Use /v1/dfy/posture — this path no longer returns raw mechanisms.",
            },
        )

    async def _handle_signals(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import regime_view

        store = self._posture_store()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/signals",
            lambda: {
                **regime_view(store),
                "deprecated": "Use /v1/dfy/regime — this path no longer returns raw signal digests.",
            },
        )

    async def _handle_activity(self, request: "web.Request") -> "web.Response":
        from dfy_intel.guidance_projection import brief_view

        store = self._posture_store()
        return await self._gate_or_serve(
            request,
            "/v1/dfy/activity",
            lambda: {
                **brief_view(store),
                "deprecated": "Use /v1/dfy/brief — this path no longer returns raw activity rows.",
            },
        )

    async def _handle_ingest_status(self, request: "web.Request") -> "web.Response":
        """Return a diagnostic snapshot of DfyIntelStore for verifying event ingestion.

        Requires the same HERMES_INGEST_TOKEN bearer credential as the ingest
        endpoint but does NOT require an x402 payment — it is an operator-only
        debug surface, not a paid data feed.
        """
        from dfy_intel.ingest import feed_freshness, ingest_token, verify_ingest_token
        from dfy_intel.store import get_dfy_store

        if not ingest_token():
            return web.json_response(
                {"error": "ingest disabled: set HERMES_INGEST_TOKEN"}, status=503
            )
        if not verify_ingest_token(request.headers.get("Authorization")):
            return web.json_response({"error": "unauthorized"}, status=401)

        store = get_dfy_store()
        freshness = feed_freshness()

        mechanisms = store.get_mechanisms()
        signals = store.get_signals()
        activity = store.get_activity()

        from gateway.dfy_index_events import index_event_freshness, list_index_events

        return web.json_response(
            {
                "freshness": freshness,
                "index_events": {
                    "freshness": index_event_freshness(),
                    "recent": list_index_events(limit=5),
                },
                "store": {
                    "mechanisms_keys": sorted(mechanisms.keys()),
                    "signal_count": len(signals),
                    "activity_count": len(activity),
                    "recent_signals": signals[-5:],
                    "recent_activity": activity[-5:],
                },
            }
        )

    async def _handle_snapshot(self, request: "web.Request") -> "web.Response":
        """Full store snapshot for INTERNAL consumers (the standalone guidance
        gateway hydrating over the private network). Bearer-gated with the same
        HERMES_INGEST_TOKEN as ingest — NOT an x402 paid surface, and never
        exposed publicly. Returns the raw store (mechanisms/signals/activity); the
        guidance gateway is responsible for the posture-only projection before any
        public 402 route serves it.
        """
        from dfy_intel.ingest import ingest_token, verify_ingest_token
        from dfy_intel.store import get_dfy_store

        if not ingest_token():
            return web.json_response(
                {"error": "snapshot disabled: set HERMES_INGEST_TOKEN"}, status=503
            )
        if not verify_ingest_token(request.headers.get("Authorization")):
            return web.json_response({"error": "unauthorized"}, status=401)

        return web.json_response(get_dfy_store().snapshot())

    async def _handle_dfy_events(self, request: "web.Request") -> "web.StreamResponse":
        """Server-Sent Events stream of DFY ingest events.

        Requires the same HERMES_INGEST_TOKEN bearer credential as the ingest
        endpoint.  Each successfully folded event is broadcast to all connected
        subscribers in real-time.  A heartbeat comment is sent every 30 seconds
        to keep proxies and browsers from closing idle connections.
        """
        import json as _json

        from gateway.dfy_index_events import subscribe as index_subscribe
        from gateway.dfy_index_events import unsubscribe as index_unsubscribe
        from gateway.dfy_ingest import ingest_auth_error

        auth = ingest_auth_error(request.headers.get("Authorization"))
        if auth:
            body, status = auth
            return web.Response(
                status=status,
                text=f"data: {_json.dumps(body)}\n\n",
                content_type="text/event-stream",
            )

        response = web.StreamResponse(
            status=200,
            headers={
                **_CORS_HEADERS,
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)

        # Send an initial connection-established comment so the client knows
        # the stream is live before the first real event arrives.
        await response.write(b": connected\n\n")

        _HEARTBEAT_INTERVAL = 30.0

        index_q = index_subscribe()
        intel_cm = None
        intel_q = None
        intel_stop = object()
        try:
            from dfy_intel import broadcaster

            intel_cm = broadcaster.subscribe()
            intel_q = intel_cm.__enter__()
            intel_stop = getattr(broadcaster, "STOP", intel_stop)
        except Exception:
            intel_cm = None
            intel_q = None

        loop = asyncio.get_event_loop()

        def _poll():
            try:
                return index_q.get(timeout=0.25)
            except Exception:
                pass
            if intel_q is not None:
                try:
                    return intel_q.get(timeout=0.25)
                except Exception:
                    return None
            return None

        try:
            idle = 0.0
            while True:
                try:
                    item = await loop.run_in_executor(None, _poll)
                except Exception:
                    item = None
                if item is None:
                    idle += 0.5
                    if idle >= _HEARTBEAT_INTERVAL:
                        try:
                            await response.write(b": heartbeat\n\n")
                        except Exception:
                            break
                        idle = 0.0
                    continue
                idle = 0.0
                if item is intel_stop:
                    break
                try:
                    payload = item if isinstance(item, str) else str(item)
                    await response.write(f"data: {payload}\n\n".encode())
                except Exception:
                    break
        finally:
            index_unsubscribe(index_q)
            if intel_cm is not None:
                try:
                    intel_cm.__exit__(None, None, None)
                except Exception:
                    pass

        return response

    async def _handle_ingest(self, request: "web.Request") -> "web.Response":
        """Receive events PUSHED outbound to Hermes. Bearer-token authenticated.

        ``index_event`` is stored as stream=index and never folded into
        posture / brief / desk. Other kinds go through dfy_intel.
        """
        from gateway.dfy_ingest import fold_ingest_events, ingest_auth_error

        auth = ingest_auth_error(request.headers.get("Authorization"))
        if auth:
            body, status = auth
            return web.json_response(body, status=status)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        result = fold_ingest_events(body)
        status = 200 if result.get("ok") else 503
        return web.json_response(result, status=status)

    async def _handle_index_events(self, request: "web.Request") -> "web.Response":
        """Recent FCI index prints. Bearer-gated, never an x402 paid surface."""
        from gateway.dfy_index_events import citation_payload
        from gateway.dfy_ingest import ingest_auth_error

        auth = ingest_auth_error(request.headers.get("Authorization"))
        if auth:
            body, status = auth
            return web.json_response(body, status=status)
        try:
            limit = int(request.query.get("limit", "25"))
        except ValueError:
            limit = 25
        return web.json_response(citation_payload(limit=limit))

    async def connect(self) -> bool:
        if not AIOHTTP_AVAILABLE:
            logger.warning("[%s] aiohttp not installed", self.name)
            return False

        try:
            self._app = web.Application(middlewares=[_cors])
            self._app.router.add_get("/health", self._handle_health)
            self._app.router.add_get("/v1/dfy/regime", self._handle_regime)
            self._app.router.add_get("/v1/dfy/posture", self._handle_posture)
            self._app.router.add_get("/v1/dfy/attribution", self._handle_attribution)
            self._app.router.add_get("/v1/dfy/brief", self._handle_brief)
            self._app.router.add_get("/v1/dfy/desk", self._handle_desk)
            self._app.router.add_get("/v1/dfy/guidance/crypto", self._handle_crypto_guidance)
            # Legacy aliases (posture-only; see handler docstrings).
            self._app.router.add_get("/v1/dfy/mechanisms", self._handle_mechanisms)
            self._app.router.add_get("/v1/dfy/signals", self._handle_signals)
            self._app.router.add_get("/v1/dfy/activity", self._handle_activity)
            self._app.router.add_post("/v1/dfy/ingest", self._handle_ingest)
            self._app.router.add_get("/v1/dfy/ingest/status", self._handle_ingest_status)
            self._app.router.add_get("/v1/dfy/snapshot", self._handle_snapshot)
            self._app.router.add_get("/v1/dfy/index-events", self._handle_index_events)
            self._app.router.add_get("/v1/dfy/events", self._handle_dfy_events)

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
