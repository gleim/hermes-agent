#!/usr/bin/env python3
"""Build the DFY intel-pack: a single, self-contained, regenerable corpus bundle.

Hermes is deployed independently of the dfai live traders, so it cannot read the
trader's strategy/config/report files off the local filesystem. This script runs
against a dfai checkout, reads the relevant artifacts, **redacts secrets from
configs**, and emits one content-hashed JSON bundle into the **private**
``dfy-trader-intel`` package (``packages/dfy_intel/dfy_intel/corpus/dfy_corpus.json``).
The Tier-C oracle falls back to that bundle when no local ``DFY_ORACLE_*`` env paths
are configured — it is never committed to the public ``hermes-agent`` repo.

Re-run on every strategy version / report publication to refresh the bundle;
drift is then visible in a single diff instead of hiding across scattered copies.

Usage (all artifact paths are explicit — no baked-in strategy names):
    pip install -e ../dfy-trader-intel/packages/dfy_intel
    python scripts/build_dfy_corpus.py --dfai-root /path/to/dfai \\
        --strategy user_data/versions/.../strategy/MyStrategy.py \\
        --config user_data/versions/.../config/my_config.json \\
        --report-dir reports/publications/my-report-dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse the canonical secret-redaction + JSONC helpers so the vendored bundle
# and the oracle's env-config reader stay byte-for-byte consistent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dfy_intel.corpus_bundle import redact_secrets as _redact  # noqa: E402
from dfy_intel.corpus_bundle import strip_jsonc as _strip_jsonc  # noqa: E402

SCHEMA = "dfy_corpus/v1"

REPORT_EXTS = (".md", ".markdown", ".tex", ".txt")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _git_commit(root: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _read_text(path: Path, trunc: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if trunc and len(text) > trunc:
        text = text[:trunc] + "\n... truncated ...\n"
    return text


def collect_strategies(root: Path, rel_paths: List[str], trunc: int) -> List[Dict[str, Any]]:
    out = []
    for rel in rel_paths:
        p = (root / rel)
        if not p.is_file():
            print(f"  ! strategy not found: {rel}", file=sys.stderr)
            continue
        text = _read_text(p, trunc)
        out.append({"path": rel, "name": p.name, "sha256": _sha256(text), "source": text})
        print(f"  + strategy {rel} ({len(text)} chars)")
    return out


def collect_configs(root: Path, rel_paths: List[str]) -> List[Dict[str, Any]]:
    out = []
    for rel in rel_paths:
        p = (root / rel)
        if not p.is_file():
            print(f"  ! config not found: {rel}", file=sys.stderr)
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        try:
            parsed = json.loads(_strip_jsonc(raw))
            redacted = _redact(parsed)
            content = json.dumps(redacted, indent=2)
            entry = {"path": rel, "name": p.name, "format": "json",
                     "sha256": _sha256(content), "content": content}
            print(f"  + config {rel} (parsed + redacted)")
        except Exception as exc:
            # Could not parse → do NOT vendor raw text (may contain secrets).
            entry = {"path": rel, "name": p.name, "format": "json",
                     "note": f"unparseable config not vendored (secret-safety): {exc}"}
            print(f"  ! config {rel} unparseable; vendored as note only", file=sys.stderr)
        out.append(entry)
    return out


def collect_reports(root: Path, rel_files: List[str], rel_dirs: List[str],
                    max_files: int, trunc: int) -> List[Dict[str, Any]]:
    candidates: List[Path] = []
    for rel in rel_files:
        candidates.append(root / rel)
    for rel in rel_dirs:
        d = root / rel
        if d.is_dir():
            for ext in REPORT_EXTS:
                candidates.extend(sorted(d.glob(f"**/*{ext}")))
    out: List[Dict[str, Any]] = []
    seen = set()
    for p in candidates:
        if len(out) >= max_files:
            break
        if not p.is_file() or p.suffix.lower() not in REPORT_EXTS:
            continue
        rp = str(p.resolve())
        if rp in seen:
            continue
        seen.add(rp)
        text = _read_text(p, trunc)
        rel = str(p.relative_to(root)) if str(p).startswith(str(root)) else p.name
        out.append({"path": rel, "name": p.name, "format": p.suffix.lstrip("."),
                    "sha256": _sha256(text), "source": text})
        print(f"  + report {rel} ({len(text)} chars)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dfai-root", required=True, help="Path to a dfai checkout.")
    ap.add_argument("--strategy", action="append", default=[], help="Strategy .py (repeatable, rel to root).")
    ap.add_argument("--config", action="append", default=[], help="Config .json (repeatable, rel to root).")
    ap.add_argument("--report", action="append", default=[], help="Report file (repeatable, rel to root).")
    ap.add_argument("--report-dir", action="append", default=[], help="Report dir (repeatable, rel to root).")
    ap.add_argument("--out", default=None, help="Output bundle path (default: the installed dfy_intel package's corpus/dfy_corpus.json).")
    ap.add_argument("--strategy-trunc", type=int, default=20000)
    ap.add_argument("--report-trunc", type=int, default=24000)
    ap.add_argument("--max-reports", type=int, default=10)
    args = ap.parse_args()

    root = Path(args.dfai_root).expanduser().resolve()
    if not root.is_dir():
        print(f"error: --dfai-root not a directory: {root}", file=sys.stderr)
        return 2

    strategies = args.strategy
    configs = args.config
    report_files = args.report
    report_dirs = args.report_dir

    if not strategies:
        print("error: pass at least one --strategy (no defaults — secret-safety)", file=sys.stderr)
        return 2

    if args.out:
        out_path = Path(args.out).expanduser()
    else:
        import dfy_intel
        out_path = Path(dfy_intel.__file__).resolve().parent / "corpus" / "dfy_corpus.json"

    print(f"Building DFY corpus from {root}")
    bundle = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"repo": "dfai", "root": "(redacted)", "commit": _git_commit(root)},
        "strategy_sources": collect_strategies(root, strategies, args.strategy_trunc),
        "configs": collect_configs(root, configs) if configs else [],
        "reports": collect_reports(root, report_files, report_dirs, args.max_reports, args.report_trunc),
    }
    payload = json.dumps(bundle, indent=2, ensure_ascii=False)
    bundle_hash = _sha256(payload)
    bundle["bundle_sha256"] = bundle_hash
    payload = json.dumps(bundle, indent=2, ensure_ascii=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")
    print(f"\nWrote {out_path}")
    print(f"  strategies={len(bundle['strategy_sources'])} "
          f"configs={len(bundle['configs'])} reports={len(bundle['reports'])}")
    print(f"  commit={bundle['source']['commit']} bundle_sha256={bundle_hash[:12]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
