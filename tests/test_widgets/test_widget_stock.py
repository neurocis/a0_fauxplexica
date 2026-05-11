"""Tests for ``tools/widget_stock.py`` (no live network — yfinance mocked)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import pytest

from a0_fauxplexica.helpers.widget_cache import stock_chart_cache, stock_quote_cache
from a0_fauxplexica.tools.widget_stock import StockWidget, _parse_ticker_json


def _classification(stock: bool = True) -> SimpleNamespace:
    return SimpleNamespace(routing=SimpleNamespace(widgets={"stock": stock}))


def _stub_llm(response: str) -> Callable[..., Any]:
    async def _llm(*, system: str, user: str) -> str:  # noqa: ARG001
        return response
    return _llm


@pytest.fixture(autouse=True)
def clear_stock_caches() -> None:
    stock_chart_cache.clear()
    stock_quote_cache.clear()


def test_should_execute_routing_flag() -> None:
    w = StockWidget()
    assert w.should_execute(_classification(stock=True)) is True
    assert w.should_execute(_classification(stock=False)) is False


def test_parse_ticker_json_strict_and_lenient() -> None:
    assert _parse_ticker_json('{"ticker":"AAPL","comparison_tickers":["MSFT","GOOG","TSLA"]}')["ticker"] == "AAPL"
    assert _parse_ticker_json('```json\n{"ticker":"MSFT","comparison_tickers":[]}\n```')["ticker"] == "MSFT"
    assert _parse_ticker_json("NVDA") == {"ticker": "NVDA", "comparison_tickers": []}
    assert _parse_ticker_json("") == {"ticker": "NOT_PRESENT", "comparison_tickers": []}


@pytest.mark.asyncio
async def test_no_ticker_output() -> None:
    out = await StockWidget().execute(
        chat_history=[],
        follow_up="how is the market?",
        classification=_classification(),
        llm=_stub_llm('{"ticker":"NOT_PRESENT","comparison_tickers":[]}'),
    )
    assert out is not None
    assert out.type == "stock"
    assert out.data["error"] == "no_ticker"
    assert out.llm_context == "No stock ticker detected."


@pytest.mark.asyncio
async def test_happy_path_with_comparison_cap() -> None:
    quote = {
        "longName": "Apple Inc.",
        "regularMarketPrice": 110.0,
        "regularMarketPreviousClose": 100.0,
    }
    chart = {"period": "1d", "interval": "5m", "points": [{"t": "2026-01-01", "c": 110.0}]}

    async def fake_fetch_quote(ticker: str) -> dict:
        assert ticker == "AAPL"
        return quote

    async def fake_fetch_all_charts(ticker: str) -> dict:
        return {"1D": {**chart, "ticker": ticker}}

    with patch("a0_fauxplexica.tools.widget_stock._fetch_quote", fake_fetch_quote), patch(
        "a0_fauxplexica.tools.widget_stock._fetch_all_charts", fake_fetch_all_charts
    ):
        out = await StockWidget().execute(
            chat_history=[],
            follow_up="compare AAPL to MSFT GOOG TSLA",
            classification=_classification(),
            llm=_stub_llm('{"ticker":"AAPL","comparison_tickers":["MSFT","GOOG","TSLA"]}'),
        )

    assert out is not None
    assert out.type == "stock"
    assert out.data["symbol"] == "AAPL"
    assert out.data["quote"] == quote
    assert out.data["chart_data"]["1D"]["ticker"] == "AAPL"
    # Comparison cap = 2.
    assert set(out.data["comparison_data"].keys()) == {"MSFT", "GOOG"}
    assert out.llm_context == "AAPL (Apple Inc.) trading at $110.0 (+10.00%)."


@pytest.mark.asyncio
async def test_extractor_failure_graceful() -> None:
    async def boom(**kwargs: Any) -> str:
        raise RuntimeError("llm down")

    out = await StockWidget().execute(
        chat_history=[],
        follow_up="AAPL",
        classification=_classification(),
        llm=boom,
    )
    assert out is not None
    assert out.llm_context == "Failed to fetch stock data."
    assert "llm down" in out.data["error"]


@pytest.mark.asyncio
async def test_quote_empty_graceful() -> None:
    async def fake_fetch_quote(ticker: str) -> None:  # noqa: ARG001
        return None

    async def fake_fetch_all_charts(ticker: str) -> dict:  # noqa: ARG001
        return {}

    with patch("a0_fauxplexica.tools.widget_stock._fetch_quote", fake_fetch_quote), patch(
        "a0_fauxplexica.tools.widget_stock._fetch_all_charts", fake_fetch_all_charts
    ):
        out = await StockWidget().execute(
            chat_history=[],
            follow_up="AAPL",
            classification=_classification(),
            llm=_stub_llm('{"ticker":"AAPL","comparison_tickers":[]}'),
        )
    assert out is not None
    assert out.data["error"] == "quote_empty"
    assert out.data["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_fetch_exception_graceful() -> None:
    async def fake_fetch_quote(ticker: str) -> dict:  # noqa: ARG001
        raise RuntimeError("yahoo rate limit")

    with patch("a0_fauxplexica.tools.widget_stock._fetch_quote", fake_fetch_quote):
        out = await StockWidget().execute(
            chat_history=[],
            follow_up="AAPL",
            classification=_classification(),
            llm=_stub_llm('{"ticker":"AAPL","comparison_tickers":[]}'),
        )
    assert out is not None
    assert out.llm_context == "Failed to fetch stock data."
    assert "yahoo rate limit" in out.data["error"]


@pytest.mark.asyncio
async def test_fetch_quote_uses_cache() -> None:
    from a0_fauxplexica.tools.widget_stock import _fetch_quote

    stock_quote_cache.set(("quote", "AAPL"), {"regularMarketPrice": 123})
    with patch("a0_fauxplexica.tools.widget_stock._sync_fetch_info") as sync_fetch:
        out = await _fetch_quote("AAPL")
    assert out == {"regularMarketPrice": 123}
    sync_fetch.assert_not_called()
