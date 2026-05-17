---
name: fauxplexica-widgets
description: Invoke Fauxplexica's deterministic factual widgets — weather (Nominatim geocode + Open-Meteo forecast), stock (yfinance quote + chart), and calculator (asteval-based safe arithmetic) — directly, outside the auto-research pipeline. Use when the user explicitly asks for a weather widget, stock quote/chart, or calculator output, or wants widget-style UI cards rather than narrative research answers.
version: 0.2.0
tags:
  - widgets
  - weather
  - stock
  - calculator
  - factual-ui
  - fauxplexica
  - perplexica
triggers:
  - fauxplexica widget
  - weather widget
  - stock widget
  - calculator widget
  - stock quote
  - stock chart
  - compare stocks
  - what's the weather
  - forecast for
  - calculate this
  - evaluate expression
---

# Fauxplexica Widgets Skill

Direct access to the three deterministic factual widgets bundled with the `a0_fauxplexica` plugin. These widgets normally auto-attach inside the research pipeline when a query is classified as weather/stock/math, but they can also be called explicitly via their tools.

## When to use

Load this skill when the user wants **structured widget output** rather than a synthesized research answer:

- *"Weather widget for Tokyo"* / *"What's the weather in Berlin?"*
- *"Stock quote for NVDA"* / *"Compare AAPL and MSFT charts"*
- *"Calculate (1.05^30) * 1000"* / *"Evaluate this expression"*

If the user just wants a general answer that *happens* to involve weather/finance/math, prefer `fauxplexica-research` and let the pipeline auto-invoke widgets.

## The three widgets

### 1. `widget_weather`

Nominatim geocode + Open-Meteo forecast. Returns current conditions and short-term forecast.

```
widget_weather:
  location: "Berlin, DE"
```

- Deterministic public APIs (no API key required)
- Returns location-resolved structured data

### 2. `widget_stock`

`yfinance` quote + chart data with aggressive caching (default 300s TTL).

```
widget_stock:
  ticker: "NVDA"
```

For comparisons, pass multiple tickers up to the configured `stock_comparison_max` (default 2):

```
widget_stock:
  ticker: ["AAPL", "MSFT"]
```

- Cache TTL: `stock_cache_ttl_seconds` in plugin config
- Includes quote, change, and chart series

### 3. `widget_calc`

Safe arithmetic via `asteval` — no `eval()`, no Python builtins, no I/O.

```
widget_calc:
  expression: "(1.05 ** 30) * 1000"
```

- Deterministic, side-effect-free
- Supports standard math operators and common functions (`sqrt`, `log`, `sin`, etc.)

## Citation policy

Widget output is **factual UI data**, not a citeable web source. If a research answer relies on widget data, the composer cites a backing web/academic source when one is in scope; widget values themselves are presented as deterministic computed facts.

## Prerequisites

- `a0_fauxplexica` plugin installed and enabled
- Network access for weather (Nominatim, Open-Meteo) and stock (Yahoo Finance) widgets
- No external API keys required
- Widget toggles in `config.json`: `widgets_enabled.{weather,calculator,stock}` (all `true` by default)

## When NOT to use this skill

- For evidence-backed narrative answers → use `fauxplexica-research`
- For RAG over user-uploaded files → use `fauxplexica-uploads`
- For real-time intraday trading decisions → use the `trading_analysis` tool (multi-agent pipeline), not the stock widget alone

## See also

- `fauxplexica-research` — Perplexity/Vane-style synthesis with citations
- `fauxplexica-uploads` — RAG over chat-context uploaded files
