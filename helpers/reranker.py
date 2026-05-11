"""Embedding-based reranker for speed/balanced Fauxplexica searches.

Ports Vane's hot-path result filtering with one deliberate hardening: embedder
failures keep all results but log a warning instead of failing silently.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Sequence

from helpers.utils import cosine_similarity

__all__ = ["rerank_results"]

log = logging.getLogger(__name__)


async def rerank_results(
    query: str,
    results: list[dict],
    embedder,
    *,
    keep_threshold: float = 0.5,
    dedup_threshold: float = 0.75,
    top_k: int = 20,
) -> list[dict]:
    """Filter, deduplicate, sort, and truncate search results by embeddings.

    Args:
        query: User/search query to embed once.
        results: Search result dictionaries. Each result's ``content`` field is
            embedded; empty content falls back to title/url text.
        embedder: Object/function capable of embedding text. Supported shapes:
            ``await embedder.aembed_query(text)``, ``embedder.embed_query(text)``,
            ``await embedder(text)``, or ``embedder(text)``.
        keep_threshold: Drop results with query cosine similarity below this.
        dedup_threshold: Drop any candidate whose max cosine similarity to a
            prior kept result is greater than this threshold.
        top_k: Return at most this many results.

    Returns:
        New list of result dicts, each with ``similarity`` populated.

    Failure policy:
        If any embedder call fails, all input results are returned (copied) with
        ``similarity=1.0`` and a warning is logged.
    """
    if top_k <= 0:
        return []
    if not results:
        return []

    try:
        query_vec = await _embed(embedder, query)
        rows: list[tuple[dict, Sequence[float], float]] = []
        for result in results:
            text = _result_text(result)
            vec = await _embed(embedder, text)
            sim = cosine_similarity(query_vec, vec)
            if sim >= keep_threshold:
                r = dict(result)
                r["similarity"] = sim
                rows.append((r, vec, sim))
    except Exception as exc:  # noqa: BLE001 - deliberate broad fallback contract
        log.warning("Embedding rerank failed; keeping all results with similarity=1.0: %s", exc)
        kept = []
        for result in results:
            r = dict(result)
            r["similarity"] = 1.0
            kept.append(r)
        return kept[:top_k]

    rows.sort(key=lambda item: item[2], reverse=True)

    kept: list[dict] = []
    kept_vecs: list[Sequence[float]] = []
    for result, vec, _sim in rows:
        if kept_vecs:
            max_prior = max(cosine_similarity(vec, prior) for prior in kept_vecs)
            if max_prior > dedup_threshold:
                continue
        kept.append(result)
        kept_vecs.append(vec)
        if len(kept) >= top_k:
            break
    return kept


async def _embed(embedder, text: str) -> Sequence[float]:
    """Call a common sync/async embedder interface and return one vector."""
    if hasattr(embedder, "aembed_query"):
        value = embedder.aembed_query(text)
    elif hasattr(embedder, "embed_query"):
        value = embedder.embed_query(text)
    elif callable(embedder):
        value = embedder(text)
    else:
        raise TypeError("embedder must be callable or provide embed_query/aembed_query")
    if inspect.isawaitable(value):
        value = await value
    if not isinstance(value, Sequence):
        raise TypeError("embedder returned a non-sequence vector")
    return value


def _result_text(result: Dict[str, Any]) -> str:
    """Return text used for embedding a result."""
    return str(result.get("content") or result.get("title") or result.get("url") or "")
