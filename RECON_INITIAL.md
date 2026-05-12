# RECON_INITIAL — Vane Upstream Intelligence (Phase 1, Pass 1)

*Author: Recon (researcher superordinate). Date: 2026-05-11. Upstream: `ItzCrazyKns/Vane@master`. Perplexity corpus: `x1xhlol/system-prompts-and-models-of-ai-tools/Perplexity/Prompt.txt`.*

This report is the result of a full code-dive against Vane's `src/` tree (every file under `src/lib/agents/search/**`, prompts, SearxNG client, scraper, and both `/api/chat` + `/api/search` routes) plus the Perplexity system-prompt corpus. Sections below are aligned 1-to-1 with the deliverables requested by A0_Fauxplexica.

---

## 1. Deep code dive — `src/` structure → A0 component mapping

### 1.1 Top-level src/ map

| Vane path | Responsibility | Maps to our A0 plugin component |
|---|---|---|
| `src/app/api/chat/route.ts` | Main streaming chat endpoint. zod-validates body, loads chat+embedding models, spawns `SearchAgent.searchAsync`, streams `block` / `updateBlock` / `researchComplete` / `messageEnd` envelopes as newline-delimited JSON. Also ensures chat row via Drizzle. | Replaced by A0's native chat pipeline. We do NOT need a `/api/chat` of our own — A0 already streams messages. Our plugin replicates the *agent* behavior, not the transport. |
| `src/app/api/search/route.ts` | Programmatic search endpoint (`APISearchAgent`). Returns `{message, sources}` JSON, or streams `init/sources/response/done` events. | Direct analog: `a0_fauxplexica/api/search.py` (already in plan). Contract is stable; we should copy the response schema verbatim for ecosystem compat. |
| `src/app/api/providers/route.ts`, `providers/[id]/...` | Model registry CRUD. | `api/providers.py` shim over `_model_config`. CRUD is OUT OF SCOPE — read-only listing is enough. |
| `src/app/api/discover/route.ts`, `suggestions/route.ts`, `uploads/route.ts`, `images/route.ts`, `videos/route.ts`, `weather/route.ts`, `reconnect/[id]/route.ts`, `chats/...`, `config/...` | Discover feed, autosuggest, uploads, image/video search, raw weather, session reconnect, chat history. | Phase 2 surface area. Only `uploads` is partially in Phase 1 (we reuse `_memory`). |
| `src/components/**` | React UI: `Chat.tsx`, `MessageBox.tsx`, `MessageRenderer/Citation.tsx`, `MessageSources.tsx`, `Widgets/{Weather,Stock,Calculation,Renderer}.tsx`, `ThinkBox.tsx`, `Settings/Sections/Search.tsx`, `Setup/SetupWizard.tsx`, `MessageInputActions/{Sources,Optimization,ChatModelSelector}.tsx`. | Patterns to mirror in `webui/main.html` + `fauxplexica-store.js`. Important UI primitives: source chip row, mode toggle (Speed/Balanced/Quality), citation popover, `<ThinkBox>` reasoning panel, `<AssistantSteps>` step-by-step block. We should adopt the **block-based render model** (see §2). |
| `src/lib/agents/search/index.ts` | Core orchestrator `SearchAgent.searchAsync`. | `helpers/orchestrator.py` (our **Orchy**). |
| `src/lib/agents/search/classifier.ts` + `src/lib/prompts/search/classifier.ts` | Single-shot structured-output classifier. | `helpers/classifier.py` + `prompts/classifier.md` (**Classy**). |
| `src/lib/agents/search/researcher/index.ts` | Iterative tool-loop research agent. | New: needs explicit `helpers/researcher.py` — **not in current plan**. Phase 1 plan rolls this into Orchy; recommend splitting. |
| `src/lib/agents/search/researcher/actions/` | Pluggable tool registry: `plan`, `done`, `web_search`, `academic_search`, `social_search`, `scrape_url`, `uploads_search`. | A0-native: each becomes a registered tool under `tools/`. We can lean on A0's existing tool dispatcher rather than reimplement a registry. |
| `src/lib/agents/search/researcher/actions/search/baseSearch.ts` | Shared search executor: SearxNG fetch, per-result embedding, similarity filter, embedding-based dedup, picker-LLM (quality), scraper, extractor-LLM (quality). | This is the **biggest file we underestimated** (423 LOC). Split into: `helpers/searxng_client.py`, `helpers/reranker.py`, `helpers/scraper.py`, `helpers/extractor.py`. See §2 + §6. |
| `src/lib/agents/search/widgets/{weather,calculation,stock}Widget.ts` + `executor.ts` + `index.ts` | Widget registry; each widget has `shouldExecute(classification)` + `execute(input) → {type, llmContext, data}`. | `helpers/widgets_registry.py` + `tools/widget_*.py`. |
| `src/lib/agents/suggestions/index.ts` | Suggestion generator (LLM → array of strings). | Phase 2 (`tools/fauxplexica_suggest.py`). |
| `src/lib/agents/media/{image,video}.ts` | Image/video search agents. | Phase 2. |
| `src/lib/prompts/search/{classifier,researcher,writer}.ts` | All system prompts. Researcher prompt is **mode-aware** (speed/balanced/quality) — three distinct flavors. | `prompts/classifier.md`, `prompts/researcher_{speed,balanced,quality}.md`, `prompts/composer_*.md`. We MUST keep mode-specific researcher prompts; current plan has only one. |
| `src/lib/searxng.ts` | Thin SearxNG client (URL builder + JSON parse). | `helpers/searxng_client.py`. Trivial port. |
| `src/lib/scraper.ts` | Playwright + Readability scraper, singleton browser, idle-kill timer. | `helpers/scraper.py` — recommend Trafilatura (`pip install trafilatura`) instead of headless browser for Phase 1; matches what `_memory`/RAG tooling typically uses and avoids Chromium dep. Playwright-Python only if hard sites force it. |
| `src/lib/uploads/{manager,store}.ts` | File upload manager + per-fileId vector store with similarity search. | Reuse `_memory` plugin (`helpers/uploads.py` thin wrapper). |
| `src/lib/utils/{computeSimilarity,jaccardSim,splitText,formatHistory,hash,files}.ts` | Vector cosine sim, Jaccard for text, recursive text splitter, history formatter. | `helpers/utils.py` — port `splitText` (4000 char / 500 overlap defaults) and cosine similarity. |
| `src/lib/models/**` | Multi-provider abstraction (OpenAI/Anthropic/Gemini/Groq/Ollama/Lemonade/LMStudio/Transformers). | Skip entirely — A0's `_model_config` covers this. |
| `src/lib/db/{schema,migrate,index}.ts` + `drizzle.config.ts` | SQLite via Drizzle ORM; tables: `chats`, `messages`, providers, etc. | Skip — A0 chat persistence. We only need a tiny `helpers/history.py` for search-index metadata (Phase 2). |
| `src/lib/session.ts` | In-memory event bus + JSON-Patch block updater. `emitBlock`, `updateBlock`, `subscribe(event, data)`. Drives streaming UI. | We need this concept inside our `composer`/`orchestrator`: a **block stream** abstraction so WebUI can show `reasoning`, `searching`, `search_results`, `reading`, `source`, `widget`, `text` blocks progressively. **Not currently in plan — recommend adding `helpers/blockstream.py`.** |
| `src/lib/types.ts` | All block types: `TextBlock`, `ResearchBlock` (with `subSteps: ReasoningResearchBlock | SearchingResearchBlock | SearchResultsResearchBlock | ReadingResearchBlock | UploadSearchingResearchBlock | UploadSearchResultsResearchBlock`), `SourceBlock`, `WidgetBlock`. | Important: **block-based incremental UI is the heart of Vane's UX**. WebUI panel must speak this dialect. |

