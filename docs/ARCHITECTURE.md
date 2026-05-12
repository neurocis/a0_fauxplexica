# A0_Fauxplexica Architecture

A0_Fauxplexica adapts Vane's Perplexity-style answering engine to Agent Zero. Instead of recreating Vane's full Next.js/Drizzle stack, it uses A0-native plugins, tools, chat persistence, model configuration, WebUI panels, and superordinate orchestration.

## Canonical pipeline

```text
user query
  -> classify
  -> parallel widgets + research
  -> compose answer
  -> validate citations
  -> stream typed blocks / final answer
```

## Vane-to-A0 mapping

| Vane concept | A0_Fauxplexica mapping |
|---|---|
| Next.js chat UI | A0 chat UI plus `webui/main.html` panel and the `A0_Fauxplexica` chat profile. |
| `/api/chat` | A0 native message pipeline; no duplicate chat endpoint. |
| `/api/search` | `POST /api/plugins/a0_fauxplexica/search`. |
| Providers route | `GET /api/plugins/a0_fauxplexica/providers` shim over `_model_config`. |
| SearxNG backend | `helpers/searxng_client.py`; BYO SearxNG required. |
| SearchAgent coordinator | `helpers/orchestrator.py`. |
| Researcher ReAct loop | `helpers/researcher.py`. |
| Writer/composer prompt | `helpers/composer.py` + `prompts/composer_*.md`. |
| Citation chips/source registry | `helpers/citations.py` + WebUI citation cards. |
| Streaming message blocks | `helpers/blockstream.py` + WebUI store NDJSON parser. |
| Upload vector store | A0 `_memory` reuse via `helpers/uploads.py`. |
| Chat history DB | A0 native chat persistence; no new schema in Phase 1. |

## Stage 1: classify

Owned by `helpers/classifier.py`. Produces two orthogonal outputs:

1. **Routing** — which tools should run (skip search, personal search, academic search, discussion search, widget toggles).
2. **Style** — how the answer should be written (`general`, `academic_research`, `recent_news`, `weather`, `people`, `coding`, `recipe`, `translation`, `creative_writing`, `science_math`, `url_lookup`).

URL detection is regex-prefilled before LLM refinement so URL lookup does not depend entirely on inference.

## Stage 2: widgets

Owned by `helpers/widgets_registry.py` and `tools/widget_*.py`. Widgets follow `should_execute(classification) -> execute(...) -> WidgetOutput`. Current widgets: weather (Nominatim + Open-Meteo), calculator (`asteval`), stock (`yfinance`). Widget failures degrade into structured failure outputs and do not abort the search. Widget `llmContext` is injected into the composer but is explicitly not citeable.

## Stage 3: research

Owned by `helpers/researcher.py`. Iterative ReAct-style loop. Amendments R1:

- speed mode: shallow loop, no scraping.
- balanced mode: up to 6 iterations.
- quality mode: up to `quality_max_iterations` (default 10), with picker/scrape/extract.

Supporting modules: `searxng_client`, `reranker`, `picker`, `scraper`, `extractor`, `uploads`.

Research produces findings and ordered source candidates for citation.

## Stage 4: compose

Owned by `helpers/composer.py` and `prompts/composer_*.md`. The composer receives:

- normalized query / standalone follow-up
- style primary type
- selected prompt template
- source context block (with stable `<result index=N>` markers)
- widget context block (marked as non-citeable)
- mode/depth hints

Prompt families: general, academic, news, coding, people, URL lookup, weather, recipe, translation, creative, science/math.

Perplexity-style output goals: concise answer first, comparison tables when appropriate, inline `[n]` citations for factual claims, no separate references section, mode-aware behavior for translation/creative/simple math.

## Stage 5: cite

Owned by `helpers/citations.py`. Phase 1 improves on Vane:

1. Build an ordered URL-deduplicated source registry.
2. Concatenate repeated URL content rather than creating duplicate citations.
3. Render source context with stable `<result index=N>` markers.
4. Let the composer emit `[N]` citations.
5. Post-hoc scan emitted citations and apply `keep` / `strip_invalid` / `annotate_invalid` policy.

Widget results are not source citations.

## Stage 6: blockstream

Owned by `helpers/blockstream.py`. Typed progressive blocks rather than a single markdown blob. Block types include `reasoning`, `searching`, `search_results`, `reading`, `source`, `widget`, `text`. Updates use JSON-Patch-style operations so the WebUI can update an in-flight block rather than repaint everything.

Phase 1 accepts that reload/history may show markdown rather than full block replay. Sidecar block persistence is deferred to Phase 2.

## WebUI track

Files:

- `webui/main.html`
- `webui/config.html`
- `webui/fauxplexica-store.js`
- `webui/citation-card.html`
- `webui/thumbnail.jpg`

The Phase 1 WebUI implements the search form, mode/source/widget controls, NDJSON-over-SSE blockstream renderer, clickable inline `[n]` citations linked to the rich sidebar cards, uploads UI, missing-SearxNG warning, and a diagnostic providers panel.

## API track

Phase 1 routes (see `docs/API.md`):

- `POST /api/plugins/a0_fauxplexica/search`
- `GET /api/plugins/a0_fauxplexica/providers`
- `GET /api/plugins/a0_fauxplexica/suggest` (Phase 2 placeholder)

The search route is a thin wrapper around `helpers.orchestrator.run_fauxplexica_search` and returns either NDJSON over `text/event-stream` or a JSON answer object.

## Chat profile track

The `A0_Fauxplexica` profile makes the plugin usable as a dedicated chat context. Files:

- `prompts/system_fauxplexica.md` — Fauxplexica system prompt for the plugin.
- `/a0/usr/projects/a0-fauxplexica/.a0proj/instructions/fauxplexica.md`
- `/a0/usr/projects/a0-fauxplexica/.a0proj/agents.json`
- `/a0/usr/projects/a0-fauxplexica/.a0proj/plugins/_model_config/presets.yaml`
- `/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/agent.yaml`
- `/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/prompts/agent.system.main.specifics.md`
- `/a0/usr/plugins/a0_fauxplexica/agents/fauxplexica/plugins/_model_config/config.json`

## Storage and history

Phase 1 avoids a new database schema:

- A0 native chat persistence stores chat/messages.
- `_memory` stores upload embeddings.
- `helpers/history.py` can layer per-search metadata where needed.
- Block sidecar persistence is deferred to Phase 2.

## Current status boundaries

Waves 1b, 2, 3, and 4 are integrated and validated. Recon may still produce a `recon_diff` capturing upstream Vane changes worth folding in before Phase 1 sign-off; small follow-ups land via short surgical commits.
