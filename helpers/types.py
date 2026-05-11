"""Shared dataclasses + type aliases for A0_Fauxplexica helpers.

Keep this module dependency-light — no LLM, no network, no I/O. Cross-module
contracts live here so Orchy/Reggie/Compo can import without pulling in heavier
deps.

Part of the A0_Fauxplexica plugin. See PLAN_PHASE1.md §3 / PLAN_AMENDMENTS_R1.md §A2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "SearchResult",
    "PickerOutput",
    "ExtractorChunkOutput",
    "RoutingWidgets",
    "RoutingFlags",
    "StyleHints",
    "ClassifierOutput",
    "PrimaryType",
    "Freshness",
    "DepthHint",
    "to_dict",
    "from_dict",
]


@dataclass
class SearchResult:
    """Canonical search result shape used across the plugin.

    Mirrors Vane's per-result dict but strongly typed. Downstream consumers
    (Reggie's researcher loop, Citer's source registry, Compo's context
    builder) all key off this shape.

    Attributes:
        title: Human-readable result title.
        url: Canonical URL of the result. Used as the dedup key.
        content: Snippet or extracted body. May be concatenated across
            multiple SearxNG hits with the same ``url`` (URL-level dedup with
            content-concat — see PLAN_AMENDMENTS_R1 §A12 / RECON §2.2 stage D).
        engine: Source engine name (e.g. ``google``, ``brave``, ``arxiv``).
        score: Optional engine-provided relevance score (passthrough).
        published_date: Optional ISO-ish publish date from the engine.
        category: SearxNG category bucket (``general``, ``images``,
            ``videos``, ``science``, ``social media``). Set by the client to
            help downstream consumers route results.
        similarity: Optional rerank cosine similarity vs query. Populated by
            the reranker; ``1.0`` when the embedder failed and we kept all
            results as a fallback.
        extra: Open dict for engine-specific passthrough fields (publishedDate
            casing, image thumbnails, video duration, etc).
    """

    title: str
    url: str
    content: str
    engine: str = ""
    score: Optional[float] = None
    published_date: Optional[str] = None
    category: Optional[str] = None
    similarity: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict (for JSON serialization / LLM context)."""
        d = asdict(self)
        # Drop empties to keep the wire format tight; consumers can treat
        # missing keys as None.
        if not d["extra"]:
            d.pop("extra")
        for k in ("score", "published_date", "category", "similarity"):
            if d.get(k) is None:
                d.pop(k, None)
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SearchResult":
        """Build a SearchResult from a loose dict (e.g. SearxNG JSON row).

        Unknown keys are stashed under ``extra`` rather than dropped.
        """
        known = {
            "title",
            "url",
            "content",
            "engine",
            "score",
            "published_date",
            "category",
            "similarity",
        }
        # SearxNG uses camelCase for publishedDate; normalise.
        published = raw.get("published_date") or raw.get("publishedDate")
        extra = {k: v for k, v in raw.items() if k not in known and k != "publishedDate"}
        return cls(
            title=str(raw.get("title") or ""),
            url=str(raw.get("url") or ""),
            content=str(raw.get("content") or ""),
            engine=str(raw.get("engine") or ""),
            score=_safe_float(raw.get("score")),
            published_date=str(published) if published is not None else None,
            category=raw.get("category"),
            similarity=_safe_float(raw.get("similarity")),
            extra=extra,
        )


@dataclass
class PickerOutput:
    """Structured-output shape returned by the quality-mode picker LLM."""

    picked_indices: List[int] = field(default_factory=list)


@dataclass
class ExtractorChunkOutput:
    """Structured-output shape returned by the extractor LLM per chunk."""

    extracted_facts: str = ""


def to_dict(result: SearchResult) -> Dict[str, Any]:
    """Module-level convenience wrapper around ``SearchResult.to_dict``."""
    return result.to_dict()


def from_dict(raw: Dict[str, Any]) -> SearchResult:
    """Module-level convenience wrapper around ``SearchResult.from_dict``."""
    return SearchResult.from_dict(raw)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Classy — classifier output schema (PLAN_AMENDMENTS_R1.md §A5)
# ---------------------------------------------------------------------------

PrimaryType = Literal[
    "general",
    "academic_research",
    "recent_news",
    "weather",
    "people",
    "coding",
    "recipe",
    "translation",
    "creative_writing",
    "science_math",
    "url_lookup",
]

Freshness = Literal["any", "week", "day"]
DepthHint = Literal["short", "medium", "deep"]


@dataclass
class RoutingWidgets:
    """Per-widget enable flags emitted by the classifier.

    These are advisory; :func:`helpers.classifier.classify` AND-gates them
    against caller-provided settings before returning.
    """

    weather: bool = False
    stock: bool = False
    calculation: bool = False

    def to_dict(self) -> Dict[str, bool]:
        """Return a plain dict matching the §A5 nested widget schema."""
        return {
            "weather": self.weather,
            "stock": self.stock,
            "calculation": self.calculation,
        }


@dataclass
class RoutingFlags:
    """Tool-routing flags — the *which-tools-fire* axis.

    Ports Vane's classifier booleans 1:1, plus a nested widget block.
    Orthogonal to :class:`StyleHints` (the *how-to-answer* axis).
    """

    skip_search: bool = False
    personal_search: bool = False
    academic_search: bool = False
    discussion_search: bool = False
    widgets: RoutingWidgets = field(default_factory=RoutingWidgets)

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict matching the §A5 routing schema."""
        return {
            "skip_search": self.skip_search,
            "personal_search": self.personal_search,
            "academic_search": self.academic_search,
            "discussion_search": self.discussion_search,
            "widgets": self.widgets.to_dict(),
        }


@dataclass
class StyleHints:
    """Answer-style hints — the *how-to-answer* axis.

    Drives composer template selection (``primary_type``), SearxNG
    ``time_range`` (``freshness``), and composer verbosity (``depth_hint``).
    """

    primary_type: PrimaryType = "general"
    freshness: Freshness = "any"
    depth_hint: DepthHint = "medium"

    def to_dict(self) -> Dict[str, str]:
        """Return a plain dict matching the §A5 style schema."""
        return {
            "primary_type": self.primary_type,
            "freshness": self.freshness,
            "depth_hint": self.depth_hint,
        }


@dataclass
class ClassifierOutput:
    """Top-level classifier result.

    Schema mirrors PLAN_AMENDMENTS_R1.md §A5. ``_fastpath_reason`` is a
    debug-only field set when deterministic heuristics bypass the LLM.
    """

    routing: RoutingFlags = field(default_factory=RoutingFlags)
    style: StyleHints = field(default_factory=StyleHints)
    standalone_followup: str = ""
    detected_urls: List[str] = field(default_factory=list)
    _fastpath_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to the wire schema, omitting debug-only fields."""
        return {
            "routing": self.routing.to_dict(),
            "style": self.style.to_dict(),
            "standalone_followup": self.standalone_followup,
            "detected_urls": list(self.detected_urls),
        }
