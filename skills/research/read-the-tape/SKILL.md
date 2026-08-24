---
name: read-the-tape
description: Translate DataFi tape jargon for first-time readers.
version: 1.0.0
author: gleim + Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [DataFi, GM, tape, Live, Grok]
    category: research
    related_skills: []
---

# Read the Tape Skill

Translate a cryptic DataFi / GM! Live blurb into plain language for someone
auditing a ticker for the first time or reading a promo on X. This skill does
not publish feed construction and is not a trade ticket.

## When to Use

- A user pastes `HYPE1D`, `last-action`, `c0.58`, `held`, or `GM! tape, standard`
- Someone asks what the Live page cells mean
- Grok / GROUP / COMPUTER needs a relatability pass before house jargon

## Prerequisites

- `dfy_tape_guide` is on the core / dfy toolset (no API key)
- Current house cards and identity live at `https://datafi.live/soul.md`
- Checkout / mint / MCP live at `https://datafi.live/skills.md` — fetch those
  with `web_extract` when the user asks about paying or current card numbers

## How to Run

1. Call `dfy_tape_guide` with the pasted blurb (or with no args for the glossary).
2. Lead with the plain reading. Then name the jargon in the same breath.
3. If they need current frozen cards, `web_extract` `https://datafi.live/soul.md`.
4. Point humans at `https://datafi.live/live`. Do not dump desk internals.

## Quick Reference

| Phrase | Plain |
|---|---|
| `HYPE1D` | Hyperliquid on the one-day book |
| `print 0.634` | Unsigned conviction in [0, 1]; 0.5 is even |
| `last-action +0.413 / c0.58` | Signed lean and confidence when the event fired |
| `live card` | The one name that currently cleared both bars |
| `held` | Quiet book — not broken, not a sell |
| `exit in ~15h` | Horizon clock still open |
| `standard` | House-default rung |

## Procedure

1. Treat the Live page as a probability-density tape, not a price chart.
2. Prefer the **standard** rung unless the caller asked for purist or active.
3. An event needs both bars: `|signed| ≥ band` and `confidence ≥ min_conf`.
4. Held windows are information. Do not invent a trade from silence.
5. Close public reads with: measurement is public, method stays private, not investment advice.

## Pitfalls

- Do not invent method, omega, IC, PnL, yield, or buy/sell.
- Do not impersonate DataDeFi (`datadefi.ai`).
- Do not tell humans to use slash commands.
- Do not keep a stale `soul.md` / `skills.md` — fetch again before you act.
- Do not put narrator / index_event paragraphs on the Live page.

## Verification

- `dfy_tape_guide` on the sample HYPE1D promo returns a plain reading that
  names Hyperliquid, the one-day clock, +0.413 / 0.58, ~15h, and print 0.634.
- No buy/sell or method claims in the answer.
