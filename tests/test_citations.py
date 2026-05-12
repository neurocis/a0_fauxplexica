from __future__ import annotations

from dataclasses import dataclass

from helpers.citations import (
    build_source_registry,
    extract_citation_indices,
    validate_citations,
)


def test_build_source_registry_normalizes_and_dedupes_urls():
    sources = [
        {"title": "A", "url": "https://Example.com/path/", "snippet": "one", "score": "0.9"},
        {"title": "Duplicate", "url": "https://example.com/path", "snippet": "two"},
        {"name": "B", "link": "https://b.test", "provider": "academic"},
    ]
    registry = build_source_registry(sources)
    assert [r.index for r in registry] == [1, 2]
    assert registry[0].title == "A"
    assert registry[0].score == 0.9
    assert registry[1].source == "academic"


def test_validate_keeps_valid_citations_and_reports_uncited():
    result = validate_citations("Alpha [1].", [{"title": "A", "url": "https://a"}, {"title": "B", "url": "https://b"}])
    assert result.ok is True
    assert result.answer == "Alpha [1]."
    assert result.valid_indices == [1]
    assert result.invalid_indices == []
    assert result.uncited_indices == [2]


def test_validate_strips_out_of_range_refs_only():
    result = validate_citations("Alpha [1][9] and beta [2].", [{"url": "https://a"}, {"url": "https://b"}])
    assert result.ok is False
    assert result.invalid_indices == [9]
    assert result.answer == "Alpha [1] and beta [2]."
    assert [c.index for c in result.citations] == [1, 9, 2]


def test_validate_annotates_invalid_refs():
    result = validate_citations("Unsupported [3].", [{"url": "https://a"}], policy="annotate_invalid")
    assert result.answer == "Unsupported [invalid:3]."
    assert result.invalid_indices == [3]


def test_validate_keep_policy_does_not_repair_text():
    result = validate_citations("Unsupported [3].", [{"url": "https://a"}], policy="keep")
    assert result.answer == "Unsupported [3]."
    assert result.invalid_indices == [3]


def test_validate_no_sources_makes_all_refs_invalid():
    result = validate_citations("Claim [1].", [])
    assert result.answer == "Claim ."
    assert result.invalid_indices == [1]
    assert result.registry == []


def test_extract_citation_indices_preserves_order_and_duplicates():
    assert extract_citation_indices("A [2][1] B [2]") == [2, 1, 2]


@dataclass
class SourceObj:
    title: str
    url: str
    snippet: str
    score: float


def test_registry_accepts_dataclass_sources():
    registry = build_source_registry([SourceObj("Obj", "https://obj", "snippet", 0.7)])
    assert registry[0].to_dict()["title"] == "Obj"
    assert registry[0].metadata == {}
