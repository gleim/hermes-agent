"""Shared DFY strategy-oracle context builder.

Assembles a single analysis payload from three sources so any Hermes surface
(Discord ``/dfy-oracle`` slash command, the ``dfy_oracle`` agent tool used by the
web / TUI / CLI chat, or the x402 gateway) can give strategy-aware, report-aware
guidance from the same logic:

  1. Live DFY feed    — ``dfy_intel.store`` (runner meta, mechanisms incl. open
                        trades + per-pair indicators, recent signals, activity).
  2. Strategy sources — the ``.py`` files the bot actually loads
                        (``DFY_ORACLE_STRATEGY_PATHS`` / ``DFY_ORACLE_STRATEGY_DIR``).
  3. Published reports — analytic write-ups / papers (markdown, LaTeX, text, and
                        optionally PDF) via ``DFY_ORACLE_REPORT_PATHS`` /
                        ``DFY_ORACLE_REPORT_DIR``.

Env (all optional; the builder degrades gracefully when unset):
  DFY_ORACLE_STRATEGY_PATHS   comma-separated ``.py`` file paths
  DFY_ORACLE_STRATEGY_DIR     directory; first N ``*.py`` files (alphabetical)
  DFY_ORACLE_REPORT_PATHS     comma-separated report file paths (.md/.tex/.txt/.pdf)
  DFY_ORACLE_REPORT_DIR       directory; globbed recursively for report files
  DFY_ORACLE_MAX_STRATEGY_FILES   default 8
  DFY_ORACLE_STRATEGY_TRUNC       default 14000 (chars per strategy file)
  DFY_ORACLE_MAX_REPORT_FILES     default 6
  DFY_ORACLE_REPORT_TRUNC         default 16000 (chars per report file)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPORT_EXTS = (".md", ".tex", ".txt", ".markdown")
_REPORT_GLOBS = ("**/*.md", "**/*.markdown", "**/*.tex", "**/*.txt")


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except (TypeError, ValueError):
        return default


def _csv_paths(env_name: str) -> List[str]:
    out: List[str] = []
    for entry in (os.getenv(env_name, "") or "").split(","):
        p = entry.strip()
        if p:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Strategy sources
# ---------------------------------------------------------------------------


def collect_strategy_sources() -> List[Dict[str, Any]]:
    """Read the strategy ``.py`` files configured via env.

    Mirrors (and supersedes) the old discord-only collector: explicit paths from
    ``DFY_ORACLE_STRATEGY_PATHS`` plus up to 12 ``*.py`` from
    ``DFY_ORACLE_STRATEGY_DIR``, capped at ``DFY_ORACLE_MAX_STRATEGY_FILES`` total
    and truncated to ``DFY_ORACLE_STRATEGY_TRUNC`` chars each.
    """
    max_files = _env_int("DFY_ORACLE_MAX_STRATEGY_FILES", 8)
    trunc = _env_int("DFY_ORACLE_STRATEGY_TRUNC", 14000)

    paths: List[str] = _csv_paths("DFY_ORACLE_STRATEGY_PATHS")
    strategy_dir = (os.getenv("DFY_ORACLE_STRATEGY_DIR", "") or "").strip()
    if strategy_dir:
        d = Path(strategy_dir).expanduser()
        if d.is_dir():
            paths.extend(str(x) for x in sorted(d.glob("*.py"))[:12])

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in paths[:max_files]:
        path = Path(raw).expanduser()
        try:
            if not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > trunc:
                text = text[:trunc] + "\n# ... truncated ...\n"
            out.append({"path": resolved, "kind": "strategy", "source": text})
        except OSError:
            continue

    # Independent-deployment fallback: no local strategy files configured/found,
    # so serve the vendored intel-pack bundle.
    if not out:
        from dfy_intel.corpus_bundle import bundle_strategy_sources

        return bundle_strategy_sources()
    return out


# ---------------------------------------------------------------------------
# Published reports
# ---------------------------------------------------------------------------


def _read_pdf_text(path: Path, trunc: int) -> Optional[str]:
    """Best-effort PDF text extraction; returns None if no extractor is available."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return None
    try:
        reader = PdfReader(str(path))
        chunks: List[str] = []
        total = 0
        for page in reader.pages:
            t = page.extract_text() or ""
            chunks.append(t)
            total += len(t)
            if total > trunc:
                break
        return "\n".join(chunks)
    except Exception as exc:  # corrupt / encrypted / parser error
        logger.debug("dfy oracle pdf read %s: %s", path, exc)
        return None


def _discover_report_paths() -> List[Path]:
    paths: List[Path] = [Path(p).expanduser() for p in _csv_paths("DFY_ORACLE_REPORT_PATHS")]
    report_dir = (os.getenv("DFY_ORACLE_REPORT_DIR", "") or "").strip()
    if report_dir:
        d = Path(report_dir).expanduser()
        if d.is_dir():
            globbed: List[Path] = []
            for pattern in _REPORT_GLOBS:
                globbed.extend(d.glob(pattern))
            # Also pick up PDFs from the dir only when an extractor may exist.
            globbed.extend(d.glob("**/*.pdf"))
            paths.extend(sorted(set(globbed)))
    return paths