### 1.2 Architectural delta vs Phase 1 plan

- Plan section 2 lumps research+orchestrator together. Vane splits them: `SearchAgent` (top-level coordinator) + `Researcher` (inner agentic loop). Recommend the same split → either rename **Orchy** to coordinate and add a new persistent super **Reggie** (researcher), OR have Orchy spawn ephemeral subordinates per iteration.
- Plan doesn't mention the **block stream** model. The WebUI panel needs to handle progressively emitted blocks and JSON-Patch updates; otherwise the UX collapses to plain markdown.
- Plan undercounts SearxNG complexity (see §2 + §6.1).

---

## 2. Pipeline diff — Vane actual vs the abstract "Vane architecture" we had

### 2.1 Documented (our PLAN_PHASE1 §1.2)

> classify → parallel(research, widgets) → compose with citations

### 2.2 Actual (from `src/lib/agents/search/index.ts` + `researcher/index.ts` + `widgets/executor.ts` + `baseSearch.ts`)

```
SearchAgent.searchAsync
├─ DB upsert message row (status=answering, responseBlocks=[])
├─ classify({chatHistory, enabledSources, query, llm}) → ClassifierOutput { classification{7 booleans}, standaloneFollowUp }
├─ WidgetExecutor.executeAll  ┐  (parallel)
│                              ├─ for each registered widget where shouldExecute(classification): execute(...) → {type, llmContext, data}
│                              └─ emit per-widget block to session
├─ if !classification.skipSearch:
│   Researcher.research → ResearcherOutput { findings[], searchFindings[] }
│   ├─ build availableTools + availableActionsDescription (mode-aware) via ActionRegistry
│   ├─ emit empty ResearchBlock {subSteps:[]}
│   ├─ FOR iter in 1..maxIter   (speed=2, balanced=6, quality=25)
│   │   ├─ stream LLM(researcher_prompt(mode, iter, maxIter, files), history, tools=availableTools)
│   │   ├─ collect ToolCalls; if first ToolCall is __reasoning_preamble → emit reasoning sub-step
│   │   ├─ if no tool calls OR last tool is `done` → break
│   │   ├─ Promise.all execute(toolCalls)  ← tools include web_search/academic_search/social_search/scrape_url/uploads_search
│   │   └─ append tool results to agent message history
│   ├─ collect actionOutput[type=='search_results'].results into searchResults[]
│   ├─ DEDUP by url: same URL → concat content with "\n\n"
│   └─ emit final SourceBlock(filteredSearchResults)
├─ session.emit('data',{type:'researchComplete'})
├─ build finalContext:
│   <search_results>\n  <result index=N title=...>{content}</result>...\n</search_results>\n
│   <widgets_result noteForAssistant="...do not CITE">{llmContext}</widgets_result>
├─ writer_prompt(finalContextWithWidgets, systemInstructions, mode)
├─ stream LLM → emit incremental TextBlock with JSON-Patch updates
└─ DB update message row (status=completed, responseBlocks=session.getAllBlocks())
```

