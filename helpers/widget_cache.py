"""In-process TTL cache for widget external-API responses.

Primary consumer is the StockWidget — yfinance is rate-limited and frequently
breaks when Yahoo changes their unofficial endpoints, so aggressive caching is
mandatory (see PLAN_AMENDMENTS_R1.md §A8).

Not thread-safe in a meaningful way; we rely on the GIL and the fact that
cache writes are O(1) dict operations. Async-safe because we never await
while holding state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Generic, Hashable, Optional, TypeVar

__all__ = ["TTLCache"]

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Tiny in-process TTL cache keyed by any hashable.

    Usage:
        cache: TTLCache[dict] = TTLCache(ttl_seconds=300)
        cached = cache.get(("AAPL", "1D"))
        if cached is None:
            cached = expensive_fetch()
            cache.set(("AAPL", "1D"), cached)
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = ttl_seconds
        self._store: dict[Hashable, _Entry[T]] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def get(self, key: Hashable) -> Optional[T]:
        """Return cached value or ``None`` if missing or expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            # Lazy eviction
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: Hashable, value: T, ttl_seconds: Optional[int] = None) -> None:
        """Store ``value`` under ``key`` with optional per-entry TTL override."""
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        self._store[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, Hashable):  # type: ignore[arg-type]
            return False
        return self.get(key) is not None  # type: ignore[arg-type]


# Module-level cache instance for the stock widget. Other modules can construct
# their own ``TTLCache`` if they need separate TTLs / namespaces.
stock_chart_cache: TTLCache[Any] = TTLCache(ttl_seconds=300)
stock_quote_cache: TTLCache[Any] = TTLCache(ttl_seconds=300)
