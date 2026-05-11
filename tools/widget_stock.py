"""Stock widget — yfinance quote + chart data with aggressive caching.

Mirrors Vane's ``stockWidget.ts`` (yahoo-finance2 in TS-land). Two-stage:

1. Inner param-extractor LLM call → extract ``{ticker, comparison_tickers}``;
   comparison is capped at 2 (Vane uses 3 but Yahoo rate-limits hurt).
2. yfinance quote + 7 chart ranges (1D, 5D, 1M, 3M, 6M, 1Y, MAX) × (1 + N_cmp).
   Per-ticker chart cache (5min TTL by default) keeps repeat queries cheap.

yfinance is sync — every blocking call goes through ``asyncio.to_thread``.

Graceful degradation on any yfinance / network error.

See PLAN_AMENDMENTS_R1.md §A8 and RECON_INITIAL.md §5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any, List, Optional

import yfinance as yf

from ..helpers.widget_cache import stock_chart_cache, stock_quote_cache
from ..helpers.widgets_registry import WidgetOutput, build_failure_output

if TYPE_CHECKING:
    from ..helpers.types import ClassifierOutput  # noqa: F401

__all__ = ["StockWidget"]

_log = logging.getLogger(__name__)

_COMPARISON_MAX = 2  # PLAN_AMENDMENTS_R1.md §A8 / §A11
_CHART_RANGES: list[tuple[str, str, str]] = [
    # (label, period, interval)
    ("1D", "1d", "5m"),
    ("5D", "5d", "30m"),
    ("1M", "1mo", "1d"),
    ("3M", "3mo", "1d"),
    ("6M", "6mo", "1d"),
    ("1Y", "1y", "1wk"),
    ("MAX", "max", "1mo"),
]

_EXTRACTOR_SYSTEM_PROMPT = f"""You extract stock tickers from a user query.

