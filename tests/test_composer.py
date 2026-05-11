"""Unit tests for :mod:`helpers.composer`.

No live network or A0 runtime imports are used.  The composer accepts a plain
async LLM callable, so tests capture the system/user prompt pair directly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HERE)
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from helpers.composer import (  # noqa: E402
    STYLE_PROMPT_FILES,
    compose_answer,
    render_context,
    select_prompt_path,
)
from helpers.types import ClassifierOutput, RoutingFlags, StyleHints  # noqa: E402


@dataclass
class ChunkLike:
    content: str
    metadata: dict[str, Any]


class CaptureLLM:
    def __init__(self, response: str = "final answer") -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, message: str) -> str:
        self.calls.append((system, message))
        return self.response


class RaisingLLM:
    async def __call__(self, _system: str, _message: str) -> str:
        raise RuntimeError("model offline")


class EmitStream:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def emit(self, block_type: str, content: str) -> None:
        self.events.append((block_type, content))


def _classification(primary_type: str) -> ClassifierOutput:
    return ClassifierOutput(
        routing=RoutingFlags(),
        style=StyleHints(primary_type=primary_type),  # type: ignore[arg-type]
        standalone_followup="standalone query",
        detected_urls=[],
    )


def _sources() -> list[Any]:
    return [
        {"title": "First", "url": "https://one.example", "content": "First content."},
        ChunkLike(
            content="Second content.",
            metadata={"title": "Second", "url": "https://two.example"},
        ),
    ]


@pytest.mark.parametrize(
    ("primary_type", "filename", "needle"),
    [
        ("general", "composer_general.md", "general answer composer"),
        ("academic_research", "composer_academic.md", "academic-research composer"),
        ("recent_news", "composer_news.md", "recent-news composer"),
        ("coding", "composer_coding.md", "coding composer"),
        ("people", "composer_people.md", "people composer"),
        ("url_lookup", "composer_url.md", "URL-lookup composer"),
        ("weather", "composer_weather.md", "weather composer"),
        ("recipe", "composer_recipe.md", "recipe composer"),
        ("translation", "composer_translation.md", "translation composer"),
        ("creative_writing", "composer_creative.md", "creative-writing composer"),
        ("science_math", "composer_science_math.md", "science-and-math composer"),
    ],
)
@pytest.mark.asyncio
async def test_prompt_selection_per_primary_type(primary_type: str, filename: str, needle: str):
    llm = CaptureLLM()
    out = await compose_answer(
        query="q",
        classification=_classification(primary_type),
        chat_history=[],
        search_findings=_sources(),
        widget_outputs=[],
        mode="balanced",
        llm=llm,
        config={},
    )
    assert out == "final answer"
    assert select_prompt_path(primary_type).name == filename
    assert STYLE_PROMPT_FILES[primary_type] == filename
    assert needle in llm.calls[0][0]


@pytest.mark.asyncio
async def test_unknown_prompt_type_falls_back_to_general():
    llm = CaptureLLM()
    await compose_answer(
        query="q",
        classification=_classification("unknown"),
        chat_history=[],
        search_findings=[],
        widget_outputs=[],
        mode="speed",
        llm=llm,
        config={},
    )
    assert "general answer composer" in llm.calls[0][0]


def test_context_rendering_result_markers():
    context = render_context(_sources(), [])
    assert '<search_results note="These are the search results and assistant can cite these">' in context
    assert '<result index=1 title="First" url="https://one.example">First content.</result>' in context
    assert '<result index=2 title="Second" url="https://two.example">Second content.</result>' in context
    assert "</search_results>" in context


def test_widgets_context_wrapped_with_do_not_cite_note():
    context = render_context([], [{"type": "weather", "llm_context": "Weather: sunny."}])
    assert '<widgets_result noteForAssistant="Widgets are factual UI data. Do not cite widgets as sources.">' in context
    assert "Weather: sunny." in context
    assert "</widgets_result>" in context


def test_context_budget_truncation():
    long_source = [{"title": "Long", "url": "https://long.example", "content": "x" * 500}]
    context = render_context(long_source, [], context_budget_chars=180)
    assert len(context) <= 180
    assert "Context budget reached" in context
    assert "</widgets_result>" in context


@pytest.mark.asyncio
async def test_translation_and_creative_prompts_do_not_require_citations():
    for primary in ("translation", "creative_writing"):
        llm = CaptureLLM()
        await compose_answer(
            query="q",
            classification=_classification(primary),
            chat_history=[],
            search_findings=_sources(),
            widget_outputs=[],
            mode="balanced",
            llm=llm,
            config={},
        )
        system_prompt = llm.calls[0][0]
        assert "Do not require citations" in system_prompt
        assert "No References section" not in system_prompt


@pytest.mark.asyncio
async def test_url_lookup_prompt_enforces_source_one():
    llm = CaptureLLM()
    await compose_answer(
        query="summarize https://one.example",
        classification=_classification("url_lookup"),
        chat_history=[],
        search_findings=_sources(),
        widget_outputs=[],
        mode="speed",
        llm=llm,
        config={},
    )
    system_prompt = llm.calls[0][0]
    assert "using only the corresponding URL/source supplied as search result 1" in system_prompt
    assert "[1] only" in system_prompt
    assert "Do not cite any number except [1]" in system_prompt


@pytest.mark.asyncio
async def test_block_stream_optional_noop_and_emit_behavior():
    no_stream_llm = CaptureLLM("answer without stream")
    out = await compose_answer(
        query="q",
        classification=_classification("general"),
        chat_history=[],
        search_findings=[],
        widget_outputs=[],
        mode="speed",
        llm=no_stream_llm,
        config={},
    )
    assert out == "answer without stream"

    stream = EmitStream()
    stream_llm = CaptureLLM("answer with stream")
    out = await compose_answer(
        query="q",
        classification=_classification("general"),
        chat_history=[],
        search_findings=[],
        widget_outputs=[],
        mode="speed",
        llm=stream_llm,
        config={},
        block_stream=stream,
    )
    assert out == "answer with stream"
    assert stream.events == [("text", "answer with stream")]


@pytest.mark.asyncio
async def test_llm_error_fallback_returns_useful_string():
    """Documented choice: composer returns a useful string, not an exception."""

    out = await compose_answer(
        query="q",
        classification=_classification("general"),
        chat_history=[],
        search_findings=[],
        widget_outputs=[],
        mode="speed",
        llm=RaisingLLM(),
        config={},
    )
    assert "couldn't compose the final answer" in out
    assert "model offline" in out
