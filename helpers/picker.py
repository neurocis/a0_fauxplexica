"""Quality-mode LLM picker for selecting search results to scrape.

The picker makes a single structured-output LLM call and returns indices into
the *input* results list. The caller is responsible for filtering/scraping.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Dict, List

__all__ = ["pick_results"]


async def pick_results(
    query: str,
    results: list[dict],
    llm,
    *,
    max_picks: int = 3,
) -> list[int]:
    """Pick the best result indices for quality-mode scraping.

    Args:
        query: User/search query.
        results: Candidate result dicts. Returned indices refer to this input
            list, not to any sliced/reordered copy.
        llm: LLM object/callable. Supported interfaces are:
            ``await llm.structured(prompt, schema=...)``,
            ``await llm.apredict(prompt)``, ``llm.predict(prompt)``,
            ``await llm(prompt)``, or ``llm(prompt)``.
        max_picks: Maximum number of input indices to return.

    Returns:
        Up to ``max_picks`` integer indices into ``results``. Invalid,
        duplicate, or out-of-range indices are discarded while preserving LLM
        order.
    """
    if max_picks <= 0 or not results:
        return []

    prompt = _build_prompt(query, results, max_picks=max_picks)
    raw = await _call_llm(llm, prompt)
    picked = _parse_picked_indices(raw)

    out: list[int] = []
    seen: set[int] = set()
    for idx in picked:
        if idx in seen:
            continue
        if 0 <= idx < len(results):
            out.append(idx)
            seen.add(idx)
        if len(out) >= max_picks:
            break
    return out


def _build_prompt(query: str, results: list[dict], *, max_picks: int) -> str:
    """Build the single structured-output picker prompt."""
    compact = []
    for i, r in enumerate(results):
        content = str(r.get("content") or "")[:900]
        compact.append(
            {
                "index": i,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "engine": r.get("engine", ""),
                "content": content,
            }
        )
    return (
        "You are selecting search results to scrape for a high-quality answer.\n"
        "Favor: (1) relevance to the query, (2) content quality/depth, "
        "(3) reputable/original sources, and (4) diversity of perspectives and domains.\n"
        f"Return STRICT JSON only with shape {{\"picked_indices\": [int, ...]}}. "
        f"Pick at most {max_picks} indices from the input list.\n\n"
        f"Query: {query}\n\n"
        f"Results JSON:\n{json.dumps(compact, ensure_ascii=False)}"
    )


async def _call_llm(llm, prompt: str) -> Any:
    """Call common sync/async structured or text LLM interfaces."""
    schema = {"type": "object", "properties": {"picked_indices": {"type": "array", "items": {"type": "integer"}}}}
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


def _parse_picked_indices(raw: Any) -> list[int]:
    """Parse ``{picked_indices:[...]}`` from dict/object/JSON/text."""
    if isinstance(raw, dict):
        data = raw
    elif hasattr(raw, "picked_indices"):
        data = {"picked_indices": getattr(raw, "picked_indices")}
    else:
        text = str(raw)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Last-resort tolerant extraction for models that wrap JSON in text.
            match = re.search(r"\{.*\}", text, flags=re.S)
            data = json.loads(match.group(0)) if match else {}
    vals = data.get("picked_indices", []) if isinstance(data, dict) else []
    out: list[int] = []
    for v in vals:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out
