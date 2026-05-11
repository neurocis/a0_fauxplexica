"""Misc helpers used across A0_Fauxplexica.

Ported at scaffold time per PLAN_AMENDMENTS_R1.md §A13 (utils owned by Scaff).
Keep this module dependency-light — no LLM, no network. Heavier helpers belong
in their own modules.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import List

__all__ = ["split_text", "cosine_similarity"]


def split_text(text: str, chunk: int = 4000, overlap: int = 500) -> List[str]:
    """Split ``text`` into roughly ``chunk``-char windows with ``overlap``.

    Port of Vane's ``splitText(content, 4000, 500)`` used by the chunked
    extractor LLM. Pure character-window split — no tokenizer dependency.

    - ``chunk`` must be positive.
    - ``overlap`` must be non-negative and strictly less than ``chunk``.
    - Empty input yields an empty list.
    """
    if chunk <= 0:
        raise ValueError("chunk must be > 0")
    if overlap < 0 or overlap >= chunk:
        raise ValueError("overlap must be in [0, chunk)")
    if not text:
        return []

    step = chunk - overlap
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + chunk])
        i += step
    return out


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return cosine similarity of two equal-length numeric vectors.

    Returns ``0.0`` if either vector has zero magnitude. Inputs must have
    matching length; otherwise ``ValueError`` is raised.
    """
    if len(a) != len(b):
        raise ValueError("vectors must have equal length")
    if not a:
        return 0.0

    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy

    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
