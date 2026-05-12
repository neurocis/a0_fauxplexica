# A0_Fauxplexica

![status](https://img.shields.io/badge/status-Phase%201%20integrated-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)
![version](https://img.shields.io/badge/version-0.1.0-lightgrey)

A0_Fauxplexica is a **Perplexity / Vane-style AI answering engine** delivered as a native Agent Zero plugin and a dedicated `A0_Fauxplexica` chat profile. It maps Vane's answering pipeline onto A0's plugin, tool, WebUI, and superordinate orchestration model:

```text
classify -> parallel(research, widgets) -> compose -> validate citations -> stream typed blocks / final answer
```

The plugin runs cleanly in a dedicated `fauxplexica` chat profile context and can also be invoked from other A0 contexts through tools such as `fauxplexica_search`, `fauxplexica_answer`, and `fauxplexica_upload`.

> **Phase 1 status:** Waves 1b, 2, 3, and 4 are integrated and validated on `main`. Python suite passes (178 tests). WebUI store tests pass. A dedicated `A0_Fauxplexica` chat profile is provided.

## BYO SearxNG

A0_Fauxplexica does not bundle SearxNG. You must provide a reachable SearxNG instance and set `searxng_url` in plugin settings.

- Academic search depends on engines enabled in your SearxNG configuration.
- The client passes `time_range`, `safesearch`, repeated `engines=`/`categories=`, and optional pagination.

If `searxng_url` is empty when web/academic/discussion sources are enabled, the API responds with a structured `missing_searxng_url` error and the WebUI shows a configuration warning.

## Implemented surfaces

- `helpers/searxng_client.py` — async SearxNG client and result normalization.
- `helpers/query_builder.py` — query/category/freshness/domain rewrite support.
- `helpers/classifier.py` — unified routing + style classifier.
- `helpers/reranker.py` — embedding keep/dedup thresholds for speed/balanced research.
- `helpers/picker.py` — quality-mode LLM picker.
- `helpers/scraper.py` — Trafilatura-based scraper (Playwright fallback is Phase 2).
- `helpers/extractor.py` — chunked quality-mode fact extraction with concurrency cap.
- `helpers/researcher.py` — ReAct research loop.
- `helpers/orchestrator.py` — mode-to-pipeline coordinator that invokes researcher, widgets, and composer.
- `helpers/composer.py` — answer composition.
- `helpers/citations.py` — source registry and post-hoc citation validation.
- `helpers/blockstream.py` — typed block stream / JSON-Patch updates.
- `helpers/uploads.py` — uploaded-file RAG adapter over A0 `_memory`.
- `helpers/widgets_registry.py`, `helpers/widget_cache.py` — widget execution and caching.
- `tools/widget_weather.py`, `tools/widget_calc.py`, `tools/widget_stock.py` — widget tools.
- `tools/fauxplexica_search.py`, `tools/fauxplexica_answer.py` — agent-facing search/answer tools.
- `tools/fauxplexica_upload.py`, `tools/fauxplexica_uploads_search.py` — uploaded-file tools.
- `api/search.py`, `api/providers.py`, `api/suggest.py` — Phase 1 search/providers routes; `suggest` is a Phase 2 placeholder.
- `webui/main.html`, `webui/config.html`, `webui/fauxplexica-store.js`, `webui/citation-card.html` — WebUI panel and store.
- `prompts/system_fauxplexica.md` — Fauxplexica system prompt for chat profile.

## Chat profile

The `A0_Fauxplexica` profile is defined for both project use (`/a0/usr/projects/a0-fauxplexica/.a0proj/`) and plugin-distributed use (`/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/`):

- key: `fauxplexica`
- display name: `A0_Fauxplexica`
- profile: `developer`
- defaults: mode `balanced`, citation style `inline_bracket`, rich sidebar citations, SearxNG BYO only
- connection policy: single connection definition per chat context
- model preset: `Fauxplexica Research` (strong chat model + utility classifier + local embeddings)

See `/a0/usr/projects/a0-fauxplexica/PROFY_STATUS.md` for the full profile contract.

## Search modes

| Mode | Behavior | Iteration cap |
|---|---|---|
| `speed` | shallow research, no scraping | small |
| `balanced` | parallel research with rerank/synthesis | moderate |
| `quality` | ReAct loop with picker/scrape/extract | `quality_max_iterations` (default 10) |

Amendments R1 throttles Vane's larger quality iteration cap for Phase 1 cost control.

## Widgets

| Widget | Implementation | Notes |
|---|---|---|
| Weather | `tools/widget_weather.py` | Nominatim + Open-Meteo, graceful failure output. |
| Calculator | `tools/widget_calc.py` | `asteval` sandbox; no raw `eval`. |
| Stock | `tools/widget_stock.py` | `yfinance`, 5-minute per-ticker cache, comparison cap of 2. |

Widget outputs are factual UI data but are not citeable web sources.

## Uploads / file Q&A

File Q&A reuses A0's `_memory` infrastructure via `helpers/uploads.py`. Supported Phase 1 types: PDF, TXT, MD, CSV, DOCX. Uploads are scoped per chat context. Images and multimodal parsing are deferred to Phase 2.

## Public API

Full contract in [`docs/API.md`](docs/API.md).

- `POST /api/plugins/a0_fauxplexica/search` — programmatic search; supports streaming NDJSON-over-SSE and a non-streaming JSON answer.
- `GET /api/plugins/a0_fauxplexica/providers` — read-only providers/sources/widgets/modes/limits/model registry listing.
- `GET /api/plugins/a0_fauxplexica/suggest` — placeholder reserved for Phase 2 suggestions.

## Citation contract

- Inline bracket citations such as `[1]` or `[1][3]`.
- Source registry normalizes results into 1-based indices with title/url/snippet/source/score.
- Post-hoc validation provides policies `keep`, `strip_invalid`, and `annotate_invalid`.
- Out-of-range citations are detected and may be stripped or annotated.
- Uncited sources are reported and surfaced in the sidebar.

## WebUI

The Phase 1 WebUI provides:

- search input bound to the search route (streaming and non-streaming)
- mode selector (Speed/Balanced/Quality) populated from `providers`
- source toggles (web/academic/discussions) and widget toggles (weather/calculator/stock) populated from `providers`
- NDJSON-over-SSE blockstream renderer for `init`, `block`, `updateBlock`, `researchComplete`, `response`, `messageEnd`, `done`, `error`
- clickable inline `[n]` citations linked to the rich sidebar cards
- uploads UI bound to the upload/uploads-search tools
- inline `missing_searxng_url` configuration warning
- diagnostic `config.html` page showing the providers JSON

## Configuration

See [`docs/CONFIG.md`](docs/CONFIG.md). Important keys:

- `searxng_url`
- `default_mode`
- `sources`
- `widgets_enabled`
- `max_sources_per_query`
- `citation_style`
- `model_overrides`
- `context_budget_chars`
- `quality_max_iterations`
- `scrape_extractor_concurrency`
- `stock_comparison_max`
- `stock_cache_ttl_seconds`
- `rerank.*`
- `searxng.*`
- `webui.scraper_fallback_playwright`

## Testing

- `PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests api` → clean
- `PYTHONPATH=/a0/plugins pytest -q tests` → **178 passed**
- `node tests/webui/test_fauxplexica_store.mjs` → `WEBUI_STORE_TESTS_OK`

## Phase 2+ deferred items

- Discover feed.
- Smart suggestions / autocomplete beyond placeholder route.
- Image/video search rendering.
- Custom-agent builder.
- Authentication overlay.
- Tavily/Exa providers beyond stubs/interfaces.
- Playwright scraper fallback for JS-heavy sites.
- Block-stream sidecar persistence for history-fidelity reloads.
- Mobile WebUI polish.
- Multi-tenant hardening.

## License

MIT — see [`LICENSE`](./LICENSE).
