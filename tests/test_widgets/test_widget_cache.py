"""Tests for ``helpers/widget_cache.py`` (no network)."""

from __future__ import annotations

import time

import pytest

from a0_fauxplexica.helpers.widget_cache import TTLCache


def test_get_miss_returns_none() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=60)
    assert cache.get("missing") is None


def test_set_then_get_roundtrip() -> None:
    cache: TTLCache[dict] = TTLCache(ttl_seconds=60)
    payload = {"price": 123.45}
    cache.set(("AAPL", "1D"), payload)
    assert cache.get(("AAPL", "1D")) == payload


def test_entry_expires() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=60)
    cache.set("k", 1, ttl_seconds=1)
    assert cache.get("k") == 1
    # Force expiry by sleeping past the TTL.
    time.sleep(1.1)
    assert cache.get("k") is None


def test_clear_drops_everything() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=60)
    cache.set("a", 1)
    cache.set("b", 2)
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0


def test_invalid_ttl_raises() -> None:
    with pytest.raises(ValueError):
        TTLCache(ttl_seconds=0)
    with pytest.raises(ValueError):
        TTLCache(ttl_seconds=-5)


def test_contains_uses_ttl() -> None:
    cache: TTLCache[str] = TTLCache(ttl_seconds=60)
    cache.set("k", "v")
    assert "k" in cache
    cache.clear()
    assert "k" not in cache
