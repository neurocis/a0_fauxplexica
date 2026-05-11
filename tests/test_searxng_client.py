"""Tests for helpers.searxng_client."""

from __future__ import annotations

import httpx
import pytest

from helpers.searxng_client import SearxClient, SearxError


@pytest.mark.asyncio
async def test_search_uses_repeated_engines_and_categories_and_plumbs_options():
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        qp = request.url.params
        assert qp.get("q") == "agentic search"
        assert qp.get("format") == "json"
        assert qp.get("time_range") == "week"
        assert qp.get("safesearch") == "2"
        assert qp.get("pageno") == "1"
        assert qp.get_list("engines") == ["brave", "google scholar"]
        assert qp.get_list("categories") == ["science", "general"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Paper",
                        "url": "https://example.test/paper",
                        "content": "snippet",
                        "engine": "arxiv",
                        "score": 0.9,
                        "publishedDate": "2026-01-01",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sx = SearxClient("https://searx.test", client=client)
        rows = await sx.search(
            "agentic search",
            engines=["brave", "google scholar"],
            categories=["science", "general"],
            time_range="week",
            safesearch=2,
        )

    assert len(seen_urls) == 1
    assert rows == [
        {
            "title": "Paper",
            "url": "https://example.test/paper",
            "content": "snippet",
            "engine": "arxiv",
            "score": 0.9,
            "publishedDate": "2026-01-01",
            "category": "science",
        }
    ]


@pytest.mark.asyncio
async def test_search_pagination_flattens_pages_in_order():
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("pageno")
        pages.append(page)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": f"Title {page}",
                        "url": f"https://example.test/{page}",
                        "content": f"content {page}",
                        "engine": "brave",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await SearxClient("https://searx.test", client=client).search("q", pages=3)

    assert pages == ["1", "2", "3"]
    assert [r["title"] for r in rows] == ["Title 1", "Title 2", "Title 3"]


@pytest.mark.asyncio
async def test_search_retries_transient_5xx_then_succeeds(monkeypatch):
    calls = 0

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("helpers.searxng_client.asyncio.sleep", no_sleep)
    monkeypatch.setattr("helpers.searxng_client.random.uniform", lambda _a, _b: 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "ok", "url": "https://ok", "content": "ok", "engine": "brave"}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await SearxClient(
            "https://searx.test", client=client, max_retries=2, backoff_base=0
        ).search("q")

    assert calls == 2
    assert rows[0]["title"] == "ok"


@pytest.mark.asyncio
async def test_search_4xx_does_not_retry():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad query")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SearxError):
            await SearxClient("https://searx.test", client=client, max_retries=3).search("q")

    assert calls == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"query": "q", "time_range": "hour"},
        {"query": "q", "safesearch": 9},
        {"query": "q", "pages": 0},
    ],
)
def test_search_validation(kwargs):
    sx = SearxClient("https://searx.test", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))

    async def run():
        await sx.search(**kwargs)

    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(run())