### 2.3 Stages we missed in the planning doc

| # | Stage | Where in Vane | Why it matters for us |
|---|---|---|---|
| **A** | **Per-iteration agentic loop** with `__reasoning_preamble` pseudo-tool | `researcher/index.ts:60-100`, `actions/plan.ts` | We had "research" as one shot. Actually it's a 2-25 iteration ReAct loop. The first "tool" each iteration is a fake `__reasoning_preamble` whose only job is to surface visible chain-of-thought. **A0 mapping**: drop the fake-tool trick — A0 already exposes thoughts via the `thoughts` array. But we need to mirror this in the WebUI as a "reasoning" sub-block. |
| **B** | **Per-result embedding + similarity filter** | `baseSearch.ts:36-83` (speed/balanced branch) | Each SearxNG result has its `content` embedded, cosine-compared against the query embedding, filtered at `> 0.5`. Falls back to `similarity=1` (i.e. keep-all) on embedding failure. This is a **re-ranking layer** the plan doesn't mention. |
| **C** | **Embedding-based dedup** | `baseSearch.ts:122-148` | After per-query embedding, cross-result cosine `> 0.75` is dropped as duplicate. Final results sorted by similarity, sliced to 20. |
| **D** | **URL-level dedup with content concat** | `researcher/index.ts:177-199` | Top-level: same `metadata.url` → second occurrence's content appended to first with `\n\n`, second dropped. |
| **E** | **Picker LLM (quality mode only)** | `baseSearch.ts:177-258` | Separate LLM call selects 2-3 most-relevant search results to scrape (criteria: relevance, content quality, reputation, diversity). Returns `picked_indices: number[]`. |
| **F** | **Scrape + extractor LLM (quality mode only)** | `baseSearch.ts:260-365`, `scrapeURL.ts:130-180` | For each picked result: Playwright+Readability scrape → splitText into 4000-char chunks (500 overlap) → per-chunk extractor LLM producing structured `extracted_facts: string` (telegram-style bullets) → concatenate. Numerical/table fidelity is explicitly preserved by prompt. |
| **G** | **Mode-specific researcher prompts** | `prompts/search/researcher.ts` (three functions: `getSpeedPrompt`/`getBalancedPrompt`/`getQualityPrompt`) | Each mode has its own ReAct strategy (speed: 1 call, balanced: alternate reason/act with cap 6, quality: iterative deep-research with `<research_strategy>` 7-angle checklist). |
| **H** | **Widget llmContext fold-in** | `agents/search/index.ts:108-118` | Widgets contribute a `llmContext` string that's injected into composer prompt under `<widgets_result>` with an explicit `do not CITE this as a source` instruction. |
| **I** | **Block-based streaming render model** | `session.ts` + all `session.emitBlock`/`session.updateBlock` calls | Output is a sequence of typed blocks (`research`/`source`/`widget`/`text`) updated via JSON-Patch ops over a streaming socket. Phase 1 plan has "answer pane + citation sidebar" but no streaming primitive. |
| **J** | **Iteration safety net** | `researcher/index.ts:153-159` | `done` is also implicitly triggered when no tool calls produced OR when last tool is literally `done`. |

