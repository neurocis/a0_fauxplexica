"""Async SearxNG meta-search client used by the A0_Fauxplexica researcher.

Improvements over Vane:
- repeated ``engines=`` and ``categories=`` params, not comma-joined values
- ``time_range`` and ``safesearch`` plumbing
- pagination via ``pages``
- bounded exponential backoff for transient failures
- public result shape: ``{title, url, content, engine, score?, publishedDate?}``

Google Scholar note: SearxNG frequently ships the ``google scholar`` engine
as disabled by default in ``engines.yml``. Users must enable it explicitly for
academic search to work well.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin

import httpx

from helpers.types import SearchResult

__all__ = ["SearxClient", "SearxError"]

log = logging.getLogger(__name__)

_TIME_RANGES = {"any", "day", "week", "month", "year"}
_SAFESEARCH_VALUES = {0, 1, 2}
_KNOWN_CATEGORIES = {"general", "images", "videos", "science", "social media"}


class SearxError(RuntimeError):
    """Raised when SearxNG returns an unrecoverable error after retries."""


class SearxClient:
    """Thin async client for a self-hosted SearxNG instance.

    Args:
        base_url: SearxNG instance URL, typically read from plugin setting
            ``searxng_url`` by the caller.
        timeout: Per-request timeout in seconds.
        max_retries: Retry count for transient network/5xx/JSON errors.
        backoff_base: Initial exponential backoff delay in seconds.
        client: Optional ``httpx.AsyncClient`` for tests / dependency injection.
        user_agent: User-Agent sent on requests.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        client: Optional[httpx.AsyncClient] = None,
        user_agent: str = "a0-fauxplexica/0.1",
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError("base_url must be a non-empty SearxNG URL")
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._backoff_base = max(0.0, float(backoff_base))
        self._user_agent = user_agent
        self._client = client
        self._external_client = client is not None

    async def __aenter__(self) -> "SearxClient":
        """Return this client as an async context manager."""
        self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Close owned HTTP resources on context-manager exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._client is not None and not self._external_client:
            await self._client.aclose()
            self._client = None

    async def search(
        self,
        query: str,
        *,
        engines: Optional[Sequence[str]] = None,
        categories: Optional[Sequence[str]] = None,
        time_range: str = "any",
        safesearch: int = 0,
        pages: int = 1,
        language: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search SearxNG and return canonical public result dictionaries.

        Args:
            query: Non-empty query string.
            engines: Optional engine names, serialized as repeated params.
            categories: Optional SearxNG categories. Phase 1 uses ``general``,
                ``images``, ``videos``, ``science`` and ``social media``.
            time_range: One of ``any|day|week|month|year``. ``any`` omits the
                param because SearxNG treats absence as all-time.
            safesearch: SearxNG safesearch value ``0|1|2``.
            pages: Number of SearxNG pages to fetch and flatten.
            language: Optional SearxNG language code.
            extra_params: Optional raw extra query params.

        Returns:
            List of ``{title, url, content, engine, score?, publishedDate?}``
            dicts. ``category`` is included when known for downstream routing.

        Raises:
            ValueError: Invalid caller input.
            SearxError: SearxNG failure after retries, or unretryable 4xx.
        """
        self._validate(query, time_range, safesearch, pages, categories)
        out: List[Dict[str, Any]] = []
        for page in range(1, pages + 1):
            params = self._build_params(
                query=query,
                engines=engines,
                categories=categories,
                time_range=time_range,
                safesearch=safesearch,
                page=page,
                language=language,
                extra_params=extra_params,
            )
            payload = await self._fetch_with_retry(params)
            out.extend(self._parse_payload(payload, categories=categories))
        return out

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            )
        return self._client

    def _validate(
        self,
        query: str,
        time_range: str,
        safesearch: int,
        pages: int,
        categories: Optional[Sequence[str]],
    ) -> None:
        if not query or not query.strip():
            raise ValueError("query must be non-empty")
        if time_range not in _TIME_RANGES:
            raise ValueError(f"time_range must be one of {sorted(_TIME_RANGES)}")
        if safesearch not in _SAFESEARCH_VALUES:
            raise ValueError(f"safesearch must be one of {sorted(_SAFESEARCH_VALUES)}")
        if pages < 1:
            raise ValueError("pages must be >= 1")
        if categories:
            unknown = [c for c in categories if c not in _KNOWN_CATEGORIES]
            if unknown:
                log.warning("SearxClient: unknown categories passed through: %s", unknown)

    def _build_params(
        self,
        *,
        query: str,
        engines: Optional[Sequence[str]],
        categories: Optional[Sequence[str]],
        time_range: str,
        safesearch: int,
        page: int,
        language: Optional[str],
        extra_params: Optional[Dict[str, Any]],
    ) -> List[tuple[str, str]]:
        """Build params as a list so repeated keys are preserved by httpx."""
        params: List[tuple[str, str]] = [
            ("q", query),
            ("format", "json"),
            ("safesearch", str(safesearch)),
            ("pageno", str(page)),
        ]
        if time_range != "any":
            params.append(("time_range", time_range))
        if language:
            params.append(("language", language))
        for engine in engines or ():
            params.append(("engines", str(engine)))
        for category in categories or ():
            params.append(("categories", str(category)))
        if extra_params:
            for key, value in extra_params.items():
                if isinstance(value, (list, tuple)):
                    params.extend((str(key), str(item)) for item in value)
                else:
                    params.append((str(key), str(value)))
        return params

    async def _fetch_with_retry(self, params: Sequence[tuple[str, str]]) -> Dict[str, Any]:
        """Fetch one result page with exponential backoff."""
        client = self._ensure_client()
        url = urljoin(self._base_url, "search")
        last_err: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.get(url, params=list(params))
                if 400 <= response.status_code < 500:
                    raise SearxError(f"SearxNG {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("SearxNG JSON payload must be an object")
                return payload
            except SearxError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_err = exc
                if attempt >= self._max_retries:
                    break
                delay = self._backoff_base * (2**attempt) + random.uniform(0, self._backoff_base)
                log.warning(
                    "SearxNG fetch failed (attempt %d/%d): %s; retrying in %.2fs",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        raise SearxError(f"SearxNG fetch failed after retries: {last_err!r}")

    def _parse_payload(
        self,
        payload: Dict[str, Any],
        *,
        categories: Optional[Sequence[str]],
    ) -> List[Dict[str, Any]]:
        """Normalize raw SearxNG ``results`` to the public dict contract."""
        rows = payload.get("results") or []
        if not isinstance(rows, list):
            log.warning("SearxNG payload['results'] was %r, expected list", type(rows))
            return []
        primary_category = categories[0] if categories else None
        out: List[Dict[str, Any]] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            sr = SearchResult.from_dict(raw)
            if primary_category and not sr.category:
                sr.category = primary_category
            out.append(self._to_public_dict(sr))
        return out

    def _to_public_dict(self, sr: SearchResult) -> Dict[str, Any]:
        """Return required downstream dict shape from a ``SearchResult``."""
        d: Dict[str, Any] = {
            "title": sr.title,
            "url": sr.url,
            "content": sr.content,
            "engine": sr.engine,
        }
        if sr.score is not None:
            d["score"] = sr.score
        if sr.published_date is not None:
            d["publishedDate"] = sr.published_date
        if sr.category is not None:
            d["category"] = sr.category
        if sr.similarity is not None:
            d["similarity"] = sr.similarity
        if sr.extra:
            d.update(sr.extra)
        return d
