# A0_Fauxplexica

![status](https://img.shields.io/badge/status-Phase%201%20Wave%202%20in%20progress-orange)
![license](https://img.shields.io/badge/license-MIT-blue)
![version](https://img.shields.io/badge/version-0.1.0-lightgrey)

A0_Fauxplexica is a **Perplexity / Vane-style AI answering engine** delivered as a native Agent Zero plugin. It maps Vane's answering pipeline onto A0's plugin, tool, WebUI, and superordinate orchestration model:

```text
classify -> parallel(research, widgets) -> compose -> cite -> stream blocks / answer
```

The plugin is designed for a dedicated `fauxplexica` chat/profile context and for one-shot use from other A0 contexts through tools such as `fauxplexica_search` and `fauxplexica_answer`.

> **Phase 1 status:** Wave 1b is integrated. Helper/tool/test surfaces for classification, SearxNG search, uploads, widgets, reranking, scraping/extraction, and composition scaffolding are present. Wave 2 is in progress for Reggie research loop, Compo composer/prompt completion, Orchy blockstream/orchestration, and continuous QA. Do not treat API/WebUI polish or full end-to-end behavior as complete until later waves land.

## BYO SearxNG requirement

A0_Fauxplexica does **not** bundle, start, or auto-provision SearxNG. You must provide a reachable SearxNG instance and configure `searxng_url`.

Notes for operators:

- Use the upstream SearxNG Docker image or your own hosted SearxNG deployment.
- Academic search depends on the engines enabled in your SearxNG configuration. Google Scholar is commonly disabled by default.
- The Phase 1 client is designed to pass `time_range`, `safesearch`, repeated `engines=`/`categories=` parameters, and optional pagination.

## Implemented components currently visible

Current repository surfaces include:

- `helpers/searxng_client.py` — async SearxNG client and result normalization.
- `helpers/query_builder.py` — query/category/freshness/domain rewrite support.
- `helpers/classifier.py` — unified routing + style classifier contract.
- `helpers/reranker.py` — embedding keep/dedup thresholds for speed/balanced research.
- `helpers/picker.py` — quality-mode LLM picker contract.
- `helpers/scraper.py` — Trafilatura-based scraper; Playwright fallback is Phase 2.
- `helpers/extractor.py` — chunked quality-mode fact extraction.
- `helpers/researcher.py` — ReAct research-loop surface owned by Reggie.
- `helpers/orchestrator.py` — mode-to-pipeline coordinator surface owned by Orchy.
- `helpers/composer.py` — answer composition surface owned by Compo.
- `helpers/citations.py` — source registry and citation validation surface.
- `helpers/blockstream.py` — typed block stream / JSON-Patch update abstraction.
- `helpers/uploads.py` — uploaded-file RAG adapter using A0 `_memory` infrastructure.
- `helpers/widgets_registry.py`, `helpers/widget_cache.py` — widget execution and caching support.
- `tools/widget_weather.py`, `tools/widget_calc.py`, `tools/widget_stock.py` — widget tools.
- `tools/fauxplexica_search.py`, `tools/fauxplexica_answer.py` — agent-facing search/answer tools.
- `tools/fauxplexica_upload.py`, `tools/fauxplexica_uploads_search.py` — uploaded-file ingestion/search tool wrappers.
- `api/search.py`, `api/providers.py`, `api/suggest.py` — API route surfaces; search/providers are Phase 1 targets, suggestions are Phase 2.
- `webui/main.html`, `webui/config.html`, `webui/fauxplexica-store.js`, `webui/citation-card.html` — WebUI panel surfaces.

## Supported file types

File Q&A is routed through the existing A0 `_memory` plugin rather than a new vector store. Current upload helpers are intended to support text-extractable content handled by the underlying A0 memory/upload stack, including common text and document formats such as plain text and PDF when the host stack can extract them.

Phase 1 does **not** introduce a separate multimodal image/PDF parser. Image and video search/rendering are deferred to Phase 2+.

## Widgets

Phase 1 widget targets:

| Widget | Implementation surface | Notes |
|---|---|---|
| Weather | `tools/widget_weather.py` | Nominatim geocoding plus Open-Meteo forecast; graceful failure output. |
| Calculator | `tools/widget_calc.py` | Sandboxed arithmetic via `asteval`; no raw `eval`. |
| Stock | `tools/widget_stock.py` | `yfinance`, 5-minute per-ticker cache, comparison cap of 2. |

Widgets are triggered from classifier routing flags and return `llmContext` that the composer may use. Widget output must not be cited as a web source.

## Search modes

| Mode | Intended behavior | Current status |
|---|---|---|
| `speed` | Low-latency search, small iteration count, no scraping. | Contracts/config present; Wave 2 integration in progress. |
| `balanced` | Multi-query / iterative research with rerank and synthesis. | Contracts/config present; Wave 2 integration in progress. |
| `quality` | Deeper ReAct loop, picker, scrape, extractor, richer source set. | Contracts/config present; Wave 2 integration in progress. |

Amendments R1 set quality iteration cap to `10` for Phase 1 cost control.

## Configuration overview

Primary settings live in `default_config.yaml` and can be overridden per project or per agent because `plugin.yaml` sets both `per_project_config: true` and `per_agent_config: true`.

Important keys:

- `searxng_url` — required BYO SearxNG base URL.
- `default_mode` — `speed`, `balanced`, or `quality`.
- `sources` — source picker defaults for `web`, `discussions`, and `academic`.
- `widgets_enabled` — weather/calculator/stock toggles.
- `max_sources_per_query` — final retained source cap.
- `citation_style` — currently `inline_bracket` target, with `footnote` reserved by config.
- `model_overrides` — optional classifier/composer/utility model-role overrides.
- `context_budget_chars` — composer context cap.
- `quality_max_iterations` — Reggie quality-mode loop cap.
- `scrape_extractor_concurrency` — per-page extractor semaphore.
- `rerank.*` — embedding keep/dedup thresholds.
- `searxng.*` — pagination and default time range.
- `webui.scraper_fallback_playwright` — Phase 2 fallback toggle; false by default.

See [`docs/CONFIG.md`](docs/CONFIG.md) for the full key-by-key reference.

## API and tools

Draft API contracts are documented in [`docs/API.md`](docs/API.md). The planned Phase 1 public routes are:

- `POST /api/fauxplexica/search`
- `GET /api/fauxplexica/providers`

`GET /api/fauxplexica/suggest` exists as a Phase 2 placeholder for smart suggestions/autocomplete.

Current helper/tool import surfaces are also summarized in `docs/API.md` for Wave 2 developers.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the Vane-inspired pipeline mapping across classify, widgets, research, compose, cite, blockstream, WebUI, and API tracks.

## Testing status

Integrated Wave 1b validation reported by the orchestrator:

- `python -m compileall -q helpers tools tests` — PASS
- Targeted Wave 1b pytest suite — `132 passed in 3.06s`

The repository currently includes unit tests for classifier, SearxNG client, uploads, widgets, scraper/extractor/reranker/picker/type surfaces, and related helper behavior. End-to-end API/WebUI validation remains dependent on later Wave 2/3/4 integration outputs.

## Phase 2+ deferred items

Deferred or not-yet-final Phase 1+ items include:

- Discover feed.
- Smart suggestions/autocomplete beyond placeholder surface.
- Image/video search rendering.
- Custom-agent builder.
- Authentication overlay.
- Tavily/Exa provider implementation beyond stubs/interfaces.
- Playwright scraper fallback for JS-heavy sites.
- Block-stream sidecar persistence for history-fidelity reloads.
- Mobile WebUI polish.
- Multi-tenant hardening.

## License

MIT — see [`LICENSE`](./LICENSE).
