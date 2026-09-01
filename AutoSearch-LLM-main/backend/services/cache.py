"""Bounded in-process TTL cache for search discovery results.

Scope is deliberately narrow: this caches the single most expensive external
operation in the request path (the Serper call, measured at ~2.02 s mean in the
Phase 1 baseline). It does not cache generated answers - see docs/CACHING.md.

Concurrency: entries live in a plain dict guarded by nothing. That is safe here
because every access happens inside the asyncio event loop and neither ``get``
nor ``set`` awaits, so no other coroutine can interleave mid-operation. This
avoids lock complexity that would buy nothing under a single-threaded loop.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from backend.services import config


def make_search_key(query: str, *, k: int, country: str = "us", language: str = "en") -> str:
    """Deterministic cache key for a search request.

    Normalises whitespace and case so trivially different spellings of the same
    query share an entry. The API key is deliberately NOT part of the key:
    search results are not user-specific, and keys must never reach a cache.
    """
    normalized = " ".join(query.split()).casefold()
    raw = f"{normalized}|k={k}|gl={country}|hl={language}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TTLCache:
    """Bounded LRU + TTL cache.

    Eviction order: expired entries first, then least-recently-used.
    """

    def __init__(self, *, max_entries: int, ttl_s: float) -> None:
        self.max_entries = max(1, int(max_entries))
        self.ttl_s = float(ttl_s)
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    # -- reads ----------------------------------------------------------
    def get(self, key: str) -> tuple[bool, Any]:
        """Return ``(hit, value)``. A miss never raises."""
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return False, None

        expires_at, value = entry
        if expires_at <= time.monotonic():
            # Expired: drop it so it cannot be served or counted as present.
            del self._entries[key]
            self.expirations += 1
            self.misses += 1
            return False, None

        self._entries.move_to_end(key)
        self.hits += 1
        return True, value

    # -- writes ---------------------------------------------------------
    def set(self, key: str, value: Any) -> None:
        if key in self._entries:
            del self._entries[key]
        self._entries[key] = (time.monotonic() + self.ttl_s, value)

        if len(self._entries) > self.max_entries:
            self._purge_expired()
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)  # evict least-recently-used
            self.evictions += 1

    def _purge_expired(self) -> None:
        now = time.monotonic()
        stale = [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in stale:
            del self._entries[key]
            self.expirations += 1

    # -- introspection --------------------------------------------------
    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "max_entries": self.max_entries,
            "ttl_s": self.ttl_s,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else None,
            "evictions": self.evictions,
            "expirations": self.expirations,
        }


_search_cache: TTLCache | None = None


def get_search_cache() -> TTLCache:
    """Process-wide search cache, built from configuration on first use."""
    global _search_cache
    if _search_cache is None:
        _search_cache = TTLCache(
            max_entries=config.search_cache_max_entries(),
            ttl_s=config.search_cache_ttl_s(),
        )
    return _search_cache


def reset_search_cache() -> None:
    """Drop the cache so the next use rebuilds it from current configuration.

    Used by tests; also a safe way to flush the cache at runtime.
    """
    global _search_cache
    _search_cache = None
