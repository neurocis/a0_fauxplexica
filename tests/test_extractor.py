"""Tests for helpers.extractor."""

from __future__ import annotations

import asyncio

import pytest

from helpers.extractor import extract_facts


class TrackingLLM:
    def __init__(self):
        self.prompts = []
        self.active = 0
        self.max_active = 0

    async def structured(self, prompt, schema=None):
        self.prompts.append(prompt)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return {"extracted_facts": f"- facts for chunk {len(self.prompts)}"}


@pytest.mark.asyncio
async def test_extract_facts_splits_content_and_uses_semaphore():
    # 8001 chars => 3 chunks with 4000/500 split.
    content = "a" * 8001
    llm = TrackingLLM()
    sem = asyncio.Semaphore(1)

    out = await extract_facts("https://example.test", content, "query", llm, semaphore=sem)

    assert out.count("- facts for chunk") == 3
    assert len(llm.prompts) == 3
    assert llm.max_active == 1
    assert "telegram-style bullets" in llm.prompts[0]
    assert "Preserve numbers" in llm.prompts[0]


@pytest.mark.asyncio
async def test_extract_facts_json_string_response():
    async def llm(_prompt):
        return '{"extracted_facts": "- one\\n- two"}'

    out = await extract_facts("u", "short content", "q", llm, semaphore=asyncio.Semaphore(3))
    assert out == "- one\n- two"


@pytest.mark.asyncio
async def test_extract_facts_empty_content_returns_empty_without_call():
    called = False

    def llm(_prompt):
        nonlocal called
        called = True
        return {"extracted_facts": "x"}

    assert await extract_facts("u", "", "q", llm, semaphore=asyncio.Semaphore(1)) == ""
    assert called is False
