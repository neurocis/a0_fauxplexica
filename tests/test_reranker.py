"""Tests for helpers.reranker."""

from __future__ import annotations

import logging

import pytest

from helpers.reranker import rerank_results


class FakeEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors

    async def aembed_query(self, text):
        if isinstance(self.vectors, Exception):
            raise self.vectors
        return self.vectors[text]


@pytest.mark.asyncio
async def test_rerank_filters_dedups_sorts_and_slices():
    results = [
        {"title": "bad", "url": "u1", "content": "bad"},
        {"title": "good", "url": "u2", "content": "good"},
        {"title": "dupe", "url": "u3", "content": "dupe"},
        {"title": "ok", "url": "u4", "content": "ok"},
    ]
    embedder = FakeEmbedder(
        {
            "query": [1, 0],
            "bad": [0, 1],       # filtered
            "good": [1, 0],      # kept
            "dupe": [0.99, 0.01],# deduped vs good
            "ok": [0.6, 0.8],    # kept: relevant, but not duplicate
        }
    )

    out = await rerank_results(
        "query", results, embedder, keep_threshold=0.5, dedup_threshold=0.75, top_k=10
    )

    assert [r["title"] for r in out] == ["good", "ok"]
    assert out[0]["similarity"] == pytest.approx(1.0)
    assert out[1]["similarity"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_rerank_top_k_applies_after_sort():
    results = [
        {"title": "a", "content": "a"},
        {"title": "b", "content": "b"},
        {"title": "c", "content": "c"},
    ]
    embedder = FakeEmbedder({"q": [1, 0], "a": [0.6, 0.8], "b": [1, 0], "c": [0.8, 0.6]})
    out = await rerank_results("q", results, embedder, keep_threshold=0.0, dedup_threshold=1.0, top_k=2)
    assert [r["title"] for r in out] == ["b", "c"]


@pytest.mark.asyncio
async def test_rerank_embedder_failure_keeps_all_and_logs_warning(caplog):
    results = [{"title": "a", "content": "a"}, {"title": "b", "content": "b"}]
    caplog.set_level(logging.WARNING)
    out = await rerank_results("q", results, FakeEmbedder(RuntimeError("boom")))
    assert [r["similarity"] for r in out] == [1.0, 1.0]
    assert "Embedding rerank failed" in caplog.text
