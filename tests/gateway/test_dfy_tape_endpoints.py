"""x402 gateway endpoint tests for the public "read the tape" surface.

Kept separate from test_dfy_tape.py so the pure-module tests still run when
aiohttp isn't installed (aiohttp ships with the messaging/web extras, not dev).
"""

import pytest

pytest.importorskip("aiohttp")

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.config import PlatformConfig  # noqa: E402
from gateway.platforms.x402_intel import X402IntelAdapter, _cors  # noqa: E402

EXAMPLE_TAPE = """GM! tape, standard.

HYPE1D is the live card: last-action +0.413 / c0.58, long. Still open, 1D exit in ~15h. Current print 0.634.

Core 1D held. HYPE90M 0.553, held. Measurement is public. Method stays private. Not investment advice.
datafi.live"""


def _legend_app() -> "web.Application":
    adapter = X402IntelAdapter(PlatformConfig(enabled=True))
    app = web.Application(middlewares=[_cors])
    app.router.add_get("/v1/dfy/legend", adapter._handle_legend)
    app.router.add_get("/v1/dfy/translate", adapter._handle_translate)
    app.router.add_post("/v1/dfy/translate", adapter._handle_translate)
    return app


class TestLegendEndpoint:
    @pytest.mark.asyncio
    async def test_legend_json(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.get("/v1/dfy/legend")
            assert resp.status == 200
            body = await resp.json()
            assert body["title"] == "How to Read the Tape"
            assert len(body["glossary"]) >= 8
            # public, CORS-enabled surface
            assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    @pytest.mark.asyncio
    async def test_legend_markdown(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.get("/v1/dfy/legend?format=markdown")
            assert resp.status == 200
            assert resp.content_type == "text/markdown"
            assert "How to Read the Tape" in await resp.text()


class TestTranslateEndpoint:
    @pytest.mark.asyncio
    async def test_translate_post_text(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.post("/v1/dfy/translate", json={"text": EXAMPLE_TAPE})
            assert resp.status == 200
            body = await resp.json()
            assert body["decoded"]["symbol"] == "HYPE"
            assert "1-day" in body["translation"]

    @pytest.mark.asyncio
    async def test_translate_get_text(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.get("/v1/dfy/translate", params={"text": EXAMPLE_TAPE})
            assert resp.status == 200
            body = await resp.json()
            assert "HYPE" in body["translation"]

    @pytest.mark.asyncio
    async def test_translate_card_object(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.post(
                "/v1/dfy/translate",
                json={"card": {"symbol": "ETH", "horizon": "4H", "side": "short"}},
            )
            assert resp.status == 200
            body = await resp.json()
            assert "ETH" in body["translation"]
            assert "4-hour" in body["translation"]

    @pytest.mark.asyncio
    async def test_translate_persona_lead(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.post(
                "/v1/dfy/translate", json={"text": EXAMPLE_TAPE, "style": "lead"}
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["style"] == "lead"
            assert body["message"].startswith("New here?")

    @pytest.mark.asyncio
    async def test_translate_requires_input(self):
        async with TestClient(TestServer(_legend_app())) as cli:
            resp = await cli.post("/v1/dfy/translate", json={})
            assert resp.status == 400
