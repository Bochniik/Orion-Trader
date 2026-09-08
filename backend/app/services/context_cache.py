import copy
import os
from datetime import datetime, timezone
from threading import RLock
from time import monotonic


class MarketContextCache:
    """Small in-process cache with stale-on-error fallback for market context."""

    def __init__(self, ttl_seconds=None):
        configured = ttl_seconds if ttl_seconds is not None else os.getenv("MARKET_CONTEXT_TTL_SECONDS", "60")
        try:
            configured = int(configured)
        except (TypeError, ValueError):
            configured = 60
        self.ttl_seconds = max(1, min(configured, 3_600))
        self._entries = {}
        self._lock = RLock()

    def clear(self):
        with self._lock:
            self._entries.clear()

    def load(self, key, loader):
        now = monotonic()
        with self._lock:
            existing = self._entries.get(key)
            if existing and now - existing["stored_at"] <= self.ttl_seconds:
                return copy.deepcopy(existing["value"]), self._metadata(existing, "cached", now)

        try:
            value = loader()
            entry = {
                "value": copy.deepcopy(value),
                "stored_at": monotonic(),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            with self._lock:
                self._entries[key] = entry
            return copy.deepcopy(value), self._metadata(entry, "fresh", monotonic())
        except Exception as exc:
            with self._lock:
                stale = self._entries.get(key)
            if stale:
                metadata = self._metadata(stale, "stale", monotonic())
                metadata["error"] = str(exc)
                return copy.deepcopy(stale["value"]), metadata
            return None, {
                "status": "unavailable",
                "fetched_at": None,
                "age_seconds": None,
                "error": str(exc),
            }

    @staticmethod
    def _metadata(entry, status, now):
        return {
            "status": status,
            "fetched_at": entry["fetched_at"],
            "age_seconds": round(max(0, now - entry["stored_at"]), 2),
        }
