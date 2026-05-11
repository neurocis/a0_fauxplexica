# A0_Fauxplexica Architecture

A0_Fauxplexica adapts Vane's Perplexity-style answering engine to Agent Zero. Instead of recreating Vane's full Next.js/Drizzle stack, it uses A0-native plugins, tools, chat persistence, model configuration, WebUI panels, and superordinate orchestration.

## Canonical pipeline

```text
user query
  -> classify
  -> parallel widgets + research
  -> compose answer
  -> validate/render citations
  -> stream typed blocks / final answer
```

## Vane-to-A0 mapping

| Vane concept | A0_Fauxplexica mapping |
|---|---|
| Next.js chat UI | A0 chat UI plus `webui/main.html` panel. |
| `/api/chat` | A0 native message pipeline; no duplicate chat endpoint planned. |
| `/api/search` | `api/search.py` as `POST /api/fauxplexica/search`. |
| Providers route | `api/providers.py` shim over `_model_config`. |
| SearxNG backend | `helpers/searxng_client.py`; BYO SearxNG required. |
| SearchAgent coordinator | `helpers/orchestrator.py` owned by Orchy. |
| Researcher ReAct loop | `helpers/researcher.py` owned by Reggie. |
| Writer/composer prompt | `helpers/composer.py` and `prompts/composer_*.md` owned by Compo. |
| Citation chips/source registry | `helpers/citations.py` and WebUI citation cards. |
| Streaming message blocks | `helpers/blockstream.py` plus WebUI JSON-Patch handling. |
| Upload vector store | A0 `_memory` reuse via `helpers/uploads.py`. |
| Chat history DB | A0 native chat persistence; no new schema in Phase 1. |

## Stage 1: classify

Owned by Classy / `helpers/classifier.py`.

The classifier produces two orthogonal outputs:

1. **Routing** — which tools should run:
   - skip web search
   - personal/upload search
   - academic search
   - discussion search
   - weather/stock/calculation widgets
2. **Style** — how the answer should be written:
   - `general`
   - `academic_research`
   - `recent_news`
   - `weather`
   - `people`
   - `coding`
   - `recipe`
   - `translation`
   - `creative_writing`
   - `science_math`
   - `url_lookup`

URL detection is regex-prefilled and then refined, because URL lookup should not depend entirely on LLM inference.

## Stage 2: widgets

Owned by Widge / `helpers/widgets_registry.py` and `tools/widget_*.py`.

Widgets follow Vane's pattern:

```text
should_execute(classification) -> execute(...) -> WidgetOutput
```

Current widgets:

- Weather — Nominatim plus Open-Meteo.
- Calculator — `asteval` sandbox.
- Stock — `yfinance`, comparison cap, TTL cache.

Widget failures should degrade into structured failure outputs rather than aborting the whole search. Widget `llmContext` is injected into the composer but explicitly marked as non-citable.

## Stage 3: research

Owned by Reggie / `helpers/researcher.py`.

The research stage is an iterative ReAct-style loop rather than a single search call. Amendments R1 specify:

- speed mode: shallow loop, no scraping.
- balanced mode: up to 6 iterations.
- quality mode: up to `quality_max_iterations` (default 10), includes picker/scrape/extract.

Supporting modules:

- `helpers/searxng_client.py` — SearxNG fetch and result normalization.
- `helpers/reranker.py` — embedding similarity filter and dedup for speed/balanced modes.
- `helpers/picker.py` — quality-mode LLM picker for 2-3 results to scrape.
- `helpers/scraper.py` — Trafilatura scraper in Phase 1.
- `helpers/extractor.py` — chunked fact extraction with concurrency cap.
- `helpers/uploads.py` — personal/upload search via A0 `_memory`.

Research produces findings and ordered source candidates for citation.

## Stage 4: compose

Owned by Compo / `helpers/composer.py` and `prompts/composer_*.md`.

The composer receives:

- normalized query / standalone follow-up
- style primary type
- selected prompt template
- source context block
- widget context block
- mode/depth hints

Prompt families currently present include general, academic, news, coding, people, URL lookup, weather, recipe, translation, creative, and science/math.

Perplexity-style output goals:

- clear markdown sections where useful
- comparison tables when appropriate
- inline bracket citations for factual claims
- no separate references section
- special handling for translation/creative/simple math where citations may be inappropriate

## Stage 5: cite

Owned by Citer / `helpers/citations.py`.

Citation architecture follows Vane's source registry idea but improves it:

1. Build an ordered URL-deduplicated source registry.
2. Concatenate repeated URL content rather than creating duplicate citations.
3. Render source context with stable `<result index=N>` markers.
4. Let the composer emit `[N]` citations.
5. Post-hoc scan emitted citations and drop or repair out-of-range references.

Widget results are not source citations.

## Stage 6: blockstream

Owned by Orchy / `helpers/blockstream.py`.

Vane's UX depends on typed progressive blocks, not just final markdown. A0_Fauxplexica tracks this with block types such as:

- `reasoning`
- `searching`
- `search_results`
- `reading`
- `source`
- `widget`
- `text`

Updates use JSON-Patch-style operations so the WebUI can progressively update a block rather than repainting a whole answer.

Phase 1 accepts that reload/history may show markdown rather than exact block replay. Sidecar block persistence is deferred to Phase 2.

## WebUI track

Current WebUI files:

- `webui/main.html`
- `webui/config.html`
- `webui/fauxplexica-store.js`
- `webui/citation-card.html`
- `webui/thumbnail.jpg`

Target UI pieces:

- search bar
- mode toggle
- source chips
- progressive reasoning/search/read blocks
- answer pane
- clickable citation sidebar/cards
- config panel for SearxNG URL, default mode, sources, widgets, and model roles

Final polish depends on stable blockstream/API contracts.

## API track

Planned Phase 1 API surfaces:

- `POST /api/fauxplexica/search`
- `GET /api/fauxplexica/providers`

`GET /api/fauxplexica/suggest` is present as a Phase 2 placeholder.

The search API target is NDJSON over `text/event-stream` for streaming and a JSON answer/sources/citations object for non-streaming use.

## Storage and history

Phase 1 avoids a new database schema:

- A0 native chat persistence stores chat/messages.
- `_memory` stores upload embeddings.
- `helpers/history.py` can layer per-search metadata where needed.
- Block sidecar persistence is deferred.

## Current status boundaries

Wave 1b delivered broad helper/tool/test surfaces. Wave 2 is expected to finalize behavior for:

- Reggie research loop.
- Orchy orchestration/blockstream integration.
- Compo composer/prompt enforcement.
- QA integration coverage.

Citer, APIs, WebUI, and profile integration remain required before final user-facing docs can be marked stable.
