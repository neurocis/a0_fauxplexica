"""Tests for ``tools/widget_calc.py`` (no network).

Uses an inline stub LLM callable for the param extractor — no LLM network calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import pytest

from a0_fauxplexica.tools.widget_calc import CalculationWidget


def _classification(calc: bool = True) -> SimpleNamespace:
    return SimpleNamespace(routing=SimpleNamespace(widgets={"calculation": calc}))


def _stub_llm(response: str) -> Callable[..., Any]:
    async def _llm(*, system: str, user: str) -> str:  # noqa: ARG001
        return response
    return _llm


def test_should_execute_routing_flag() -> None:
    w = CalculationWidget()
    assert w.should_execute(_classification(calc=True)) is True
    assert w.should_execute(_classification(calc=False)) is False


def test_should_execute_handles_dict_classification() -> None:
    w = CalculationWidget()
    assert w.should_execute({"routing": {"widgets": {"calculation": True}}}) is True
    assert w.should_execute({"routing": {"widgets": {"calculation": False}}}) is False
    assert w.should_execute({}) is False
    assert w.should_execute(None) is False


@pytest.mark.asyncio
async def test_simple_arithmetic() -> None:
    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="what is 2 + 2",
        classification=_classification(),
        llm=_stub_llm("2 + 2"),
    )
    assert out is not None
    assert out.type == "calculation_result"
    assert out.data["expression"] == "2 + 2"
    assert out.data["result"] == 4
    assert out.data["result_type"] == "number"
    assert out.llm_context == "Calculation: 2 + 2 = 4"


@pytest.mark.asyncio
async def test_sqrt_function() -> None:
    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="sqrt 144",
        classification=_classification(),
        llm=_stub_llm("sqrt(144)"),
    )
    assert out is not None
    assert out.data["result"] == 12.0


@pytest.mark.asyncio
async def test_percent_calc() -> None:
    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="15% of 240",
        classification=_classification(),
        llm=_stub_llm("0.15 * 240"),
    )
    assert out is not None
    assert out.data["result"] == pytest.approx(36.0)


@pytest.mark.asyncio
async def test_not_present_returns_no_expression_output() -> None:
    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="what's the weather?",
        classification=_classification(),
        llm=_stub_llm("NOT_PRESENT"),
    )
    assert out is not None
    assert out.type == "calculation_result"
    assert out.data["error"] == "no_expression"
    assert out.llm_context == "No math expression detected."


@pytest.mark.asyncio
async def test_extractor_failure_graceful() -> None:
    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("llm down")

    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="anything",
        classification=_classification(),
        llm=boom,
    )
    assert out is not None
    assert out.llm_context == "Failed to fetch calculation_result data."
    assert "llm down" in out.data["error"]


@pytest.mark.asyncio
async def test_eval_error_graceful() -> None:
    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="divide by zero",
        classification=_classification(),
        llm=_stub_llm("1 / 0"),
    )
    assert out is not None
    # asteval surfaces ZeroDivisionError via interp.error.
    assert out.data["expression"] == "1 / 0"
    assert "error" in out.data
    assert "Could not evaluate" in out.llm_context


@pytest.mark.asyncio
async def test_strips_code_fences() -> None:
    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="compute",
        classification=_classification(),
        llm=_stub_llm("```python\n3 * 7\n```"),
    )
    assert out is not None
    assert out.data["expression"] == "3 * 7"
    assert out.data["result"] == 21


@pytest.mark.asyncio
async def test_call_utility_model_shape_supported() -> None:
    """Make sure an agent-like LLM (call_utility_model) is supported."""

    class AgentLike:
        async def call_utility_model(self, system: str, message: str) -> str:  # noqa: ARG002
            return "10 - 4"

    w = CalculationWidget()
    out = await w.execute(
        chat_history=[],
        follow_up="10 minus 4",
        classification=_classification(),
        llm=AgentLike(),
    )
    assert out is not None
    assert out.data["result"] == 6