Rules:
- Output STRICT JSON only, no prose, no code fence: {{"ticker": "<TICKER>", "comparison_tickers": ["<T1>", "<T2>"]}}
- ``ticker`` is the primary stock symbol the user is asking about (e.g. "AAPL", "MSFT", "BRK-B").
- ``comparison_tickers`` is a list (0 to {_COMPARISON_MAX}) of additional symbols the user explicitly compares against.
- If the query mentions no ticker, output: {{"ticker": "NOT_PRESENT", "comparison_tickers": []}}
- Use the canonical Yahoo Finance symbol (e.g. "BRK-B" not "BRK.B", "BTC-USD" for crypto, etc.).
Never explain. Output JSON only."""


class StockWidget:
    """Stock widget — id ``'stock'``."""

    type: str = "stock"

    def should_execute(self, classification: "ClassifierOutput") -> bool:
        return _routing_widget_flag(classification, "stock")

    async def execute(
        self,
        *,
        chat_history: list,
        follow_up: str,
        classification: "ClassifierOutput",
        llm: Any,
    ) -> Optional[WidgetOutput]:
        # Stage 1: extract tickers.
        try:
            params = await _extract_tickers(follow_up, chat_history, llm)
        except Exception as exc:  # noqa: BLE001
            _log.exception("stock: extractor LLM call failed: %s", exc)
            return build_failure_output(self.type, f"extractor failed: {exc}")

        ticker = (params.get("ticker") or "").strip().upper()
        comparison: List[str] = [
            t.strip().upper()
            for t in (params.get("comparison_tickers") or [])
            if isinstance(t, str) and t.strip()
        ][:_COMPARISON_MAX]

        if not ticker or ticker == "NOT_PRESENT":
            return WidgetOutput(
                type=self.type,
                llm_context="No stock ticker detected.",
                data={"error": "no_ticker"},
            )

        # Stage 2: quote + chart data. Run concurrently per symbol.
        try:
            quote_task = asyncio.create_task(_fetch_quote(ticker))
            chart_task = asyncio.create_task(_fetch_all_charts(ticker))
            comp_tasks = [
                asyncio.create_task(_fetch_all_charts(t)) for t in comparison
            ]

            quote = await quote_task
            chart_data = await chart_task
            comp_results = await asyncio.gather(*comp_tasks, return_exceptions=True)
        except Exception as exc:  # noqa: BLE001
            _log.exception("stock: fetch error: %s", exc)
            return build_failure_output(self.type, str(exc))

        if quote is None:
            return WidgetOutput(
                type=self.type,
                llm_context=f"Could not fetch quote for {ticker}.",
                data={"error": "quote_empty", "symbol": ticker},
            )

        comparison_data: dict[str, Any] = {}
        for sym, res in zip(comparison, comp_results):
            if isinstance(res, BaseException):
                _log.warning("stock: comparison %s failed: %s", sym, res)
                comparison_data[sym] = {"error": str(res)}
            else:
                comparison_data[sym] = res

        company = (
            quote.get("longName")
            or quote.get("shortName")
            or quote.get("displayName")
            or ticker
        )
        price = quote.get("regularMarketPrice")
        prev_close = quote.get("regularMarketPreviousClose")
        if price is not None and prev_close:
            try:
                pct_change = ((float(price) - float(prev_close)) / float(prev_close)) * 100.0
                pct_str = f"{pct_change:+.2f}"
            except (TypeError, ValueError, ZeroDivisionError):
                pct_str = "n/a"
        else:
            pct_str = "n/a"

        price_str = f"${price}" if price is not None else "price unavailable"
        llm_context = f"{ticker} ({company}) trading at {price_str} ({pct_str}%)."

        data: dict[str, Any] = {
            "symbol": ticker,
            "quote": quote,
            "chart_data": chart_data,
        }
        if comparison_data:
            data["comparison_data"] = comparison_data

        return WidgetOutput(type=self.type, llm_context=llm_context, data=data)


# ---------------------------------------------------------------------------
# yfinance helpers (sync, wrapped in to_thread)
# ---------------------------------------------------------------------------


async def _fetch_quote(ticker: str) -> Optional[dict]:
    """Return a quote dict from yfinance, with caching."""
    cache_key = ("quote", ticker)
    cached = stock_quote_cache.get(cache_key)
    if cached is not None:
        return cached
    info = await asyncio.to_thread(_sync_fetch_info, ticker)
    if info:
        stock_quote_cache.set(cache_key, info)
    return info


def _sync_fetch_info(ticker: str) -> Optional[dict]:
    """Blocking yfinance call. Run in a thread."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        # ``fast_info`` carries the realtime price even when ``info`` is stale.
        try:
            fast = dict(t.fast_info) if t.fast_info else {}
        except Exception:  # noqa: BLE001
            fast = {}
        if fast:
            merged = dict(info)
            # fast_info uses different keys — map common ones.
            if "lastPrice" in fast and "regularMarketPrice" not in merged:
                merged["regularMarketPrice"] = fast.get("lastPrice")
            if "previousClose" in fast and "regularMarketPreviousClose" not in merged:
                merged["regularMarketPreviousClose"] = fast.get("previousClose")
            if "dayHigh" in fast and "regularMarketDayHigh" not in merged:
                merged["regularMarketDayHigh"] = fast.get("dayHigh")
            if "dayLow" in fast and "regularMarketDayLow" not in merged:
                merged["regularMarketDayLow"] = fast.get("dayLow")
            return merged
        return info or None
    except Exception as exc:  # noqa: BLE001
        _log.warning("stock: yfinance info(%s) failed: %s", ticker, exc)
        return None


async def _fetch_all_charts(ticker: str) -> dict:
    """Fetch every range for ``ticker`` concurrently, with per-range caching."""
    coros = [_fetch_chart(ticker, label, period, interval) for label, period, interval in _CHART_RANGES]
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: dict[str, Any] = {}
    for (label, _, _), res in zip(_CHART_RANGES, results):
        if isinstance(res, BaseException):
            _log.warning("stock: chart %s/%s failed: %s", ticker, label, res)
            out[label] = {"error": str(res)}
        else:
            out[label] = res
    return out


