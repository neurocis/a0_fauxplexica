"""Citation validation and source registry helpers for A0_Fauxplexica.

The composer emits Perplexity/Vane-style inline bracket citations such as
``[1]`` or citation clusters such as ``[1][3]``.  This module normalizes raw
search findings into a stable one-based source registry and performs post-hoc
validation of citations in generated answers.

The functions are deterministic and side-effect free so they can be used from
orchestrator/API/WebUI code without network or model calls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable, Literal
from urllib.parse import urlsplit, urlunsplit

CitationPolicy = Literal["keep", "strip_invalid", "annotate_invalid"]
_CITATION_RE = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class SourceRecord:
    """Normalized citeable source metadata."""

    index: int
    title: str
    url: str
    snippet: str = ""
    source: str = "web"
    score: float | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        data = asdict(self)
        if data["metadata"] is None:
            data["metadata"] = {}
        return data


@dataclass(frozen=True)
class CitationRef:
    """One citation occurrence in an answer."""

    index: int
    start: int
    end: int
    text: str
    valid: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CitationValidationResult:
    """Structured result returned by :func:`validate_citations`."""

    answer: str
    original_answer: str
    registry: list[SourceRecord]
    citations: list[CitationRef]
    valid_indices: list[int]
    invalid_indices: list[int]
    cited_indices: list[int]
    uncited_indices: list[int]
    policy: CitationPolicy

    @property
    def ok(self) -> bool:
        """Whether all citation refs are valid."""
        return not self.invalid_indices

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "ok": self.ok,
            "answer": self.answer,
            "original_answer": self.original_answer,
            "registry": [item.to_dict() for item in self.registry],
            "citations": [item.to_dict() for item in self.citations],
            "valid_indices": self.valid_indices,
            "invalid_indices": self.invalid_indices,
            "cited_indices": self.cited_indices,
            "uncited_indices": self.uncited_indices,
            "policy": self.policy,
        }


def build_source_registry(sources: Iterable[Any], *, dedupe_urls: bool = True) -> list[SourceRecord]:
    """Normalize raw source/search-finding objects into stable 1-based records.

    ``sources`` may contain dictionaries, dataclasses, or arbitrary objects with
    ``title``/``url``/``snippet``/``score`` attributes. Duplicate canonical URLs
    are collapsed by default while preserving first-seen order.
    """
    registry: list[SourceRecord] = []
    seen_urls: set[str] = set()
    for raw in sources or []:
        data = _as_mapping(raw)
        url = str(data.get("url") or data.get("link") or data.get("href") or "").strip()
        canonical = _canonical_url(url)
        if dedupe_urls and canonical and canonical in seen_urls:
            continue
        if canonical:
            seen_urls.add(canonical)

        title = str(data.get("title") or data.get("name") or url or "Untitled source").strip()
        snippet = str(data.get("snippet") or data.get("content") or data.get("text") or "").strip()
        source = str(data.get("source") or data.get("provider") or data.get("engine") or "web").strip() or "web"
        score = _coerce_score(data.get("score") if "score" in data else data.get("relevance_score"))
        metadata = {k: v for k, v in data.items() if k not in {"title", "name", "url", "link", "href", "snippet", "content", "text", "source", "provider", "engine", "score", "relevance_score"}}
        registry.append(
            SourceRecord(
                index=len(registry) + 1,
                title=title,
                url=url,
                snippet=snippet,
                source=source,
                score=score,
                metadata=metadata,
            )
        )
    return registry


def validate_citations(
    answer: str,
    sources: Iterable[Any],
    *,
    policy: CitationPolicy = "strip_invalid",
    dedupe_urls: bool = True,
) -> CitationValidationResult:
    """Validate bracket citation refs in ``answer`` against ``sources``.

    Policies:
    - ``keep``: leave answer unchanged.
    - ``strip_invalid``: remove out-of-range citation tokens only.
    - ``annotate_invalid``: replace invalid tokens with ``[invalid:N]``.
    """
    if policy not in {"keep", "strip_invalid", "annotate_invalid"}:
        raise ValueError("policy must be one of: keep, strip_invalid, annotate_invalid")

    original = str(answer or "")
    registry = build_source_registry(sources, dedupe_urls=dedupe_urls)
    max_index = len(registry)
    citations: list[CitationRef] = []
    valid_set: set[int] = set()
    invalid_set: set[int] = set()

    for match in _CITATION_RE.finditer(original):
        idx = int(match.group(1))
        valid = 1 <= idx <= max_index
        citations.append(CitationRef(idx, match.start(), match.end(), match.group(0), valid))
        if valid:
            valid_set.add(idx)
        else:
            invalid_set.add(idx)

    repaired = original
    if policy == "strip_invalid":
        repaired = _CITATION_RE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= max_index else "", original)
        repaired = re.sub(r" {2,}", " ", repaired).strip()
    elif policy == "annotate_invalid":
        repaired = _CITATION_RE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= max_index else f"[invalid:{m.group(1)}]", original)

    cited_indices = sorted(valid_set)
    all_indices = {item.index for item in registry}
    uncited = sorted(all_indices - valid_set)

    return CitationValidationResult(
        answer=repaired,
        original_answer=original,
        registry=registry,
        citations=citations,
        valid_indices=cited_indices,
        invalid_indices=sorted(invalid_set),
        cited_indices=cited_indices,
        uncited_indices=uncited,
        policy=policy,
    )


def extract_citation_indices(answer: str) -> list[int]:
    """Return citation indices in textual order, including duplicates."""
    return [int(m.group(1)) for m in _CITATION_RE.finditer(str(answer or ""))]


def _as_mapping(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        try:
            mapped = raw.to_dict()
            if isinstance(mapped, dict):
                return dict(mapped)
        except Exception:
            pass
    if hasattr(raw, "__dataclass_fields__"):
        try:
            return asdict(raw)
        except Exception:
            pass
    data: dict[str, Any] = {}
    for name in ("title", "url", "snippet", "content", "source", "provider", "engine", "score", "relevance_score"):
        if hasattr(raw, name):
            data[name] = getattr(raw, name)
    return data


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/")
        return urlunsplit((scheme, netloc, path, "", ""))
    except Exception:
        return url.strip().rstrip("/").lower()


def _coerce_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
