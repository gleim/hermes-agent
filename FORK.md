# Hermes x402 / DFY fork

This directory extends [Nous Research Hermes Agent](https://github.com/NousResearch/hermes-agent) to:

1. **Expose the DFY feed over HTTP** — strategy mechanisms (incl. open trades + latest indicators per pair), signals, and activity — behind an [x402](https://docs.cdp.coinbase.com/x402/docs/http-402)-style **402 Payment Required** flow.
2. **Record inbound settlements** for linkage to **Virtuals.io–style agent token** distribution (Uniswap metadata in ledger rows; on-chain execution is external).
3. **Discord** — `/dfy-*` slash commands, **`/dfy-oracle`** (feed + strategy sources), and **`/dfy-live`** (read-only panels aligned with the reference Telegram RPC bundle, fetched from the runner REST API, wrapped in Hermes commentary).

**dfai** strategies push into the same store via `DfyHermesIntelMixin` (`dfai/user_data/strategies/dfy_hermes_intel_mixin.py`). Point **`DFY_ORACLE_STRATEGY_PATHS`** at the same `.py` files your bot loads so the oracle matches production logic.

### Discord slash command catalog

Registered in `gateway/platforms/discord.py` (`_register_slash_commands`). Installed Hermes **skills** may add more dynamic slash commands at runtime.

| Command | Parameters | Description |
|--------|------------|-------------|
| `/new` | — | Start a new conversation (dispatches `/reset`) |
| `/reset` | — | Reset your Hermes session |
| `/model` | `name` (optional) | Show or change the model |
| `/reasoning` | `effort` (optional) | Reasoning effort: xhigh, high, medium, low, minimal, none |
| `/personality` | `name` (optional) | Set or list personalities |
| `/retry` | — | Retry your last message |
| `/undo` | — | Remove the last exchange |
| `/status` | — | Hermes session status |
| `/sethome` | — | Set this chat as the home channel |
| `/stop` | — | Stop the running Hermes agent |
| `/compress` | — | Compress conversation context |
| `/title` | `name` (optional) | Set or show session title |
| `/resume` | `name` (optional) | Resume a named session or list sessions |
| `/usage` | — | Token usage for this session |
| `/provider` | — | Show available providers |
| `/help` | — | Show available commands |
| `/insights` | `days` (default 7) | Usage insights and analytics |
| `/reload-mcp` | — | Reload MCP servers from config |
| `/voice` | `mode` (choices) | Voice: channel, leave, on, tts, off, status |
| `/update` | — | Update Hermes Agent to latest |
| `/thread` | `name`, `message` (optional), `auto_archive_duration` | Create a thread and optional first message |
| `/dfy-mechanisms` | — | DFY mechanisms JSON (ephemeral; mirrors x402 `/v1/dfy/mechanisms`) |
| `/dfy-signals` | `limit` (1–200, default 25) | Recent DFY signals (mirrors x402 `/v1/dfy/signals`) |
| `/dfy-activity` | `limit` (1–200, default 25) | Recent DFY activity (mirrors x402 `/v1/dfy/activity`) |
| `/dfy-oracle` | `focus` (optional) | Strategy oracle: agent analyzes DFY feed + configured strategy sources |
| `/dfy-live` | `view` (choice), `pair` (optional), `timescale` (default 7) | Fetches runner REST JSON for the selected panel (status, profit, balance, performance, trades, daily/weekly/monthly, stats, count, locks, health, version, sysinfo, whitelist, entries/exits/mix_tags, config, logs) and asks Hermes for strategy-aware live analysis |

**Permissioning:** `DISCORD_ALLOWED_USERS` (and optional `DISCORD_DFY_ROLE_IDS` for DFY commands). DFY JSON replies are ephemeral.

**Runner REST (for `/dfy-live`):** enable `api_server` on the dfai runner, then on the Hermes host set **`DFY_FT_API_URL`** (e.g. `http://127.0.0.1:8080/api/v1`), **`DFY_FT_API_USER`**, **`DFY_FT_API_PASSWORD`**. Hermes calls **GET** endpoints only (no Discord-triggered force-exit / stop / start).

## Layout

| Piece | Location |
|--------|----------|
| In-memory DFY store | `dfy_intel/store.py` (`get_dfy_store`, alias `get_intel_store`) |
| x402 helpers | `dfy_intel/x402_payment.py` |
| Snapshot file reader | `dfy_intel/dfy_snapshot_bridge.py` |
| Runner REST client (read-only) | `dfy_intel/ft_rest_client.py` |
| Virtuals / Uniswap ledger | `dfy_intel/virtuals_bridge.py` |
| aiohttp gateway | `gateway/platforms/x402_intel.py` |
| Discord | DFY slash commands in `gateway/platforms/discord.py` |

## dfai wiring

1. Mixin **first** in the class declaration: `class MyStrat(DfyHermesIntelMixin, IStrategy):`
2. At the end of **`populate_indicators`**, call `self.dfy_intel_on_indicators(dataframe, metadata)` (already added for `DfyExplore` / `DfyFoundation` / `QfiExtremaActive`).
3. **Cross-process feed:** the live runner writes **`dfy_live_snapshot.json`** (default `~/.hermes/dfy_feed/`; override with **`DFY_INTEL_SNAPSHOT_PATH`** on both sides). Hermes merges that file into `get_dfy_store()` whenever Discord or x402 serves DFY data.

Optional env:

- `DFY_INTEL_OPEN_TRADE_INTERVAL` (default `5`) — seconds between open-trade snapshots
- `DFY_INTEL_INDICATOR_INTERVAL` (default `30`) — per-pair throttle for indicator pushes
- `DFY_INTEL_MAX_COLUMNS` (default `90`) — cap columns serialized from the last candle

## Feeding from Python

```python
from dfy_intel.store import get_dfy_store

s = get_dfy_store()
s.replace_mechanisms({"regime": "trend"})
s.append_signal({"pair": "BTC/USDT", "rsi": 28.1})
s.append_activity({"event": "entry", "side": "long"})
```

## x402 HTTP gateway

```bash
export X402_INTEL_ENABLED=true
export X402_INTEL_HOST=0.0.0.0
export X402_INTEL_PORT=8643
```

**Production:** set `X402_PAYTO_ADDRESS`, `X402_NETWORK`, `X402_MAX_AMOUNT_ATOMIC`, and align verifier behavior with [x402 HTTP 402](https://docs.cdp.coinbase.com/x402/docs/http-402) (these routes are **GET**; extend `verify_settled_payment` if your facilitator expects headers only).

**Development:** `X402_SKIP_PAYMENT=true`, or `X402_RELAXED_AUTH=true` + `X402_DEV_SHARED_SECRET` / `X-Intel-Payment-MAC`.

Endpoints:

- `GET /health`
- `GET /v1/dfy/mechanisms`
- `GET /v1/dfy/signals?limit=50`
- `GET /v1/dfy/activity?limit=50`

Settled requests append lines to `~/.hermes/dfy_feed/virtuals_settlement_ledger.jsonl`.

## `/dfy-oracle` (Discord)

Hermes receives a single user message bundling JSON context. Configure strategy sources the oracle can read:

- **`DFY_ORACLE_STRATEGY_PATHS`** — comma-separated absolute paths to `.py` strategy files (e.g. your active strategy module).
- **`DFY_ORACLE_STRATEGY_DIR`** — directory of `.py` files (first 12 alphabetically, max 8 total with paths).

Role gate: **`DISCORD_DFY_ROLE_IDS`** (legacy: `DISCORD_INTEL_ROLE_IDS`).

## Virtuals + Uniswap

`VIRTUALS_AGENT_TOKEN_ADDRESS`, `VIRTUALS_CHAIN_ID`, `UNISWAP_V3_ROUTER` / `UNISWAP_UNIVERSAL_ROUTER`, `VIRTUALS_QUOTE_TOKEN`.

Use `dfy_intel.virtuals_bridge.planned_swap_intent(row)` for keeper-side swaps.

## Governance

`git remote add upstream https://github.com/NousResearch/hermes-agent.git` and merge as needed. Changes are additive plus small edits to `gateway/config.py`, `gateway/run.py`, `gateway/platforms/discord.py`, and `pyproject.toml`.
