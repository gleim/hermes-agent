"""Loader for the vendored DFY intel-pack bundle (``dfy_intel/corpus/dfy_corpus.json``).

The bundle is a self-contained, regenerable snapshot of the dfai strategy sources,
(secret-redacted) configs, and published reports, produced by
``scripts/build_dfy_corpus.py``. Because Hermes is deployed independently of the
live traders, the oracle falls back to this bundle whenever no local
``DFY_ORACLE_*`` env paths are configured — so the chat GUI gets strategy- and
report-aware analysis with zero filesystem coupling to dfai.

Also hosts the shared secret-redaction helpers used by both the build script and
the oracle's on-the-fly env-config reader.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_BUNDLE_PATH = Path(__file__).resolve().parent / "corpus" / "dfy_corpus.json"

_cache: Dict[str, Any] = {"mtime": None, "data": None}

# Config keys whose values must never leave the trader host (case-insensitive
# substring match on the key). Kept in sync with scripts/build_dfy_corpus.py.
SECRET_KEY_HINTS = (
    "token", "secret", "password", "passwd", "webhook", "api_key", "apikey",
    "jwt", "private", "mnemonic", "seed", "credential",
)
REDACTED = "***REDACTED***"


# --------------------------------------------------------------------------
# Shared helpers (secret-safety) — imported by the build script too.
# --------------------------------------------------------------------------


def strip_jsonc(text: str) -> str:
    """Best-effort JSONC → JSON: drop // and /* */ comments + trailing commas."""
    out: List[str] = []
    in_str = False
    esc = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def redact_secrets(obj: Any) -> Any:
    """Recursively replace secret-looking config values with ``***REDACTED***``."""
    if isinstance(obj, dict):
        red: Dict[str, Any] = {}
        for k, v in obj.items():
            if any(h in str(k).lower() for h in SECRET_KEY_HINTS):
                red[k] = REDACTED if v not in (None, "", [], {}) else v
            else:
                red[k] = redact_secrets(v)
        return red
    if isinstance(obj, list):
        return [redact_secrets(x) for x in obj]
    return obj


# --------------------------------------------------------------------------
# Bundle access
# --------------------------------------------------------------------------


def bundle_path() -> Path:
    return _BUNDLE_PATH


def load_bundle() -> Optional[Dict[str, Any]]:
    """Return the parsed bundle (mtime-cached), or None if absent/invalid."""
    try:
        mtime = _BUNDLE_PATH.stat().st_mtime
    except OSError:
        return None
    if _cache["mtime"] == mtime and _cache["data"] is not None:
        return _cache["data"]
    try:
        data = json.loads(_BUNDLE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _cache["mtime"] = mtime
    _cache["data"] = data
    return data


def _provenance_tag(bundle: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "from_bundle": True,
        "bundle_generated_at": bundle.get("generated_at"),
        "bundle_source_commit": (bundle.get("source") or {}).get("commit"),
    }


def bundle_strategy_sources() -> List[Dict[str, Any]]:
    bundle = load_bundle()
    if not bundle:
        return []
    tag = _provenance_tag(bundle)
    out = []
    for s in bundle.get("strategy_sources", []):
        out.append({"path": s.get("path"), "kind": "strategy",
                    "source": s.get("source", ""), **tag})
    return out


def bundle_report_sources() -> List[Dict[str, Any]]:
    bundle = load_bundle()
    if not bundle:
        return []
    tag = _provenance_tag(bundle)
    out = []
    for r in bundle.get("reports", []):
        entry = {"path": r.get("path"), "kind": "report",
                 "format": r.get("format"), **tag}
        if "source" in r:
            entry["source"] = r["source"]
        else:
            entry["note"] = r.get("note")
        out.append(entry)
    return out


def bundle_configs() -> List[Dict[str, Any]]:
    bundle = load_bundle()
    if not bundle:
        return []
    tag = _provenance_tag(bundle)
    out = []
    for c in bundle.get("configs", []):
        entry = {"path": c.get("path"), "name": c.get("name"),
                 "format": c.get("format"), **tag}
        if "content" in c:
            entry["content"] = c["content"]
        else:
            entry["note"] = c.get("note")
        out.append(entry)
    return out


def bundle_provenance() -> Optional[Dict[str, Any]]:
    bundle = load_bundle()
    if not bundle:
        return None
    return {
        "generated_at": bundle.get("generated_at"),
        "source": bundle.get("source"),
        "bundle_sha256": bundle.get("bundle_sha256"),
        "counts": {
            "strategy_sources": len(bundle.get("strategy_sources", [])),
            "configs": len(bundle.get("configs", [])),
            "reports": len(bundle.get("reports", [])),
        },
    }
