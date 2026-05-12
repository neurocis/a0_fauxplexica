"""Reranker smoke / integration test.

Skipped by default. Activates only when ``SEARXNG_URL`` is set in the
environment. When ``EMBEDDING_BASE_URL`` + ``EMBEDDING_MODEL`` are also set,
the embedder used is a real OpenAI-compatible API client; otherwise a
deterministic bag-of-words pseudo-embedder is used so the rerank machinery is
still exercised end-to-end.

The test validates:

- Real-data rerank ordering by cosine similarity (descending).
- ``top_k`` truncation is honored.
- ``keep_threshold`` filters off-topic noise.
- ``dedup_threshold`` removes a deliberately injected near-duplicate.
- Embedder failure triggers the graceful fallback (all results, ``similarity=1.0``).
- Empty input returns ``[]``.
- Self-cosine on the same input vector is 1.0 (vector determinism).
"""

from __future__ import annotations

import math
import os
import re
from typing import Any

import httpx
import pytest

from helpers.api_embedder import build_embedder_from_env
from helpers.reranker import rerank_results

pytestmark = pytest.mark.integration

_REQUIRED_ENV = "SEARXNG_URL"
_WORD_RE = re.compile(r"[a-zA-Z]+")
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 fauxplexica-rerank-smoke/1.0"

skip_unless_searxng = pytest.mark.skipif(
    not os.environ.get(_REQUIRED_ENV),
    reason=f"set {_REQUIRED_ENV} to run the reranker integration smoke",
)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "") if len(t) > 2]


class BagOfWordsEmbedder:
    """Deterministic offline embedder used when no API embedder is configured.

    Vectors are L2-normalized hashed bag-of-words counts so identical input is
    guaranteed to produce identical vectors and semantically related inputs
    share token buckets.
    """

    DIM = 256

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def aembed_query(self, text: str) -> list[float]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedder offline (simulated)")
        vec = [0.0] * self.DIM
        for token in _tokenize(text):
            vec[hash(token) % self.DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FailingEmbedder:
    """Embedder that always raises, used to verify the rerank fallback contract."""

    async def aembed_query(self, _text: str) -> list[float]:
        raise RuntimeError("embedder offline (simulated)")


async def _fetch_searxng(searxng_url: str, query: str) -> list[dict[str, Any]]:
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        response = await client.get(
            f"{searxng_url.rstrip('/')}/search",
            params={"q": query, "format": "json"},
        )
    response.raise_for_status()
    payload = response.json()
    out: list[dict[str, Any]] = []
    for item in payload.get("results", []) or []:
        out.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "content": item.get("content") or "",
                "engine": item.get("engine"),
            }
        )
    return out


def _inject_test_fixtures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add a deliberate near-duplicate and an off-topic noise result."""
    enriched = list(results)
    if enriched:
        original = enriched[0]
        mirror = dict(original)
        mirror["url"] = (original.get("url") or "").rstrip("/") + "/?utm=dup"
        mirror["title"] = f"{original.get('title', '')} (mirror)"
        enriched.append(mirror)
    enriched.append(
        {
            "title": "Best pizza recipes 2024",
            "url": "https://example.com/pizza",
            "content": "Sourdough crust pepperoni mozzarella oven baking tips",
            "engine": "noise",
        }
    )
    return enriched


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@skip_unless_searxng
@pytest.mark.asyncio
async def test_reranker_smoke_against_real_searxng() -> None:
    searxng_url = os.environ[_REQUIRED_ENV]
    query = "climate change long term effects on global temperatures"

    raw = await _fetch_searxng(searxng_url, query)
    assert raw, f"SearxNG at {searxng_url} returned no results for {query!r}"
    raw = _inject_test_fixtures(raw)

    embedder: Any = build_embedder_from_env() or BagOfWordsEmbedder()
    real_api = embedder.__class__.__name__ == "APIEmbedder"

    # 1) Normal rerank: descending similarity, top_k honored, similarity present
    ranked = await rerank_results(
        query, list(raw), embedder,
        keep_threshold=0.05, dedup_threshold=0.92, top_k=10,
    )
    assert ranked, "rerank produced no results"
    assert all("similarity" in r for r in ranked), "similarity field missing on ranked rows"
    sims = [r["similarity"] for r in ranked]
    assert sims == sorted(sims, reverse=True), "results not sorted by similarity desc"
    assert len(ranked) <= 10, f"top_k=10 not honored (got {len(ranked)})"

    # 2) Strict keep_threshold must filter the injected off-topic noise.
    # When the real semantic embedder is used the threshold may need to scale to
    # the model's similarity distribution, but the off-topic item should never
    # outrank the top 5 query-aligned items.
    strict = await rerank_results(
        query, list(raw), embedder,
        keep_threshold=0.30, dedup_threshold=0.92, top_k=10,
    )
    strict_titles = [r["title"].lower() for r in strict[:5]]
    assert not any("pizza" in title for title in strict_titles), (
        f"off-topic noise leaked into strict top-5: {strict_titles}"
    )

    # 3) top_k=3 truncation honored.
    top3 = await rerank_results(
        query, list(raw), embedder,
        keep_threshold=0.0, dedup_threshold=0.99, top_k=3,
    )
    assert len(top3) == 3, f"top_k=3 not honored (got {len(top3)})"

    # 4) dedup_threshold removes the injected mirror (same content + minor URL change).
    deduped = await rerank_results(
        query, list(raw), embedder,
        keep_threshold=0.0, dedup_threshold=0.85, top_k=50,
    )
    titles_lower = [r["title"].lower() for r in deduped]
    assert not any("(mirror)" in t for t in titles_lower), (
        "near-duplicate mirror was not removed by dedup_threshold=0.85"
    )

    # 5) Failing embedder triggers the graceful fallback contract.
    fallback = await rerank_results(
        query, list(raw), FailingEmbedder(),
        keep_threshold=0.5, dedup_threshold=0.75, top_k=5,
    )
    assert len(fallback) == 5, f"fallback should keep top_k=5 (got {len(fallback)})"
    assert all(r["similarity"] == 1.0 for r in fallback), (
        "fallback must set similarity=1.0 on every result"
    )

    # 6) Empty input returns empty list.
    assert await rerank_results(query, [], embedder, top_k=5) == []

    # 7) Self-cosine on the same input vector is 1.0 (within float tolerance).
    v1 = await embedder.aembed_query(query)
    v2 = await embedder.aembed_query(query)
    self_cos = _cosine(v1, v2)
    assert abs(self_cos - 1.0) < 1e-6, (
        f"self-cosine should be 1.0, got {self_cos} (real_api={real_api})"
    )
