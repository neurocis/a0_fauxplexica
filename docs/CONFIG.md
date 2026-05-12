# A0_Fauxplexica Configuration

This document describes `default_config.yaml` for A0_Fauxplexica Phase 1. The plugin is configured per project and per agent (`plugin.yaml` sets both to true), so operators can tune different Fauxplexica contexts independently.

## Required external service

### `searxng_url`

```yaml
searxng_url: ""
```

Base URL for your BYO SearxNG instance. A0_Fauxplexica does not bundle SearxNG. Set this before expecting web/academic/discussion research to work.

If this is empty and sources are enabled, the search route returns `missing_searxng_url` and the WebUI surfaces an inline warning.

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

### `max_sources_per_query`

```yaml
max_sources_per_query: 12
```

Hard cap on retained sources after research, deduplication, and citation registry construction.

### `context_budget_chars`

```yaml
context_budget_chars: 60000
```

Composer context budget for the final answer.

### `quality_max_iterations`

```yaml
quality_max_iterations: 10
```

Maximum Reggie research-loop iterations in quality mode. Phase 1 intentionally throttles cost and latency.

## Citation behavior

### `citation_style`

```yaml
citation_style: inline_bracket
```

Phase 1 targets inline bracket citations such as `[1]`. The post-hoc validator supports the following policies (used by integrators):

- `keep` — leave the answer unchanged; still report valid/invalid/uncited indices.
- `strip_invalid` — remove out-of-range citation tokens only.
- `annotate_invalid` — replace invalid tokens with `[invalid:N]`.

## Widgets

### `widgets_enabled`

```yaml
widgets_enabled:
  weather: true
  calculator: true
  stock: true
```

Global defaults for built-in widgets. The classifier still decides whether a widget is relevant for a query.

### `stock_comparison_max`

```yaml
stock_comparison_max: 2
```

Maximum comparison tickers for the stock widget.

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

Optional model role override strings. Empty values fall back to A0 `_model_config` defaults.

Intended roles:

- `classifier` — fast structured classification.
- `composer` — stronger final answer writing.
- `utility` — lower-cost helper calls such as extraction or parameter parsing.

The `Fauxplexica Research` preset wires these to the project's chat/utility/embedding models.

## Reranking

### `rerank.cosine_keep_threshold`

```yaml
rerank:
  cosine_keep_threshold: 0.5
```

### `rerank.cosine_dedup_threshold`

```yaml
rerank:
  cosine_dedup_threshold: 0.75
```

Embedding failures should degrade gracefully by keeping results rather than failing the whole search.

## SearxNG client tuning

### `searxng.pagination_pages`

```yaml
searxng:
  pagination_pages: 1
```

### `searxng.time_range_default`

```yaml
searxng:
  time_range_default: any
```

The classifier's `style.freshness` may override the default for recent-news or freshness-sensitive queries.

## Scraping and extraction

### `scrape_extractor_concurrency`

```yaml
scrape_extractor_concurrency: 3
```

### `webui.scraper_fallback_playwright`

```yaml
webui:
  scraper_fallback_playwright: false
```

Phase 2 toggle for Playwright fallback on JS-heavy sites. Phase 1 uses Trafilatura.

## Configuration checklist

Minimum useful setup:

1. Set `searxng_url`.
2. Confirm desired `default_mode`.
3. Confirm source defaults under `sources`.
4. Disable any widgets that should not call external APIs.
5. Tune model overrides only if `_model_config` defaults are not appropriate.

## Embedding endpoint for reranker smoke tests

A0_Fauxplexica supports live reranker smoke tests against an OpenAI-compatible
embeddings API. This does **not** bundle or pin a local model; you provide the
endpoint, API key, and model name.

Runtime config documents the intended shape:

```yaml
embeddings:
  base_url: "https://api.openai.com/v1"
  api_key: "..."
  model: "text-embedding-3-small"
  timeout_seconds: 30
```

For integration tests, prefer environment variables so secrets are not committed:

```bash
SEARXNG_URL=http://198.18.88.12 \
EMBEDDING_BASE_URL=https://api.openai.com/v1 \
EMBEDDING_API_KEY=sk-... \
EMBEDDING_MODEL=text-embedding-3-small \
PYTHONPATH=/a0/plugins pytest -q tests/integration -m integration
```

`EMBEDDING_API_KEY` may be omitted for local OpenAI-compatible gateways that do
not require authentication. If the embedding variables are not set, the reranker
integration smoke uses a deterministic bag-of-words pseudo-embedder so the
rerank machinery still runs end-to-end without a model dependency.
