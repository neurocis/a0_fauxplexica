import asyncio
import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

import pytest

from helpers.blockstream import BlockStream
from helpers.orchestrator import run_fauxplexica_search
from helpers.types import ClassifierOutput
from helpers.widgets_registry import WidgetOutput


async def _llm(*_args, **_kwargs):
    return "{}"


@pytest.mark.asyncio
async def test_orchestrator_calls_classifier_widgets_researcher_composer_in_order(monkeypatch):
    import helpers.orchestrator as orchestrator

    calls = []
    classification = ClassifierOutput(standalone_followup="standalone question")

    async def fake_classify(**kwargs):
        calls.append("classify")
        assert kwargs["query"] == "question"
        return classification

    async def fake_widgets(**kwargs):
        calls.append("widgets_start")
        await asyncio.sleep(0.01)
        calls.append("widgets_end")
        assert kwargs["follow_up"] == "standalone question"
        return [WidgetOutput(type="weather", llm_context="sunny", data={"temp": 70})]

    async def fake_research(**kwargs):
        calls.append("research_start")
        assert kwargs["file_ids"] == ["file-1"]
        assert isinstance(kwargs["block_stream"], BlockStream)
        await asyncio.sleep(0.01)
        calls.append("research_end")
        return {"sources": [{"title": "T", "url": "https://example.test", "content": "C"}]}

    async def fake_compose_answer(**kwargs):
        calls.append("compose")
        assert kwargs["sources"][0]["url"] == "https://example.test"
        assert kwargs["widgets"][0]["type"] == "weather"
        return "final answer"

    monkeypatch.setattr(orchestrator, "classify", fake_classify)
    monkeypatch.setattr(orchestrator, "execute_all", fake_widgets)
    researcher = ModuleType("helpers.researcher")
    researcher.research = fake_research
    composer = ModuleType("helpers.composer")
    composer.compose_answer = fake_compose_answer
    monkeypatch.setitem(sys.modules, "helpers.researcher", researcher)
    monkeypatch.setitem(sys.modules, "helpers.composer", composer)

    result = await run_fauxplexica_search(query="question", file_ids=["file-1"], llm=_llm)

    assert calls[0] == "classify"
    assert "widgets_start" in calls and "research_start" in calls
    assert calls[-1] == "compose"
    assert result["answer"] == "final answer"
    assert result["sources"] == [{"title": "T", "url": "https://example.test", "content": "C"}]
    assert result["widgets"] == [{"type": "weather", "llm_context": "sunny", "data": {"temp": 70}}]
    assert result["mode"] == "balanced"
    assert result["citations"] == []
    assert any(block["type"] == "widget" for block in result["blocks"])
    assert any(block["type"] == "text" for block in result["blocks"])


@pytest.mark.asyncio
async def test_widgets_and_research_are_invoked_concurrently(monkeypatch):
    import helpers.orchestrator as orchestrator

    markers = []

    async def fake_classify(**_kwargs):
        return ClassifierOutput(standalone_followup="q")

    async def fake_widgets(**_kwargs):
        markers.append("widgets_started")
        await asyncio.sleep(0.05)
        markers.append("widgets_finished")
        return []

    async def fake_research(**_kwargs):
        markers.append("research_started")
        await asyncio.sleep(0.01)
        markers.append("research_finished")
        return {"sources": []}

    monkeypatch.setattr(orchestrator, "classify", fake_classify)
    monkeypatch.setattr(orchestrator, "execute_all", fake_widgets)
    researcher = ModuleType("helpers.researcher")
    researcher.research = fake_research
    monkeypatch.setitem(sys.modules, "helpers.researcher", researcher)
    monkeypatch.delitem(sys.modules, "helpers.composer", raising=False)

    await run_fauxplexica_search(query="q", llm=_llm)

    assert markers.index("research_started") < markers.index("widgets_finished")


@pytest.mark.asyncio
async def test_fallback_when_researcher_and_composer_are_unavailable(monkeypatch):
    import helpers.orchestrator as orchestrator

    async def fake_classify(**_kwargs):
        return ClassifierOutput(standalone_followup="q")

    async def fake_widgets(**_kwargs):
        return []

    monkeypatch.setattr(orchestrator, "classify", fake_classify)
    monkeypatch.setattr(orchestrator, "execute_all", fake_widgets)
    monkeypatch.setitem(sys.modules, "helpers.researcher", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "helpers.composer", SimpleNamespace())

    result = await run_fauxplexica_search(query="q", llm=_llm)

    assert result["answer"].startswith("Composer pending:")
    assert result["sources"] == []
    assert result["widgets"] == []
    assert result["classification"]["standalone_followup"] == "q"
    assert result["mode"] == "balanced"
    assert isinstance(result["blocks"], list)


@pytest.mark.asyncio
async def test_output_shape_and_file_ids_pass_through(monkeypatch):
    import helpers.orchestrator as orchestrator

    seen = {}

    async def fake_classify(**_kwargs):
        return ClassifierOutput(standalone_followup="shape query")

    async def fake_widgets(**_kwargs):
        return []

    async def fake_research(**kwargs):
        seen["file_ids"] = kwargs["file_ids"]
        return {"sources": []}

    async def fake_compose_answer(**_kwargs):
        return "answer"

    monkeypatch.setattr(orchestrator, "classify", fake_classify)
    monkeypatch.setattr(orchestrator, "execute_all", fake_widgets)
    researcher = ModuleType("helpers.researcher")
    researcher.research = fake_research
    composer = ModuleType("helpers.composer")
    composer.compose_answer = fake_compose_answer
    monkeypatch.setitem(sys.modules, "helpers.researcher", researcher)
    monkeypatch.setitem(sys.modules, "helpers.composer", composer)

    result = await run_fauxplexica_search(query="shape", file_ids=["a", "b"], llm=_llm)

    assert set(result) == {"answer", "classification", "sources", "citations", "widgets", "mode", "blocks"}
    assert result["mode"] == "balanced"
    assert seen["file_ids"] == ["a", "b"]
