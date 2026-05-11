"""Tests for helpers.scraper."""

from __future__ import annotations

import pytest

from helpers import scraper
from helpers.scraper import scrape_url


@pytest.mark.asyncio
async def test_scrape_url_returns_extracted_content(monkeypatch):
    monkeypatch.setattr(scraper.trafilatura, "fetch_url", lambda url: "<html><body>hi</body></html>")
    monkeypatch.setattr(
        scraper.trafilatura,
        "extract",
        lambda html, include_comments, include_tables, deduplicate: "  extracted text  ",
    )

    out = await scrape_url("https://example.test")

    assert out == "extracted text"


@pytest.mark.asyncio
async def test_scrape_url_empty_extraction_returns_vane_fallback(monkeypatch):
    monkeypatch.setattr(scraper.trafilatura, "fetch_url", lambda url: "<html></html>")
    monkeypatch.setattr(scraper.trafilatura, "extract", lambda *args, **kwargs: "")

    out = await scrape_url("https://empty.test")

    assert out == "# https://empty.test\n\nError scraping content."


@pytest.mark.asyncio
async def test_scrape_url_fetch_exception_returns_fallback(monkeypatch):
    def boom(_url):
        raise RuntimeError("network")

    monkeypatch.setattr(scraper.trafilatura, "fetch_url", boom)

    out = await scrape_url("https://boom.test")

    assert out == "# https://boom.test\n\nError scraping content."


@pytest.mark.asyncio
async def test_scrape_url_playwright_hook_raises_phase2(monkeypatch):
    monkeypatch.setattr(scraper.trafilatura, "fetch_url", lambda url: "<html></html>")
    monkeypatch.setattr(scraper.trafilatura, "extract", lambda *args, **kwargs: None)

    with pytest.raises(NotImplementedError, match="Phase 2"):
        await scrape_url("https://js-heavy.test", fallback_playwright=True)
