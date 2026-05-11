"""Tests for ``helpers/widgets_registry.py`` (no network)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from a0_fauxplexica.helpers.widgets_registry import (
    WidgetOutput,
    build_failure_output,
    execute_all,
)


def _classification(weather: bool = False, calc: bool = False, stock: bool = False) -> SimpleNamespace:
    """Build a duck-typed classifier output the registry can read."""
    return SimpleNamespace(
        routing=SimpleNamespace(
            widgets={"weather": weather, "calculation": calc, "stock": stock}
        )
    )


class _StubWidget:
    """Minimal Widget impl for executor tests."""

    def __init__(
        self,
        type: str,
        trigger_key: str,
        *,
        output: Optional[WidgetOutput] = None,
        raise_exc: Optional[BaseException] = None,
        predicate_raises: bool = False,
    ) -> None:
        self.type = type
        self._trigger_key = trigger_key
        self._output = output
        self._raise_exc = raise_exc
        self._predicate_raises = predicate_raises
        self.execute_calls = 0

    def should_execute(self, classification: Any) -> bool:
        if self._predicate_raises:
            raise RuntimeError("predicate boom")
        widgets = classification.routing.widgets
        return bool(widgets.get(self._trigger_key, False))

    async def execute(self, **kwargs: Any) -> Optional[WidgetOutput]:
        self.execute_calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._output


@pytest.mark.asyncio
async def test_no_widgets_triggered_returns_empty() -> None:
    widgets = [_StubWidget("weather", "weather"), _StubWidget("stock", "stock")]
    out = await execute_all(
        classification=_classification(),
        chat_history=[],
        follow_up="hi",
        llm=None,
        enabled={"weather", "stock"},
        widgets=widgets,
    )
    assert out == []
    assert all(w.execute_calls == 0 for w in widgets)


@pytest.mark.asyncio
async def test_disabled_widget_is_skipped_even_when_triggered() -> None:
    weather = _StubWidget(
        "weather",
        "weather",
        output=WidgetOutput(type="weather", llm_context="x", data={}),
    )
    out = await execute_all(
        classification=_classification(weather=True),
        chat_history=[],
        follow_up="weather?",
        llm=None,
        enabled=set(),  # weather disabled in config
        widgets=[weather],
    )
    assert out == []
    assert weather.execute_calls == 0


@pytest.mark.asyncio
async def test_triggered_widget_runs() -> None:
    ok = WidgetOutput(type="calc", llm_context="1+1=2", data={"r": 2})
    calc = _StubWidget("calc", "calculation", output=ok)
    out = await execute_all(
        classification=_classification(calc=True),
        chat_history=[],
        follow_up="what is 1+1",
        llm=None,
        enabled={"calc"},
        widgets=[calc],
    )
    assert out == [ok]
    assert calc.execute_calls == 1


@pytest.mark.asyncio
async def test_exception_returns_failure_output() -> None:
    bad = _StubWidget(
        "weather", "weather", raise_exc=RuntimeError("open-meteo down")
    )
    out = await execute_all(
        classification=_classification(weather=True),
        chat_history=[],
        follow_up="weather?",
        llm=None,
        enabled={"weather"},
        widgets=[bad],
    )
    assert len(out) == 1
    assert out[0].type == "weather"
    assert out[0].llm_context == "Failed to fetch weather data."
    assert "open-meteo down" in out[0].data["error"]


@pytest.mark.asyncio
async def test_one_failure_does_not_kill_others() -> None:
    ok_out = WidgetOutput(type="calc", llm_context="ok", data={})
    good = _StubWidget("calc", "calculation", output=ok_out)
    bad = _StubWidget("weather", "weather", raise_exc=RuntimeError("boom"))
    out = await execute_all(
        classification=_classification(weather=True, calc=True),
        chat_history=[],
        follow_up="weather and 1+1",
        llm=None,
        enabled={"weather", "calc"},
        widgets=[bad, good],
    )
    # Order matches selection order (bad first, good second)
    assert [w.type for w in out] == ["weather", "calc"]
    assert out[0].llm_context == "Failed to fetch weather data."
    assert out[1] is ok_out


@pytest.mark.asyncio
async def test_predicate_exception_does_not_propagate() -> None:
    bad = _StubWidget("weather", "weather", predicate_raises=True)
    ok_out = WidgetOutput(type="calc", llm_context="ok", data={})
    good = _StubWidget("calc", "calculation", output=ok_out)
    out = await execute_all(
        classification=_classification(weather=True, calc=True),
        chat_history=[],
        follow_up="",
        llm=None,
        enabled={"weather", "calc"},
        widgets=[bad, good],
    )
    assert out == [ok_out]
    assert bad.execute_calls == 0


@pytest.mark.asyncio
async def test_widget_returning_none_is_filtered() -> None:
    w = _StubWidget("weather", "weather", output=None)
    out = await execute_all(
        classification=_classification(weather=True),
        chat_history=[],
        follow_up="",
        llm=None,
        enabled={"weather"},
        widgets=[w],
    )
    assert out == []


@pytest.mark.asyncio
async def test_widget_returning_wrong_shape_wrapped_as_failure() -> None:
    class BadWidget:
        type = "weather"

        def should_execute(self, classification: Any) -> bool:
            return True

        async def execute(self, **kwargs: Any) -> Any:
            return {"not": "a WidgetOutput"}

    out = await execute_all(
        classification=_classification(weather=True),
        chat_history=[],
        follow_up="",
        llm=None,
        enabled={"weather"},
        widgets=[BadWidget()],
    )
    assert len(out) == 1
    assert out[0].type == "weather"
    assert out[0].llm_context == "Failed to fetch weather data."
    assert "invalid widget output shape" in out[0].data["error"]


def test_build_failure_output_shape() -> None:
    out = build_failure_output("stock", ValueError("rate limit"))
    assert out.type == "stock"
    assert out.llm_context == "Failed to fetch stock data."
    assert out.data == {"error": "rate limit"}
