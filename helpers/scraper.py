"""Trafilatura-based page scraper for A0_Fauxplexica Phase 1.

Phase 1 intentionally avoids Playwright/Chromium. A visible Phase 2 hook is
kept behind ``fallback_playwright`` so config wiring can expose the toggle
without silently doing nothing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import trafilatura

__all__ = ["scrape_url"]

log = logging.getLogger(__name__)


def _error_content(url: str) -> str:
    """Return Vane-compatible scraper fallback content."""
    return f"# {url}\n\nError scraping content."


async def scrape_url(url: str, *, timeout: float = 20, fallback_playwright: bool = False) -> str:
    """Scrape readable page text from ``url`` using Trafilatura.

    Args:
        url: URL to fetch and extract.
        timeout: Overall timeout in seconds for the blocking Trafilatura fetch
            and extraction work.
        fallback_playwright: Phase 2 hook corresponding to
            ``webui.scraper_fallback_playwright``. If true and Trafilatura
            fails/returns empty, a ``NotImplementedError("Phase 2")`` is raised.

    Returns:
        Extracted readable text, or Vane-compatible fallback
        ``# {url}\n\nError scraping content.`` when Trafilatura fails/returns empty.

    Raises:
        NotImplementedError: If ``fallback_playwright=True`` and Trafilatura
        cannot extract content. Playwright fallback is deferred to Phase 2.
    """
    if not url or not url.strip():
        return _error_content(url)

    try:
        text = await asyncio.wait_for(asyncio.to_thread(_scrape_sync, url), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - scrape failures degrade to fallback content
        log.warning("Trafilatura scrape failed for %s: %s", url, exc)
        text = None

    if text and text.strip():
        return text.strip()

    if fallback_playwright:
        raise NotImplementedError("Phase 2")
    return _error_content(url)


def _scrape_sync(url: str) -> Optional[str]:
    """Blocking Trafilatura fetch/extract implementation."""
    html = trafilatura.fetch_url(url)
    if not html:
        return None
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        deduplicate=True,
    )