def collect_report_sources() -> List[Dict[str, Any]]:
    """Read published analytic reports configured via env.

    Markdown / LaTeX / text are read directly; PDFs are extracted when a
    ``pypdf``/``PyPDF2`` backend is installed (otherwise skipped with a note).
    Capped at ``DFY_ORACLE_MAX_REPORT_FILES`` files, ``DFY_ORACLE_REPORT_TRUNC``
    chars each.
    """
    max_files = _env_int("DFY_ORACLE_MAX_REPORT_FILES", 6)
    trunc = _env_int("DFY_ORACLE_REPORT_TRUNC", 16000)

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for path in _discover_report_paths():
        if len(out) >= max_files:
            break
        try:
            if not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                text = _read_pdf_text(path, trunc)
                if text is None:
                    out.append({
                        "path": resolved,
                        "kind": "report",
                        "format": "pdf",
                        "note": "PDF text extraction unavailable (install pypdf to ingest).",
                    })
                    continue
            elif suffix in _REPORT_EXTS:
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                continue
            if len(text) > trunc:
                text = text[:trunc] + "\n... truncated ...\n"
            out.append({
                "path": resolved,
                "kind": "report",
                "format": suffix.lstrip(".") or "text",
                "source": text,
            })
        except OSError:
            continue

    # Independent-deployment fallback: serve vendored reports from the bundle.
    if not out:
        from dfy_intel.corpus_bundle import bundle_report_sources

        return bundle_report_sources()
    return out


def collect_configs() -> List[Dict[str, Any]]:
    """Read bot configs (secret-redacted). Env ``DFY_ORACLE_CONFIG_PATHS`` for
    co-located dev; otherwise the vendored bundle (already redacted)."""
    from dfy_intel.corpus_bundle import bundle_configs, redact_secrets, strip_jsonc

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _csv_paths("DFY_ORACLE_CONFIG_PATHS"):
        path = Path(raw).expanduser()
        try:
            if not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            import json as _json

            parsed = _json.loads(strip_jsonc(path.read_text(encoding="utf-8", errors="replace")))
            content = _json.dumps(redact_secrets(parsed), indent=2)
            out.append({"path": resolved, "name": path.name, "format": "json", "content": content})
        except Exception as exc:  # never vendor unparseable config raw (secrets)
            out.append({"path": str(path), "name": path.name, "format": "json",
                        "note": f"unparseable config not shown (secret-safety): {exc}"})

    if not out:
        return bundle_configs()
    return out


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def build_oracle_payload(
    focus: str = "",
    *,
    signals_limit: int = 40,
    activity_limit: int = 25,
    include_sources: bool = True,
    include_reports: bool = True,
    include_configs: bool = True,
) -> Dict[str, Any]:
    """Assemble the full oracle analysis payload from feed + sources + reports."""
    from dfy_intel.corpus_bundle import bundle_provenance
    from dfy_intel.store import get_dfy_store

    store = get_dfy_store()
    mechanisms = store.get_mechanisms()
    payload: Dict[str, Any] = {
        "role": "dfy_strategy_oracle",
        "focus": (focus or "").strip(),
        "runner": mechanisms.get("runner"),
        "mechanisms": mechanisms,
        "signals_recent": store.get_signals(limit=signals_limit),
        "activity_recent": store.get_activity(limit=activity_limit),
    }
    if include_sources:
        payload["strategy_sources"] = collect_strategy_sources()
    if include_reports:
        payload["reports"] = collect_report_sources()
    if include_configs:
        payload["configs"] = collect_configs()
    prov = bundle_provenance()
    if prov is not None:
        payload["corpus_provenance"] = prov
    return payload


ORACLE_GUIDANCE = (
    "You are the **DFY strategy oracle** for this trading stack. You understand "
    "strategy implementation internals: indicator pipelines, entry/exit columns, "
    "tunable parameters, risk (ROI/stoploss), and how live indicator snapshots "
    "relate to recent signals — and you can ground analysis in the published "
    "analytic reports/papers when provided."
)


def build_oracle_instructions(focus: str, payload_json: str) -> str:
    """Render the oracle prompt (shared by the Discord slash command)."""
    return f"""[DFY Strategy Oracle — internal analysis]

{ORACLE_GUIDANCE}

User focus (optional): {(focus or '').strip()!r}

Use the JSON block below (strategy source files, published reports, live DFY
mechanisms including open trades and per-pair indicators, recent signals,
activity). Give **intelligent, specific** insight:
1. What the active logic is doing vs. the code (entries/exits, thresholds).
2. How the **latest signals** line up with that logic; call out divergences or confirmation.
3. How live behavior relates to the **published reports/theses** (e.g. omega attribution, A/B results).
4. Risks, anomalies, or data gaps.
5. 2–4 concrete checks the operator could run next.

Be concise but technical; cite indicator/signal keys and report sections from the data when possible.

--- DFY_CONTEXT_JSON ---
{payload_json}
--- END ---"""
