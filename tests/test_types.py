"""Tests for helpers.types SearchResult dataclass."""

from __future__ import annotations

from helpers.types import (
    ExtractorChunkOutput,
    PickerOutput,
    SearchResult,
    from_dict,
    to_dict,
)


def test_searchresult_from_dict_minimal():
    sr = SearchResult.from_dict({"title": "T", "url": "https://x", "content": "c"})
    assert sr.title == "T"
    assert sr.url == "https://x"
    assert sr.content == "c"
    assert sr.engine == ""
    assert sr.score is None
    assert sr.similarity is None
    assert sr.extra == {}


def test_searchresult_from_dict_camelcase_published_date():
    sr = SearchResult.from_dict(
        {"title": "T", "url": "u", "content": "c", "publishedDate": "2026-01-02"}
    )
    assert sr.published_date == "2026-01-02"
    # Ensure the camelCase key is not duplicated into extra.
    assert "publishedDate" not in sr.extra


def test_searchresult_from_dict_unknown_keys_go_to_extra():
    sr = SearchResult.from_dict(
        {
            "title": "T",
            "url": "u",
            "content": "c",
            "thumbnail": "https://img",
            "length": 42,
        }
    )
    assert sr.extra == {"thumbnail": "https://img", "length": 42}


def test_searchresult_from_dict_bad_score_returns_none():
    sr = SearchResult.from_dict({"title": "T", "url": "u", "content": "c", "score": "NaN-ish"})
    assert sr.score is None


def test_searchresult_to_dict_drops_empties():
    sr = SearchResult(title="T", url="u", content="c", engine="google")
    d = sr.to_dict()
    assert d == {"title": "T", "url": "u", "content": "c", "engine": "google"}
    # Optional fields absent.
    assert "score" not in d
    assert "similarity" not in d
    assert "extra" not in d


def test_searchresult_to_dict_includes_populated_optionals():
    sr = SearchResult(
        title="T",
        url="u",
        content="c",
        engine="arxiv",
        score=0.42,
        published_date="2026-01-02",
        category="science",
        similarity=0.91,
        extra={"thumb": "x"},
    )
    d = sr.to_dict()
    assert d["score"] == 0.42
    assert d["published_date"] == "2026-01-02"
    assert d["category"] == "science"
    assert d["similarity"] == 0.91
    assert d["extra"] == {"thumb": "x"}


def test_module_helpers_are_thin_wrappers():
    sr = from_dict({"title": "t", "url": "u", "content": "c"})
    assert isinstance(sr, SearchResult)
    assert to_dict(sr) == sr.to_dict()


def test_picker_and_extractor_defaults():
    assert PickerOutput().picked_indices == []
    assert ExtractorChunkOutput().extracted_facts == ""
