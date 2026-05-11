"""Quality-mode chunked fact extractor.

Splits scraped page content into Vane-compatible 4000-char / 500-overlap chunks,
runs one structured LLM call per chunk, and gates provider pressure through a
caller-provided asyncio.Semaphore.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any

from helpers.utils import split_text

__all__ = ["extract_facts"]


async def extract_facts(
    url: str,
    content: str,
    query: str,
    llm,
    *,
    semaphore,
) -> str:
    """Extract telegram-style factual bullets from scraped page content.

    Args:
        url: Source URL being extracted; included in the prompt for context.
        content: Scraped text content to split into chunks.
        query: User/search query so the extractor can keep facts relevant.
        llm: Structured/text LLM interface. Supported shapes are
            ``structured(prompt, schema=...)``, ``apredict(prompt)``,
            ``predict(prompt)``, or callable ``llm(prompt)``; sync and async
            return values are both supported.
        semaphore: ``asyncio.Semaphore`` (or compatible async context manager)
            enforcing the configured ``scrape_extractor_concurrency`` cap.

    Returns:
        Extracted fact bundles concatenated with blank lines. Empty input
        returns ``""``.
    """
    chunks = split_text(content or "", chunk=4000, overlap=500)
    if not chunks:
        return ""

    async def run_chunk(index: int, chunk: str) -> str:
        async with semaphore:
            prompt = _build_prompt(url=url, query=query, chunk=chunk, index=index, total=len(chunks))
            raw = await _call_llm(llm, prompt)
            return _parse_extracted_facts(raw).strip()

    # Create all tasks eagerly; semaphore controls provider concurrency.
    import asyncio

    extracted = await asyncio.gather(*(run_chunk(i + 1, c) for i, c in enumerate(chunks)))
    return "\n\n".join(part for part in extracted if part)


def _build_prompt(*, url: str, query: str, chunk: str, index: int, total: int) -> str:
    """Build the per-chunk extractor prompt."""
    return (
        "Extract facts from this scraped source chunk for a Perplexity-style answer.\n"
        "Return STRICT JSON only with shape {\"extracted_facts\": \"...\"}.\n"
        "Use concise telegram-style bullets. Preserve numbers, dates, units, code, and tables verbatim.\n"
        "Do not invent facts. Keep facts relevant to the query.\n\n"
        f"Query: {query}\n"
        f"URL: {url}\n"
        f"Chunk: {index}/{total}\n\n"
        f"Content:\n{chunk}"
    )


async def _call_llm(llm, prompt: str) -> Any:
    """Call a common sync/async LLM interface."""
    schema = {"type": "object", "properties": {"extracted_facts": {"type": "string"}}}
    if hasattr(llm, "structured"):
        value = llm.structured(prompt, schema=schema)
    elif hasattr(llm, "apredict"):
        value = llm.apredict(prompt)
    elif hasattr(llm, "predict"):
        value = llm.predict(prompt)
    elif callable(llm):
        value = llm(prompt)
    else:
        raise TypeError("llm must be callable or provide structured/apredict/predict")
    if inspect.isawaitable(value):
        value = await value
    return value


def _parse_extracted_facts(raw: Any) -> str:
    """Parse ``{extracted_facts: str}`` from dict/object/JSON/text."""
    if isinstance(raw, dict):
        val = raw.get("extracted_facts", "")
        return str(val or "")
    if hasattr(raw, "extracted_facts"):
        return str(getattr(raw, "extracted_facts") or "")
    text = str(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return text
        data = json.loads(match.group(0))
    if isinstance(data, dict):
        return str(data.get("extracted_facts") or "")
    return text