async def _fetch_chart(ticker: str, label: str, period: str, interval: str) -> dict:
    """Fetch a single chart range with caching."""
    cache_key = ("chart", ticker, label)
    cached = stock_chart_cache.get(cache_key)
    if cached is not None:
        return cached
    series = await asyncio.to_thread(_sync_fetch_history, ticker, period, interval)
    stock_chart_cache.set(cache_key, series)
    return series


def _sync_fetch_history(ticker: str, period: str, interval: str) -> dict:
    """Blocking yfinance history call. Run in a thread."""
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return {"period": period, "interval": interval, "points": []}
    points = []
    for ts, row in df.iterrows():
        try:
            iso_ts = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        except Exception:  # noqa: BLE001
            iso_ts = str(ts)
        points.append(
            {
                "t": iso_ts,
                "o": _maybe_float(row.get("Open")),
                "h": _maybe_float(row.get("High")),
                "l": _maybe_float(row.get("Low")),
                "c": _maybe_float(row.get("Close")),
                "v": _maybe_float(row.get("Volume")),
            }
        )
    return {"period": period, "interval": interval, "points": points}


def _maybe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Filter NaN.
    if f != f:
        return None
    return f


# ---------------------------------------------------------------------------
# Shared helpers (mirrored across widgets — kept local for stay-in-lane)
# ---------------------------------------------------------------------------


def _routing_widget_flag(classification: Any, key: str) -> bool:
    if classification is None:
        return False
    routing = getattr(classification, "routing", None)
    if routing is None and isinstance(classification, dict):
        routing = classification.get("routing")
    if routing is None:
        return False
    widgets = getattr(routing, "widgets", None)
    if widgets is None and isinstance(routing, dict):
        widgets = routing.get("widgets")
    if widgets is None:
        return False
    if isinstance(widgets, dict):
        return bool(widgets.get(key, False))
    return bool(getattr(widgets, key, False))


async def _extract_tickers(query: str, chat_history: list, llm: Any) -> dict:
    history_snippet = _format_history(chat_history)
    user_msg = (
        f"{history_snippet}\nLatest user query: {query}\n\n"
        f"Extract ticker info. Output JSON only (max {_COMPARISON_MAX} comparison tickers)."
    )
    raw = await _invoke_llm(llm, system=_EXTRACTOR_SYSTEM_PROMPT, user=user_msg)
    return _parse_ticker_json(raw)


def _parse_ticker_json(text: str) -> dict:
    """Lenient JSON parse — strips code fences, falls back to regex."""
    if not text:
        return {"ticker": "NOT_PRESENT", "comparison_tickers": []}
    t = _strip_code_fence(text)
    # First try strict.
    try:
        parsed = json.loads(t)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # Try to find the first JSON object in the string.
    m = re.search(r"\{.*?\}", t, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    # Last resort: treat whole stripped string as the ticker.
    return {"ticker": t.strip().upper(), "comparison_tickers": []}


def _format_history(chat_history: list, max_turns: int = 4) -> str:
    if not chat_history:
        return ""
    tail = chat_history[-max_turns:]
    lines = []
    for msg in tail:
        role = _get_attr(msg, "role", "user")
        content = _get_attr(msg, "content", "")
        if not content:
            continue
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "Recent context:\n" + "\n".join(lines)


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _invoke_llm(llm: Any, *, system: str, user: str) -> str:
    if hasattr(llm, "call_utility_model"):
        return await llm.call_utility_model(system=system, message=user)
    if callable(llm):
        try:
            return await llm(system=system, user=user)
        except TypeError:
            return await llm(f"{system}\n\n{user}")
    raise RuntimeError(f"unsupported llm handle: {type(llm).__name__}")


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\n?|\n?```$")


def _strip_code_fence(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    t = _FENCE_RE.sub("", t).strip()
    return t
