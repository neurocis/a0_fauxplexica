# A0_Fauxplexica Configuration

This document describes `default_config.yaml` for A0_Fauxplexica Phase 1. The plugin is configured per project and per agent (`plugin.yaml` sets both to true), so operators can tune different Fauxplexica contexts independently.

## Required external service

### `searxng_url`

```yaml
searxng_url: ""
```

Base URL for your BYO SearxNG instance. A0_Fauxplexica does not bundle SearxNG. Set this before expecting web/academic/discussion research to work.

Operational notes:

- Academic engines may require enabling in SearxNG's `engines.yml`.
- Google Scholar is often disabled by default.
- Use a deployment you control or trust, because queries are sent to this service.

## Search behavior

### `default_mode`

```yaml
default_mode: balanced
```

Default mode when the user/API does not specify one.

Allowed values:

- `speed` — lower latency, shallow research, no scraping.
- `balanced` — default synthesis mode with more research breadth.
- `quality` — deeper ReAct loop with picker/scrape/extract path.

### `sources`

```yaml
sources:
  web: true
  discussions: false
  academic: true
```

Default source categories surfaced to the classifier/search stack and WebUI picker.

- `web` — general web results.
- `discussions` — forum/social/discussion sources where supported by SearxNG.
- `academic` — scholarly sources/engines where enabled in SearxNG.

### `max_sources_per_query`

```yaml
max_sources_per_query: 12
```

Hard cap on retained sources after research, deduplication, and citation registry construction. This is separate from intermediate search result counts.

### `context_budget_chars`

```yaml
context_budget_chars: 60000
```

Composer context budget. Added by Amendments R1 to keep final context usable with smaller local models.

### `quality_max_iterations`

```yaml
quality_max_iterations: 10
```

Maximum Reggie research-loop iterations in quality mode. Vane uses a larger cap; Phase 1 intentionally throttles cost and latency.

## Citation behavior

### `citation_style`

```yaml
citation_style: inline_bracket
```

Configured citation style. Phase 1 targets Perplexity/Vane-style inline brackets such as `[1]`.

Allowed/planned values:

- `inline_bracket` — active target.
- `footnote` — reserved by config; do not assume full support until citation/API owners finalize it.

## Widgets

### `widgets_enabled`

```yaml
widgets_enabled:
  weather: true
  calculator: true
  stock: true
```

Global defaults for built-in widgets. The classifier still decides whether a widget is relevant for a query; these flags allow operators to disable a widget entirely.

Widget notes:

- Weather uses Nominatim and Open-Meteo.
- Calculator uses `asteval` rather than Python `eval`.
- Stock uses `yfinance` and caching to reduce Yahoo rate-limit pain.

### `stock_comparison_max`

```yaml
stock_comparison_max: 2
```

Maximum comparison tickers for the stock widget. Amendments R1 lowers this versus Vane because Yahoo requests can multiply quickly.

### `stock_cache_ttl_seconds`

```yaml
stock_cache_ttl_seconds: 300
```

Per-ticker stock chart cache TTL. Default is five minutes.

## Model role overrides

### `model_overrides`

```yaml
model_overrides:
  classifier: ""
  composer: ""
  utility: ""
```

Optional model role override strings. Empty values mean the plugin should fall back to A0 `_model_config` defaults.

Intended roles:

- `classifier` — fast structured classification.
- `composer` — stronger final answer writing.
- `utility` — lower-cost helper calls such as extraction or parameter parsing.

Exact preset wiring is owned by later integration with `_model_config`.

## Reranking

### `rerank.cosine_keep_threshold`

```yaml
rerank:
  cosine_keep_threshold: 0.5
```

Minimum query/result cosine similarity for keeping speed/balanced results when embeddings are available.

### `rerank.cosine_dedup_threshold`

```yaml
rerank:
  cosine_dedup_threshold: 0.75
```

Similarity threshold above which results are treated as duplicates in embedding-based deduplication.

Embedding failures should degrade gracefully by keeping results rather than failing the whole search.

## SearxNG client tuning

### `searxng.pagination_pages`

```yaml
searxng:
  pagination_pages: 1
```

Number of SearxNG pages to request when pagination is enabled. Phase 1 defaults to page 1 only.

### `searxng.time_range_default`

```yaml
searxng:
  time_range_default: any
```

Default SearxNG freshness/time range. The classifier's `style.freshness` may override this for recent-news or freshness-sensitive queries.

Planned values align with SearxNG support and classifier hints such as `any`, `week`, and `day`.

## Scraping and extraction

### `scrape_extractor_concurrency`

```yaml
scrape_extractor_concurrency: 3
```

Per-page concurrency cap for quality-mode chunk extraction. This improves on Vane's unbounded parallel extractor calls.

### `webui.scraper_fallback_playwright`

```yaml
webui:
  scraper_fallback_playwright: false
```

Phase 2 toggle for Playwright fallback on JS-heavy sites. Phase 1 intentionally uses Trafilatura to avoid a Chromium dependency. Do not assume this flag performs a full Playwright scrape until the Phase 2 fallback lands.

## Configuration checklist

Minimum useful setup:

1. Set `searxng_url`.
2. Confirm desired `default_mode`.
3. Confirm source defaults under `sources`.
4. Disable any widgets that should not call external APIs.
5. Tune model overrides only if `_model_config` defaults are not appropriate.