### 2.4 Recommended plan amendments

1. Add explicit **re-ranking** (`helpers/reranker.py`) and **picker-LLM** (`helpers/picker.py`, quality mode) helpers.
2. Add explicit **extractor-LLM** (`helpers/extractor.py`) helper with chunked splitText port.
3. Add **`helpers/blockstream.py`** (or piggy-back on A0's existing message-block schema) and define our block types: `reasoning`, `searching`, `reading`, `search_results`, `source`, `widget`, `text`.
4. Split **Researcher** out of Orchy; make Orchy a thin coordinator that fires Classify → (Widgets || Researcher) → Composer.
5. Adopt mode-specific researcher prompts; do NOT collapse into one.
6. Skip Playwright in Phase 1; use Trafilatura (or Newspaper3k) for scrape. Document Playwright as Phase 2 hardening when JS-heavy sites bite.

---

## 3. Citation mechanics — exact algorithm

### 3.1 Source registry

- `searchFindings: Chunk[]` is the **canonical ordered list** of sources. Built inside `Researcher.research`:
  1. Iterate all tool results of `type==='search_results'`, flatten `.results`.
  2. Walk in order; for each `metadata.url`, first occurrence keeps index; subsequent occurrences APPEND their `content` to the existing entry's content with `\n\n` separator. Subsequent occurrences are DROPPED from the array.
  3. Result: ordered, URL-unique `Chunk[]` where each `Chunk = {content, metadata:{title, url, ...}}`.
  4. **Speed/Balanced extra:** before dedup, results are sorted by per-query cosine similarity descending and sliced `[0,20]`. Chunks below 0.5 similarity threshold are pre-filtered.
  5. **Quality extra:** for the picked subset, content is replaced with the LLM-extracted facts (so the citation index points at *the synthesized fact bundle*, not the raw page).

### 3.2 `[n]` injection — where does the number come from

There is **no programmatic citation injection** in Vane. The composer prompt instructs the LLM:

```
- Cite every single fact, statement, or sentence using [number] notation
  corresponding to the source from the provided `context`.
- ... Ensure that every sentence in your response includes at least one citation
- Use multiple sources for a single detail if applicable, such as,
  "Paris is a cultural hub, attracting millions of visitors annually[1][2]."
```

The context block fed to the writer is literally:

```
<search_results note="These are the search results and assistant can cite these">
<result index=1 title=...>{chunk.content}</result>
<result index=2 title=...>{chunk.content}</result>
...
</search_results>
<widgets_result noteForAssistant="... do not CITE this as a souce">
<result>{widget.llmContext}</result>
</widgets_result>
```

So `[n]` is **the LLM-emitted index that matches `index=N` in the context block**, which equals `searchFindings[N-1]`. The WebUI then resolves `[n]` → `sources[n-1].metadata.{title,url}` to render clickable citation chips. **There is no post-hoc validation that `[n]` resolves**; if the model hallucinates `[42]` and there are only 7 sources, it silently fails.

### 3.3 Trust scoring

- **No explicit trust scoring** in code.
- Implicit trust signals:
  - **Speed/Balanced mode** — cosine similarity to query (no source quality input).
  - **Quality mode picker LLM** — prompt instructs: *"Favour known and reputable sources"*, *"Diversity"*, *"Maximum 3 results"*. So "trust" is a behavioural instruction to an LLM, not a numeric score.

### 3.4 Dedup recap

1. **Within a single search call** (speed/balanced): embedding-based cosine dedup at threshold `0.75`.
2. **Across all tool calls in researcher loop**: URL-key dedup with content concat.
3. **`scrape_url` action** has its own anti-double-read guard: tracks `alreadyExtractedURLs` so the quality picker doesn't re-scrape what's already in a `reading` sub-block.

### 3.5 Recommended A0 implementation (`helpers/citations.py`)

- Build `SourceRegistry` exactly like Vane: ordered list, URL-dedup, content-concat.
- Render context block with `<result index=N title=...>` markers identical to Vane.
- **Add a post-hoc validator** the upstream lacks: after composer emits text, regex-scan `\[(\d+)\]`, ensure each `n` ≤ `len(sources)`. If not, either drop the bad citation or fall back to the nearest valid neighbour and log a metric.
- Add cosine re-rank (speed/balanced) + picker-LLM (quality) — both as separately togglable helpers.

---

## 4. Query classification — Vane vs Perplexity, reconciled

### 4.1 Vane's classifier output schema (from `src/lib/agents/search/classifier.ts`)

```ts
{
  classification: {
    skipSearch: boolean,
    personalSearch: boolean,     // user-uploaded files
    academicSearch: boolean,
    discussionSearch: boolean,
    showWeatherWidget: boolean,
    showStockWidget: boolean,
    showCalculationWidget: boolean,
  },
  standaloneFollowUp: string
}
```

**These are ROUTING flags** — they decide which tools fire. They are not answer-style hints.

### 4.2 Perplexity `<query_type>` taxonomy (from the corpus)

*These are answer-STYLE specializations driving the composer.*

| query_type | Style directive |
|---|---|
| Academic Research | Long, detailed, scientific paper format, markdown headings |
| Recent News | Concise; group by topic; lists with bolded news titles; diverse perspectives; recency priority |
| Weather | Very short; only forecast; if no data → admit it |
| People | Short comprehensive biography; never start with the name as header; separate sections if multiple people |
| Coding | Code block first, language tag, then explanation |
| Cooking Recipes | Step-by-step, ingredient + amount + precise instructions |
| Translation | NO citations, just the translation |
| Creative Writing | NO citations, follow user instructions precisely |
| Science and Math | Final result only for simple calc |
| URL Lookup | Use ONLY the corresponding search result, always cite `[1]` |

### 4.3 The two axes are orthogonal

- **Routing axis** (Vane) answers: *which tools should fire?*
- **Style axis** (Perplexity) answers: *how should the composer write the answer?*

We need BOTH. Our plan only encoded one.

### 4.4 Unified taxonomy for `helpers/classifier.py` (Classy)

Proposed schema (single LLM call, structured output):

```python
{
  "routing": {
    "skip_search":          bool,  # answer from general knowledge / widget
    "personal_search":      bool,  # uploaded files
    "academic_search":      bool,  # arxiv/scholar/pubmed engines
    "discussion_search":    bool,  # reddit/forums
    "widgets": {
      "weather":            bool,
      "stock":              bool,
      "calculation":        bool
    }
  },
  "style": {
    "primary_type": Literal[
      "general", "academic_research", "recent_news", "weather",
      "people", "coding", "recipe", "translation",
      "creative_writing", "science_math", "url_lookup"
    ],
    "freshness": Literal["any","week","day"],   # drives SearxNG time_range
    "depth_hint": Literal["short","medium","deep"]  # advisory to composer
  },
  "standalone_followup": str,
  "detected_urls": list[str]    # populate from regex; if non-empty, style.primary_type bias toward url_lookup
}
```

Rationale:

- Keep Vane's seven booleans 1:1 under `routing` so existing logic ports cleanly.
- Add `style.primary_type` with the 10 Perplexity types + a `general` fallback.
- `style.freshness` and `style.depth_hint` cover behaviour the Perplexity prompts hint at (Recent News recency, Academic depth) but Vane currently doesn't classify.
- `detected_urls` — Perplexity URL Lookup needs deterministic URL detection; an LLM-classified bool is unreliable here. Pre-fill via regex, the LLM only refines.
- Composer template selection: `style.primary_type` → `prompts/composer_{primary_type}.md`. We already have most of these slots in the plan; add `recipe` and `url_lookup` (missing).

### 4.5 New composer prompts needed beyond Phase 1 plan

Plan currently lists: general, academic, news, coding, people, url. Add:
- `composer_weather.md` (terse forecast)
- `composer_recipe.md` (step-by-step recipe)
- `composer_translation.md` (no citations)
- `composer_creative.md` (no citations, ignore search if irrelevant)
- `composer_science_math.md` (final-result-only short mode)

---

## 5. Widgets — Vane inventory & alignment with our three

### 5.1 Vane's complete widget roster

| Widget | File | External dep | Trigger | Output shape |
|---|---|---|---|---|
| **weatherWidget** | `widgets/weatherWidget.ts` | Nominatim (geocode) + Open-Meteo (forecast) | `classification.showWeatherWidget` | `{type:'weather', llmContext, data:{location, lat, lon, current, hourly(24h), daily(7d), timezone}}` |
| **calculationWidget** | `widgets/calculationWidget.ts` | `mathjs` | `classification.showCalculationWidget` | `{type:'calculation_result', llmContext, data:{expression, result}}` |
| **stockWidget** | `widgets/stockWidget.ts` | `yahoo-finance2` (Yahoo Finance) | `classification.showStockWidget` | `{type:'stock', llmContext, data:{symbol, quote(~40 fields), chartData{1D,5D,1M,3M,6M,1Y,MAX}, comparisonData?}}` |

That's the **entire widget set** — no others currently. Our Phase 1 three match Vane exactly.

### 5.2 Widget execution pattern (canonical)

```ts
{
  type: string,                                  // stable widget id
  shouldExecute: (classification) => boolean,    // pure function over classifier output
  execute: async (input: {chatHistory, followUp, classification, llm}) =>
    Promise<{type: string, llmContext: string, data: any} | void>
}
```

Key points to mirror:

1. **Two-stage**: classifier flags it on → widget itself runs an *inner* LLM call to extract structured params (location / expression / ticker) → external API → returns `data` + a one-line `llmContext` string.
2. **`llmContext` is the writer's view of the widget** — it's small, factual, and gets injected into the composer prompt under `<widgets_result>` with explicit *do not cite* instruction.
3. **Graceful degradation**: every widget catches its external-API errors and returns `{type, llmContext:'Failed to fetch…', data:{error:'…'}}` rather than throwing.
4. **Parallel-with-research**: widget executor runs concurrently with the research loop (`Promise.all([widgetPromise, searchPromise])`).

### 5.3 Alignment & micro-adjustments for our build

- **widget_weather.py** — port near-verbatim: Nominatim → Open-Meteo. Same hourly/daily slice (24h hourly, 7d daily). Same `notPresent` escape hatch in the param-extractor LLM.
- **widget_calc.py** — Python equivalent of mathjs is `sympy` (safer, no eval) or `asteval` (lightweight, sandboxed). **Recommend `asteval`** — closer to mathjs's behavior, no symbolic overhead. Avoid raw `eval`.
- **widget_stock.py** — `yfinance` (Python equivalent of yahoo-finance2). Same 7 time ranges + up-to-3 comparisons. **Gotcha**: `yfinance` is rate-limited and occasionally breaks when Yahoo changes their unofficial endpoints (see §6.3). Implement aggressive caching (e.g. 5-minute TTL per ticker) from day one.
- All three should expose `should_execute(classification_dict) -> bool` and `execute(...) -> WidgetOutput` matching the dataclass above.
- The **inner param-extractor LLM** for each widget is **mandatory**, not optional. Skipping it (e.g. trying to regex the location out of the query) will hurt accuracy badly. Reuse a small/fast model preset for these inner extractors to control cost.

### 5.4 Phase-2 widget candidates spotted in code/UI

- `src/components/NewsArticleWidget.tsx` exists but no backend widget → likely Discover-feed-only. Not actionable for Phase 1.
- No translation/conversion/sports widgets — opportunity space for differentiation later.

---

## 6. Risks & gotchas — things harder than they look

### 6.1 SearxNG

- **Public instances are unreliable.** Vane assumes a self-hosted SearxNG (`getSearxngURL()` reads from server registry, no fallback). We MUST ship a docker-compose template; pointing at random public SearxNG instances will rate-limit users into the ground.
- **Engines parameter is comma-joined.** Vane's client serializes arrays as `key=val1,val2` (see `src/lib/searxng.ts`). SearxNG accepts this **only on some instances**; the official docs prefer repeated `?engines=` params. Test against real instance during Searx build.
- **Categories vs Engines confusion.** Vane uses `engines: ['arxiv','google scholar','pubmed']` for academic and `engines: ['reddit']` for social. Mind that Google Scholar engine is often disabled in default SearxNG configs (`engines.yml` `disabled: true`). Document this in the BYO-SearxNG guide.
- **No `time_range` / `safesearch` plumbing** in Vane's client. We should add them — our classifier emits a `freshness` hint.
- **Pagination not implemented.** Vane fetches page 1 only. For quality mode we may want page 2.

### 6.2 Scraper (Playwright + Readability)

- **Heavy dependency**: a headless Chromium binary in the Docker image is ~300MB. The plan should explicitly NOT carry this in Phase 1.
- **Singleton browser + idle-kill** pattern is non-trivial: shared mutex, 30s idle close, navigation timeout 20s. Trying to faithfully port this to Python (Playwright-Python) duplicates the complexity for marginal benefit in MVP.
- **Readability fails on JS-heavy sites** despite Playwright; Vane returns `# {url}\n\nError scraping content.` in the catch. Acceptable fallback.
- **Recommendation**: Phase 1 → Trafilatura (handles ~80% of real-world pages, pure Python, no browser). Phase 2 → add a `playwright_fallback` flag that boots Chromium for the 20% of pages Trafilatura returns empty on.

### 6.3 Yahoo Finance / `yfinance`

- Yahoo Finance unofficial endpoints break **frequently** (auth quirks, geo blocks). `yahoo-finance2` (TS) and `yfinance` (Python) both ship periodic emergency patches.
- The stock widget does **eight chart fetches per primary ticker plus seven per comparison ticker** — up to 8 + 3×8 = 32 HTTP calls per stock query. Rate limiting is a real risk.
- **Mitigation**: per-ticker chart cache with 5-min TTL; bound `comparisonNames` to 2 instead of 3 by default.

### 6.4 Iterative research loop

- **Quality mode `maxIteration = 25`** — combined with up to 3 `web_search` queries per iteration and per-chunk extractor LLM calls during scraping, a single "quality" answer can fire **dozens of LLM calls + tens of HTTPS fetches**. Latency and cost both balloon. Recommend Phase 1 cap quality at 10 iterations to start; reveal a config slider for power users.
- **`__reasoning_preamble` enforcement is prompt-only.** If the LLM skips it, the prompt threatens *"the tool call will be ignored"* — but the code itself doesn't actually ignore subsequent tool calls. The threat is empty. Real enforcement would require dropping non-preamble first tool calls in the receive loop; Vane does not do this. We can do better by enforcing it in code.
- **`done` is also the loop break on empty tool calls** (no-op safety). Need to handle empty-tool-call iteration gracefully so the model can't infinite-loop.
- **Tool-call streaming reassembly**: tool-call chunks arrive incrementally; Vane reassembles by `tc.id` (see `researcher/index.ts:128-141`). A0's tool calls are turn-based, not chunked — simpler, but we lose the live "thinking with running plan" UI affordance. Bridge: emit the `thoughts` array as a `reasoning` sub-block.

### 6.5 Streaming protocol

- Vane uses **newline-delimited JSON over `text/event-stream`**, not standard SSE `data:` framing. That's a quirk — most SSE clients expect the `data:` prefix. Our `/api/fauxplexica/search` should choose: faithfully copy Vane's NDJSON-over-SSE (max ecosystem compat) OR use real SSE (cleaner). **Recommend faithfully copy** for drop-in API compatibility.
- **Block update semantics use JSON-Patch ops** (`{op:'replace', path:'/data/subSteps', value:[…]}`). Our WebUI panel needs a JSON-Patch applier (`fast-json-patch` is tiny).
- **Abort handling**: Vane wires `req.signal` → `abortController` → `controller.close()` and `session.removeAllListeners()`. We must replicate cancellation in `api/search.py` (FastAPI's `request.is_disconnected()` poll).

### 6.6 Embeddings on hot path

- Speed/balanced mode embeds *the query plus every SearxNG result content* (typically 10-30 strings per query). If A0's default embedding model is a slow remote one, we'll feel it. **Mitigation**: use a small local embedder for re-ranking only (sentence-transformers `all-MiniLM-L6-v2`-class), separate from the user's primary `_memory` embedder.
- The embedding-failure fallback (`similarity=1` for every result) silently disables re-ranking. We should at least log a warning.

### 6.7 Token budget / context length

- Quality mode can stack: 20 chunks × 2-5k chars each = 40-100k chars of context into the writer. That fits Claude/GPT-4 easily but kills smaller local models. Need a `context_budget_chars` setting in `default_config.yaml` to cap.

### 6.8 Hidden coupling: classifier ↔ tool registry ↔ widgets

- `webSearchAction.enabled = config.sources.includes('web') && !classification.skipSearch`. **Sources and classifier flags are AND'd together**, not OR'd. If a user disables `web` in the source picker but the classifier wants web, no search happens. Mostly correct but creates surprising UX: "Why didn't it search?" Document this in the WebUI tooltip on the source chip row.
- `uploadsSearchAction.enabled` allows `fileIds.length > 0` to override `classification.personalSearch === false`. Intentional generosity — port it.

### 6.9 Drizzle/DB → A0 chat persistence mismatch

- Vane's `messages` table stores `responseBlocks: jsonb` with the full block stream. A0 chat persistence stores plain markdown text. **Block fidelity is lost on reload** unless we either (a) accept this regression in Phase 1, or (b) write a thin `helpers/history.py` that snapshots the blocks JSON to a sidecar file under `<context>/fauxplexica/`. Recommend (a) for Phase 1; flag (b) for Phase 2.

### 6.10 Subtle correctness bugs in Vane we should NOT inherit

- `researcher/index.ts:189-194` — when the same URL appears twice, it appends the second `content` to the FIRST entry but returns it from the map at position `index` (which is the second occurrence), causing the `seenUrls` index to drift versus the actual array. The subsequent `.filter(r !== undefined)` saves it, but the logic is shaky. Implement cleaner: pure left-fold with a dict.
- `classifier.ts` JSON schema has a **trailing comma** after `showCalculationWidget: boolean,` in the example output — most LLMs handle it but strict JSON parsers would not. Use `"messageEnd"` style without trailing commas.
- `baseSearch.ts` extractor's `splitText(content, 4000, 500)` runs **all chunks in parallel** through `generateObject`. For long pages (10+ chunks) this hammers the LLM provider; rate-limit per-page concurrency (e.g. semaphore at 3).
- Quality-mode `executeSearch` does not actually compute `similarity` — every chunk gets `similarity: 1`. So the sort-by-similarity step that's part of speed/balanced is a no-op for quality. Probably fine (picker LLM handles ranking) but inconsistent.

---

## 7. Bonus: Architecture nuggets worth stealing verbatim

- **Block-based render model** — by far the biggest UX lever. Without it, the WebUI panel feels like ChatGPT instead of Perplexity.
- **`llmContext` per widget** — clean separation of "what to show the user" (data) from "what to tell the writer" (one factual sentence). Bake this into our `WidgetOutput` dataclass.
- **`<result index=N title=…>` context wrapping** — keeps the citation index implicit but stable.
- **The explicit `do not CITE this as a source` instruction on widget context** — prevents the model from inventing `[1]` for the weather widget.
- **Mode → maxIteration mapping** (2/6/25) — start identical, tune later with telemetry.
- **Picker LLM in quality mode** — separates breadth (search) from depth (scrape) so we don't scrape 20 URLs.

---

## 8. Followup-pass shopping list

Things I did NOT do this pass that should be the next diff:

1. Walk every file under `src/components/` to extract exact UI primitives (citation popover anatomy, ThinkBox affordance, source chip layout) and produce HTML/CSS templates.
2. Read `src/lib/uploads/{manager,store}.ts` end-to-end to spec file-RAG semantics for **Filey**.
3. Diff `docs/architecture/README.md` (referenced but not yet pulled) for any planning-doc claims we missed.
4. Watch the upstream commit log for the next 7 days (`recon_diff` cycle) — Vane has been moving fast.

---

*End of RECON_INITIAL pass 1.*
