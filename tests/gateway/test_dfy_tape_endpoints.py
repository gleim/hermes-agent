"""Public tape-guide / legend / translate / persona HTTP surface.

Kept separate from test_dfy_tape.py so the pure-module tests still run when
aiohttp isn't installed (aiohttp ships with the messaging/web extras, not dev).
"""

import pytest

pytest.importorskip("aiohttp")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.config import PlatformConfig  # noqa: E402
from gateway.dfy_tape import EXAMPLE_TAPE  # noqa: E402
from gateway.platforms.api_server import (  # noqa: E402
    APIServerAdapter,
    cors_middleware,
    security_headers_middleware,
)
from gateway.platforms.x402_intel import X402IntelAdapter, _cors  # noqa: E402


def _x402_app() -> "web.Application":
    adapter = X402IntelAdapter(PlatformConfig(enabled=True))
    app = web.Application(middlewares=[_cors])
    app.router.add_get("/v1/dfy/tape-guide", adapter._handle_tape_guide)
    app.router.add_get("/v1/dfy/legend", adapter._handle_legend)
    app.router.add_get("/v1/dfy/persona", adapter._handle_persona)
    app.router.add_get("/v1/dfy/translate", adapter._handle_translate)
    app.router.add_post("/v1/dfy/translate", adapter._handle_translate)
    return app


def _api_app(api_key: str = "sk-secret") -> "web.Application":
    extra = {"key": api_key} if api_key else {}
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra=extra))
    mws = [mw for mw in (cors_middleware, security_headers_middleware) if mw is not None]
    app = web.Application(middlewares=mws)
    app["api_server_adapter"] = adapter
    app.router.add_get("/v1/dfy/tape-guide", adapter._handle_dfy_tape_guide)
    return app


class TestTapeGuideX402:
    @pytest.mark.asyncio
    async def test_browser_accept_is_html(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get(
                "/v1/dfy/tape-guide",
                headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
            )
            assert resp.status == 200
            assert "text/html" in resp.content_type
            text = await resp.text()
            assert text.startswith("<!DOCTYPE html>")
            assert "How to read the tape" in text
            assert "Hyperliquid" in text
            assert resp.headers.get("Vary") == "Accept"

    @pytest.mark.asyncio
    async def test_json_accept_is_json(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get(
                "/v1/dfy/tape-guide", headers={"Accept": "application/json"}
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["title"] == "How to read the tape"
            assert body["translation"]["live_card"] == "HYPE1D"
            assert body["translation"]["exit_hours"] == 15
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    @pytest.mark.asyncio
    async def test_format_query_forces_html(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get(
                "/v1/dfy/tape-guide?format=html",
                headers={"Accept": "application/json"},
            )
            assert resp.status == 200
            assert "text/html" in resp.content_type


class TestTapeGuideApiServer:
    @pytest.mark.asyncio
    async def test_public_without_api_key(self):
        async with TestClient(TestServer(_api_app(api_key="sk-secret"))) as cli:
            resp = await cli.get(
                "/v1/dfy/tape-guide",
                headers={"Accept": "text/html"},
            )
            assert resp.status == 200
            assert "text/html" in resp.content_type
            text = await resp.text()
            assert "<!DOCTYPE html>" in text
            assert "Walk it" in text

    @pytest.mark.asyncio
    async def test_machines_still_get_json(self):
        async with TestClient(TestServer(_api_app())) as cli:
            resp = await cli.get(
                "/v1/dfy/tape-guide", headers={"Accept": "application/json"}
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["title"] == "How to read the tape"
            assert "Not a buy or sell." in body["not"]


class TestLegendEndpoint:
    @pytest.mark.asyncio
    async def test_legend_json(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get("/v1/dfy/legend")
            assert resp.status == 200
            body = await resp.json()
            assert body["title"] == "How to read the tape"
            assert len(body["glossary"]) >= 8
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    @pytest.mark.asyncio
    async def test_legend_markdown(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get("/v1/dfy/legend?format=markdown")
            assert resp.status == 200
            assert resp.content_type == "text/markdown"
            assert "How to read the tape" in await resp.text()


class TestPersonaEndpoint:
    @pytest.mark.asyncio
    async def test_persona_public_for_external_bot(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get("/v1/dfy/persona")
            assert resp.status == 200
            body = await resp.json()
            assert "datafi" in body["persona"].lower()
            assert "not investment advice" in body["persona"].lower()
            assert len(body["glossary"]) >= 8
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"


class TestTranslateEndpoint:
    @pytest.mark.asyncio
    async def test_translate_post_text(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.post("/v1/dfy/translate", json={"text": EXAMPLE_TAPE})
            assert resp.status == 200
            body = await resp.json()
            assert body["decoded"]["symbol"] == "HYPE"
            assert "Hyperliquid" in body["translation"]
            assert "one-day" in body["translation"]

    @pytest.mark.asyncio
    async def test_translate_get_text(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.get("/v1/dfy/translate", params={"text": EXAMPLE_TAPE})
            assert resp.status == 200
            body = await resp.json()
            assert "Hyperliquid" in body["translation"]

    @pytest.mark.asyncio
    async def test_translate_card_object(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.post(
                "/v1/dfy/translate",
                json={"card": {"symbol": "ETH", "horizon": "4H", "side": "short"}},
            )
            assert resp.status == 200
            body = await resp.json()
            assert "Ethereum" in body["translation"] or "ETH" in body["translation"]

    @pytest.mark.asyncio
    async def test_translate_persona_lead(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.post(
                "/v1/dfy/translate", json={"text": EXAMPLE_TAPE, "style": "lead"}
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["style"] == "lead"
            assert "Hyperliquid" in body["message"]
            assert not body["message"].startswith("New here?")

    @pytest.mark.asyncio
    async def test_translate_requires_input(self):
        async with TestClient(TestServer(_x402_app())) as cli:
            resp = await cli.post("/v1/dfy/translate", json={})
            assert resp.status == 400
