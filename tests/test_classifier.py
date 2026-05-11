"""Unit tests for :mod:`helpers.classifier`.

These tests intentionally avoid any A0 imports — the classifier accepts a
plain async callable for the LLM, so we mock that directly. Run with::

    pytest plugins/a0_fauxplexica/tests/test_classifier.py -v
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import pytest

# Make ``helpers.*`` importable when pytest is invoked from any cwd. We add
# the plugin root (parent of this ``tests/`` dir) to ``sys.path``.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HERE)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from helpers import classifier as cls  # noqa: E402
from helpers.classifier import (  # noqa: E402
    _extract_urls,
    _is_greeting,
    _is_lone_url,
    _is_pure_math,
    _try_parse_json,
    classify,
)
from helpers.types import ClassifierOutput  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm(payload: Any, calls: list[tuple[str, str]] | None = None):
    """Return an async LLM stub that emits *payload* (str|dict) on call."""

    async def _llm(system: str, message: str) -> str:
        if calls is not None:
            calls.append((system, message))
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)

    return _llm


def _make_raising_llm(exc: Exception):
    async def _llm(_s: str, _m: str) -> str:
        raise exc

    return _llm


FULL_SOURCES = {"web", "academic", "discussions"}
FULL_WIDGETS = {"weather", "stock", "calculation"}


# ---------------------------------------------------------------------------
# URL regex
# ---------------------------------------------------------------------------


class TestUrlExtraction:
    def test_simple_https(self):
        assert _extract_urls("see https://example.com here") == [
            "https://example.com"
        ]

    def test_http_with_path(self):
        assert _extract_urls("go to http://foo.bar/baz/qux?x=1") == [
            "http://foo.bar/baz/qux?x=1"
        ]

    def test_strips_trailing_punctuation(self):
        assert _extract_urls("visit https://example.com.") == [
            "https://example.com"
        ]
        assert _extract_urls("see (https://example.com)") == [
            "https://example.com"
        ]

    def test_www_normalised_to_https(self):
        assert _extract_urls("www.example.com is cool") == [
            "https://www.example.com"
        ]

    def test_multiple_dedup_preserves_order(self):
        out = _extract_urls(
            "compare https://a.com and https://b.com and https://a.com again"
        )
        assert out == ["https://a.com", "https://b.com"]

    def test_no_url(self):
        assert _extract_urls("just a plain question") == []

    def test_empty_input(self):
        assert _extract_urls("") == []
        assert _extract_urls(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fast-path heuristics
# ---------------------------------------------------------------------------


class TestPureMath:
    @pytest.mark.parametrize(
        "expr",
        [
            "2+2",
            "3 * (4 + 5)",
            "100 / 7",
            "2^10",
            "1.5 + 2.5",
            "sqrt(16)",
            "sin(0) + cos(0)",
        ],
    )
    def test_positive(self, expr):
        assert _is_pure_math(expr) is True

    @pytest.mark.parametrize(
        "expr",
        [
            "",
            "hello",
            "what is 2+2?",  # has '?'
            "calculate 2 plus 2",  # words
            "42",  # bare number, no op
            "foo+bar",  # alphabetic non-function
        ],
    )
    def test_negative(self, expr):
        assert _is_pure_math(expr) is False


class TestLoneUrl:
    def test_just_url(self):
        urls = _extract_urls("https://example.com")
        assert _is_lone_url("https://example.com", urls)

    def test_url_with_trailing_period(self):
        urls = _extract_urls("https://example.com.")
        assert _is_lone_url("https://example.com.", urls)

    def test_url_with_question(self):
        urls = _extract_urls("summarise https://example.com please")
        assert not _is_lone_url("summarise https://example.com please", urls)

    def test_two_urls(self):
        urls = _extract_urls("https://a.com https://b.com")
        assert not _is_lone_url("https://a.com https://b.com", urls)


class TestGreeting:
    @pytest.mark.parametrize(
        "text",
        ["hi", "Hello", "hey!", "good morning", "thanks", "thank you", "bye"],
    )
    def test_positive(self, text):
        assert _is_greeting(text)

    @pytest.mark.parametrize(
        "text",
        ["hi, how does photosynthesis work", "hello world programming", "", "this is not a greeting at all and is too long indeed"],
    )
    def test_negative(self, text):
        assert not _is_greeting(text)


# ---------------------------------------------------------------------------
# JSON parse
# ---------------------------------------------------------------------------


class TestJsonParse:
    def test_direct(self):
        assert _try_parse_json('{"a": 1}') == {"a": 1}

    def test_code_fence(self):
        s = "```json\n{\"a\": 1}\n```"
        assert _try_parse_json(s) == {"a": 1}

    def test_with_chatter(self):
        s = "Sure, here is the JSON:\n{\"a\": 1, \"b\": 2}\nHope that helps."
        assert _try_parse_json(s) == {"a": 1, "b": 2}

    def test_invalid_returns_none(self):
        assert _try_parse_json("not json at all") is None
        assert _try_parse_json("") is None

    def test_non_object_returns_none(self):
        # `[1,2,3]` is valid JSON but not a dict; classifier requires dict.
        assert _try_parse_json("[1,2,3]") is None


# ---------------------------------------------------------------------------
# classify() — fast-path branches (LLM should NOT be called)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_empty_query():
    calls: list = []
    out = await classify("", [], FULL_SOURCES, FULL_WIDGETS, _make_llm({}, calls))
    assert isinstance(out, ClassifierOutput)
    assert out.routing.skip_search is True
    assert out._fastpath_reason == "empty_query"
    assert calls == []  # LLM never called


@pytest.mark.asyncio
async def test_classify_pure_math_fastpath():
    calls: list = []
    out = await classify("2 + 2 * 3", [], FULL_SOURCES, FULL_WIDGETS, _make_llm({}, calls))
    assert out._fastpath_reason == "pure_math"
    assert out.routing.skip_search is True
    assert out.routing.widgets.calculation is True
    assert out.style.primary_type == "science_math"
    assert calls == []


@pytest.mark.asyncio
async def test_classify_pure_math_widget_disabled():
    """AND-gate must clip calculation widget when not enabled."""
    out = await classify(
        "2 + 2",
        [],
        FULL_SOURCES,
        set(),  # no widgets enabled
        _make_llm({}),
    )
    assert out._fastpath_reason == "pure_math"
    assert out.routing.widgets.calculation is False


@pytest.mark.asyncio
async def test_classify_lone_url_fastpath():
    calls: list = []
    out = await classify(
        "https://example.com", [], FULL_SOURCES, FULL_WIDGETS, _make_llm({}, calls)
    )
    assert out._fastpath_reason == "lone_url"
    assert out.style.primary_type == "url_lookup"
    assert out.detected_urls == ["https://example.com"]
    assert calls == []


@pytest.mark.asyncio
async def test_classify_greeting_fastpath():
    calls: list = []
    out = await classify(
        "hello!", [], FULL_SOURCES, FULL_WIDGETS, _make_llm({}, calls)
    )
    assert out._fastpath_reason == "greeting"
    assert out.routing.skip_search is True
    assert calls == []


# ---------------------------------------------------------------------------
# classify() — LLM-backed path
# ---------------------------------------------------------------------------


GOOD_PAYLOAD = {
    "routing": {
        "skip_search": False,
        "personal_search": False,
        "academic_search": True,
        "discussion_search": False,
        "widgets": {"weather": False, "stock": False, "calculation": False},
    },
    "style": {
        "primary_type": "academic_research",
        "freshness": "any",
        "depth_hint": "deep",
    },
    "standalone_followup": "Survey transformer architectures for protein folding.",
    "detected_urls": [],
}


@pytest.mark.asyncio
async def test_classify_llm_happy_path():
    calls: list = []
    out = await classify(
        "survey of transformer architectures for protein folding",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm(GOOD_PAYLOAD, calls),
    )
    assert out._fastpath_reason is None  # LLM path taken
    assert len(calls) == 1
    assert out.routing.academic_search is True
    assert out.style.primary_type == "academic_research"
    assert out.style.depth_hint == "deep"
    assert out.standalone_followup.startswith("Survey")


@pytest.mark.asyncio
async def test_classify_and_gates_academic_disabled():
    """Even if the LLM votes academic_search, AND-gate must clip it."""
    out = await classify(
        "survey of transformer architectures for protein folding",
        [],
        {"web"},  # academic disabled
        FULL_WIDGETS,
        _make_llm(GOOD_PAYLOAD),
    )
    assert out.routing.academic_search is False


@pytest.mark.asyncio
async def test_classify_and_gates_discussions_disabled():
    payload = dict(GOOD_PAYLOAD)
    payload["routing"] = dict(GOOD_PAYLOAD["routing"])
    payload["routing"]["discussion_search"] = True
    out = await classify(
        "opinions on the new pixel phone",
        [],
        {"web", "academic"},  # discussions disabled
        FULL_WIDGETS,
        _make_llm(payload),
    )
    assert out.routing.discussion_search is False


@pytest.mark.asyncio
async def test_classify_and_gates_all_widgets():
    payload = {
        "routing": {
            "skip_search": False,
            "personal_search": False,
            "academic_search": False,
            "discussion_search": False,
            "widgets": {"weather": True, "stock": True, "calculation": True},
        },
        "style": {"primary_type": "general", "freshness": "any", "depth_hint": "medium"},
        "standalone_followup": "some question that triggers all widgets somehow",
        "detected_urls": [],
    }
    out = await classify(
        "some question that triggers all widgets somehow",
        [],
        FULL_SOURCES,
        set(),  # no widgets enabled
        _make_llm(payload),
    )
    assert out.routing.widgets.weather is False
    assert out.routing.widgets.stock is False
    assert out.routing.widgets.calculation is False


@pytest.mark.asyncio
async def test_classify_url_passed_to_prompt():
    """Regex-detected URLs must be passed to the LLM prompt."""
    calls: list = []
    await classify(
        "summarise https://example.com/article please",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm(GOOD_PAYLOAD, calls),
    )
    assert len(calls) == 1
    _system, user = calls[0]
    assert "https://example.com/article" in user


@pytest.mark.asyncio
async def test_classify_urls_regex_authoritative():
    """LLM-emitted URLs not in regex set are discarded; regex always wins."""
    payload = dict(GOOD_PAYLOAD)
    payload["detected_urls"] = ["https://hallucinated.example/foo"]
    out = await classify(
        "summarise https://real.example/article please",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm(payload),
    )
    # the hallucinated URL must NOT appear; the regex URL must.
    assert "https://hallucinated.example/foo" not in out.detected_urls
    assert "https://real.example/article" in out.detected_urls


# ---------------------------------------------------------------------------
# Error fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_llm_raises_returns_safe_defaults():
    out = await classify(
        "some non-trivial question that won't hit fast-path",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_raising_llm(RuntimeError("backend down")),
    )
    assert isinstance(out, ClassifierOutput)
    assert out.routing.skip_search is False
    assert out.style.primary_type == "general"
    assert out.style.freshness == "any"
    assert out.style.depth_hint == "medium"
    assert out._fastpath_reason and out._fastpath_reason.startswith("llm_error:")


@pytest.mark.asyncio
async def test_classify_invalid_json_returns_safe_defaults():
    out = await classify(
        "some non-trivial question",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm("this is not json, sorry"),
    )
    assert out._fastpath_reason == "json_parse_error"
    assert out.style.primary_type == "general"


@pytest.mark.asyncio
async def test_classify_invalid_json_with_url_biases_url_lookup():
    """When LLM fails and URLs are present, safe-default should prefer url_lookup."""
    out = await classify(
        "check out https://example.com/article-x for details on this thing",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm("garbage"),
    )
    assert out._fastpath_reason == "json_parse_error"
    assert out.style.primary_type == "url_lookup"
    assert "https://example.com/article-x" in out.detected_urls


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_normalises_unknown_primary_type():
    payload = dict(GOOD_PAYLOAD)
    payload["style"] = {
        "primary_type": "made_up_type",
        "freshness": "yesterday",  # invalid
        "depth_hint": "epic",  # invalid
    }
    out = await classify(
        "some question",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm(payload),
    )
    assert out.style.primary_type == "general"
    assert out.style.freshness == "any"
    assert out.style.depth_hint == "medium"


@pytest.mark.asyncio
async def test_classify_coerces_string_bools():
    """Some LLMs emit `"true"`/`"false"` strings; we must coerce them."""
    payload = {
        "routing": {
            "skip_search": "true",
            "personal_search": "false",
            "academic_search": "yes",
            "discussion_search": 0,
            "widgets": {"weather": 1, "stock": "no", "calculation": False},
        },
        "style": {"primary_type": "general", "freshness": "any", "depth_hint": "short"},
        "standalone_followup": "x",
        "detected_urls": [],
    }
    out = await classify("x", [], FULL_SOURCES, FULL_WIDGETS, _make_llm(payload))
    assert out.routing.skip_search is True
    assert out.routing.personal_search is False
    assert out.routing.academic_search is True
    assert out.routing.discussion_search is False
    assert out.routing.widgets.weather is True
    assert out.routing.widgets.stock is False


@pytest.mark.asyncio
async def test_classify_missing_standalone_falls_back_to_query():
    payload = dict(GOOD_PAYLOAD)
    payload.pop("standalone_followup", None)
    out = await classify(
        "original question text",
        [],
        FULL_SOURCES,
        FULL_WIDGETS,
        _make_llm(payload),
    )
    assert out.standalone_followup == "original question text"


@pytest.mark.asyncio
async def test_classify_drops_unknown_enables():
    """Unknown keys in enabled_sources/widgets must be ignored, not error."""
    out = await classify(
        "some question",
        [],
        {"web", "academic", "badsource"},  # badsource ignored
        {"weather", "laser"},  # laser ignored
        _make_llm(GOOD_PAYLOAD),
    )
    # academic_search retained (academic enabled); discussion_search clipped
    assert out.routing.academic_search is True


# ---------------------------------------------------------------------------
# to_dict shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classifier_output_to_dict_shape():
    out = await classify(
        "hello", [], FULL_SOURCES, FULL_WIDGETS, _make_llm(GOOD_PAYLOAD)
    )
    d = out.to_dict()
    assert set(d.keys()) == {"routing", "style", "standalone_followup", "detected_urls"}
    assert set(d["routing"].keys()) == {
        "skip_search",
        "personal_search",
        "academic_search",
        "discussion_search",
        "widgets",
    }
    assert set(d["routing"]["widgets"].keys()) == {"weather", "stock", "calculation"}
    assert set(d["style"].keys()) == {"primary_type", "freshness", "depth_hint"}
