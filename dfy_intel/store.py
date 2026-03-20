"""Thread-safe in-memory store for DFY strategy feed snapshots."""

from __future__ import annotations

import copy
import threading
from typing import Any, Dict, List, Optional


class DfyIntelStore:
    """Granular strategy state: mechanisms, price signals, trading activity."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mechanisms: Dict[str, Any] = {}
        self._signals: List[Dict[str, Any]] = []
        self._activity: List[Dict[str, Any]] = []
        self._signals_max = 500
        self._activity_max = 500
        self._dfy_file_signals: List[Dict[str, Any]] = []
        self._dfy_file_activity: List[Dict[str, Any]] = []
        self._dfy_snap_mtime: float = 0.0

    def _merge_dfy_snapshot_file(self) -> None:
        from dfy_intel.dfy_snapshot_bridge import dfy_snapshot_mtime, read_dfy_snapshot

        mt = dfy_snapshot_mtime()
        if mt is None:
            return
        if mt == self._dfy_snap_mtime:
            return
        data = read_dfy_snapshot()
        if not isinstance(data, dict):
            return
        self._dfy_snap_mtime = mt
        with self._lock:
            fm = data.get("mechanisms")
            if isinstance(fm, dict):
                self._mechanisms.update(copy.deepcopy(fm))
            fs = data.get("signals")
            if isinstance(fs, list):
                self._dfy_file_signals = [copy.deepcopy(x) for x in fs]
            fa = data.get("activity")
            if isinstance(fa, list):
                self._dfy_file_activity = [copy.deepcopy(x) for x in fa]

    def replace_mechanisms(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self._mechanisms = copy.deepcopy(data)

    def patch_mechanisms(self, patch: Dict[str, Any]) -> None:
        with self._lock:
            self._mechanisms.update(copy.deepcopy(patch))

    def set_pair_latest_indicators(self, pair: str, data: Dict[str, Any]) -> None:
        """Merge latest indicator snapshot per pair under mechanisms['latest_indicators']."""
        with self._lock:
            li = self._mechanisms.setdefault("latest_indicators", {})
            if not isinstance(li, dict):
                li = {}
                self._mechanisms["latest_indicators"] = li
            li[pair] = copy.deepcopy(data)

    def append_signal(self, item: Dict[str, Any]) -> None:
        with self._lock:
            self._signals.append(copy.deepcopy(item))
            if len(self._signals) > self._signals_max:
                self._signals = self._signals[-self._signals_max :]

    def append_activity(self, item: Dict[str, Any]) -> None:
        with self._lock:
            self._activity.append(copy.deepcopy(item))
            if len(self._activity) > self._activity_max:
                self._activity = self._activity[-self._activity_max :]

    def get_mechanisms(self) -> Dict[str, Any]:
        self._merge_dfy_snapshot_file()
        with self._lock:
            return copy.deepcopy(self._mechanisms)

    def get_signals(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        self._merge_dfy_snapshot_file()
        with self._lock:
            combined = list(self._signals) + list(self._dfy_file_signals)
        if limit is not None:
            return combined[-limit:]
        return combined

    def get_activity(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        self._merge_dfy_snapshot_file()
        with self._lock:
            combined = list(self._activity) + list(self._dfy_file_activity)
        if limit is not None:
            return combined[-limit:]
        return combined

    def snapshot(self) -> Dict[str, Any]:
        self._merge_dfy_snapshot_file()
        with self._lock:
            return {
                "mechanisms": copy.deepcopy(self._mechanisms),
                "signals": copy.deepcopy(self._signals) + copy.deepcopy(self._dfy_file_signals),
                "activity": copy.deepcopy(self._activity) + copy.deepcopy(self._dfy_file_activity),
            }


_STORE: Optional[DfyIntelStore] = None
_STORE_LOCK = threading.Lock()


def get_dfy_store() -> DfyIntelStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = DfyIntelStore()
        return _STORE


def get_intel_store() -> DfyIntelStore:
    """Backward-compatible alias."""
    return get_dfy_store()


TradingIntelStore = DfyIntelStore  # backward-compatible alias
