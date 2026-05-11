"""Tests for helpers.picker."""

from __future__ import annotations

import pytest

from helpers.picker import pick_results


class StructuredLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = None
        self.schema = None

    async def structured(self, prompt, schema=None):
        self.prompt = prompt
        self.schema = schema
        return self.payload


@pytest.mark.asyncio
async def test_pick_results_single_structured_call_and_caps_indices():
    results = [
        {"title": "a", "url": "https://a", "content": "A"},
        {"title": "b", "url": "https://b", "content": "B"},
        {"title": "c", "url": "https://c", "content": "C"},
        {"title": "d", "url": "https://d", "content": "D"},
    ]
    llm = StructuredLLM({"picked_indices": [3, 1, 1, 99, 0]})

    out = await pick_results("query", results, llm, max_picks=2)

    assert out == [3, 1]
    assert "favor" in llm.prompt.lower()
    assert "diversity" in llm.prompt.lower()
    assert llm.schema["type"] == "object"


@pytest.mark.asyncio
async def test_pick_results_parses_json_string():
    out = await pick_results(
        "q",
        [{"title": "a"}, {"title": "b"}],
        lambda _prompt: '{"picked_indices": ["1", "0"]}',
        max_picks=3,
    )
    assert out == [1, 0]


@pytest.mark.asyncio
async def test_pick_results_empty_or_zero_max_returns_empty_without_call():
    called = False

    def llm(_prompt):
        nonlocal called
        called = True
        return {"picked_indices": [0]}

    assert await pick_results("q", [], llm) == []
    assert await pick_results("q", [{"title": "a"}], llm, max_picks=0) == []
    assert called is False
