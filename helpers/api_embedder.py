"""OpenAI-compatible embeddings API client for live smoke / integration tests.

This client speaks the OpenAI ``/v1/embeddings`` wire format, which is also
implemented by many self-hosted gateways (Ollama, vLLM, LiteLLM, OpenRouter,
LM Studio, llama.cpp's OpenAI server, Azure OpenAI, Together, Groq, etc.). It is
deliberately small: it exposes the two shapes the reranker accepts
(``aembed_query`` for a single text, and a callable plain ``__call__`` that
delegates to ``aembed_query``) so it can be passed directly as ``embedder``.

Environment variables consumed by callers (the client itself never reads env):

- ``EMBEDDING_BASE_URL``: e.g. ``https://api.openai.com/v1`` or
  ``http://localhost:11434/v1``. Trailing ``/embeddings`` is optional.
- ``EMBEDDING_API_KEY``: bearer token. May be empty/missing for local gateways.
- ``EMBEDDING_MODEL``: e.g. ``text-embedding-3-small`` or ``nomic-embed-text``.

Failure behavior:
- Network/HTTP/JSON errors raise; the reranker's documented fallback contract
  catches the exception and keeps all results with ``similarity=1.0`` and a
  logged warning. Integration tests rely on this and assert it explicitly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Sequence

import httpx

__all__ = ["APIEmbedder", "build_embedder_from_env"]

log = logging.getLogger(__name__)


class APIEmbedder:
    """Minimal async OpenAI-compatible embeddings client.

    Accepts the same interfaces the reranker probes for:

    - ``await client.aembed_query(text)`` returning ``list[float]``
    - ``await client(text)`` as a callable (delegates to ``aembed_query``)

    Args:
        base_url: Base URL up to and including ``/v1`` (e.g.
            ``http://localhost:11434/v1``). A trailing ``/embeddings`` segment
            is tolerated. The path ``/embeddings`` is appended automatically
            if missing.
        api_key: Bearer token; may be empty for local gateways that do not
            require authentication.
        model: Model identifier to send in the request body.
        timeout: Per-request HTTP timeout in seconds.
        max_retries: Number of retries for transient errors (5xx / network).
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        url = (base_url or "").rstrip("/")
        if not url:
            raise ValueError("APIEmbedder requires a non-empty base_url")
        if not url.endswith("/embeddings"):
            url = f"{url}/embeddings"
        self.endpoint = url
        self.api_key = api_key or ""
        self.model = model
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))

    async def aembed_query(self, text: str) -> list[float]:
        """Embed a single string and return its vector."""
        return await self._embed_one(text)

    async def __call__(self, text: str) -> list[float]:
        """Callable alias for ``aembed_query``."""
        return await self._embed_one(text)

    async def _embed_one(self, text: str) -> list[float]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict[str, Any] = {"model": self.model, "input": text}

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self.endpoint, headers=headers, json=body)
                if response.status_code >= 500 and attempt < self.max_retries:
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                vector = _extract_first_vector(payload)
                if not vector:
                    raise ValueError("Embeddings response did not contain a vector")
                return vector
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(0.3 * (2 ** attempt))

        assert last_exc is not None  # for type checkers
        raise last_exc


def _extract_first_vector(payload: Any) -> list[float]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return []
    first = data[0]
    if not isinstance(first, dict):
        return []
    vector = first.get("embedding")
    if isinstance(vector, list) and all(isinstance(v, (int, float)) for v in vector):
        return [float(v) for v in vector]
    return []


def build_embedder_from_env() -> APIEmbedder | None:
    """Build an :class:`APIEmbedder` from environment variables, if available.

    Returns:
        Configured :class:`APIEmbedder` when ``EMBEDDING_BASE_URL`` and
        ``EMBEDDING_MODEL`` are both set in the environment.
        ``EMBEDDING_API_KEY`` is optional. Returns ``None`` otherwise.
    """
    base_url = os.environ.get("EMBEDDING_BASE_URL")
    model = os.environ.get("EMBEDDING_MODEL")
    if not base_url or not model:
        return None
    api_key = os.environ.get("EMBEDDING_API_KEY")
    timeout = float(os.environ.get("EMBEDDING_TIMEOUT", "30") or 30)
    return APIEmbedder(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
