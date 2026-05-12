# PLAN_PHASE1 — Amendments R1 (from Recon Pass 1)

*Date: 2026-05-11. Source: `RECON_INITIAL.md` Pass 1. Status: LOCKED — supersedes corresponding sections of `PLAN_PHASE1.md`.*

Recon's deep code-dive against Vane's `src/` (especially `lib/agents/search/**`) surfaced material gaps in the original Phase 1 plan. The amendments below are now part of the build contract.

---

## A1. Roster change — split **Reggie** out of Orchy

Orchy becomes a thin coordinator (Classify → parallel(Widgets, Reggie) → Composer). A new persistent super **Reggie** owns the iterative ReAct research loop.

| # | Name | Profile | Owns |
|---|---|---|---|
| 4a | **Orchy** | developer | `helpers/orchestrator.py` — coordinator only; runs classifier, fires widgets/reggie in parallel, hands findings to composer |
| 4b | **Reggie** *(new)* | developer | `helpers/researcher.py` — ReAct loop (speed=2, balanced=6, quality=10 iter), tool selection, search-result accumulation, URL-level dedup with content-concat |

## A2. New helper modules (added to plugin `helpers/`)

- `helpers/researcher.py` — iterative agentic loop (owned by Reggie)
- `helpers/reranker.py` — per-result embedding + cosine similarity filter (>0.5) + cross-result dedup (>0.75); used in speed/balanced modes
- `helpers/picker.py` — quality-mode LLM picker that selects 2–3 most-relevant results to scrape; criteria: relevance, content quality, reputation, diversity
- `helpers/extractor.py` — quality-mode chunked extractor LLM; ports Vane's `splitText(content, 4000, 500)` and produces telegram-style fact bundles per chunk; **semaphore concurrency cap = 3** per page (we improve on Vane's unbounded `Promise.all`)
- `helpers/scraper.py` — **Trafilatura-based** in Phase 1 (pure Python, no Chromium); Playwright fallback deferred to Phase 2 behind a config flag
- `helpers/blockstream.py` — block-stream abstraction for incremental WebUI updates; block types: `reasoning`, `searching`, `search_results`, `reading`, `source`, `widget`, `text`. JSON-Patch ops for updates. **Critical UX primitive — without this our WebUI feels like ChatGPT not Perplexity.**
- `helpers/utils.py` — port Vane's `splitText`, cosine similarity, format_history helpers

Original helpers (`searxng_client.py`, `query_builder.py`, `classifier.py`, `orchestrator.py`, `composer.py`, `citations.py`, `widgets_registry.py`, `history.py`) remain.

## A3. Mode-specific researcher prompts (×3)

Replace single researcher prompt with three flavours under `prompts/`:

- `prompts/researcher_speed.md` — 1-shot, parallel `web_search` calls only, no scraping
- `prompts/researcher_balanced.md` — alternating reason/act, max 6 iter, no scraping
- `prompts/researcher_quality.md` — `<research_strategy>` 7-angle checklist, max 10 iter (we cap **lower than Vane's 25** for Phase 1 cost control; expose as setting), includes `scrape_url` action

## A4. Expanded composer prompts (10 total)

Original plan covered 6. Add the following 4 to match the full Perplexity `<query_type>` taxonomy plus 1 missed:

- `prompts/composer_weather.md` — terse forecast, no citations if data sparse
- `prompts/composer_recipe.md` — step-by-step with ingredient amounts
- `prompts/composer_translation.md` — **no citations**, just the translation
- `prompts/composer_creative.md` — **no citations**, follow user instructions, may ignore search
- `prompts/composer_science_math.md` — final-result-only short mode for simple calc
- *(plus the original 6: general, academic, news, coding, people, url_lookup)*

## A5. Unified classifier output schema

Vane's classifier outputs ROUTING flags only. Perplexity prompts encode STYLE. We need both — orthogonal axes. New schema for `helpers/classifier.py`:

```python
{
  "routing": {
    "skip_search": bool,
    "personal_search": bool,        # uploaded files
    "academic_search": bool,
    "discussion_search": bool,
    "widgets": {"weather": bool, "stock": bool, "calculation": bool}
  },
  "style": {
    "primary_type": Literal["general","academic_research","recent_news",
                            "weather","people","coding","recipe",
                            "translation","creative_writing",
                            "science_math","url_lookup"],
    "freshness": Literal["any","week","day"],
    "depth_hint": Literal["short","medium","deep"]
  },
  "standalone_followup": str,
  "detected_urls": list[str]   # regex pre-filled; LLM only refines
}
```

`style.primary_type` selects the composer template. `style.freshness` plumbs to SearxNG `time_range`. `detected_urls` is regex-prefilled (LLM-flagged URL detection is unreliable per Recon).

## A6. Citation validation — improve on Vane

Vane has **no post-hoc citation validation** — if the model emits `[42]` with 7 sources, it silently fails. Our `helpers/citations.py` will:

1. Build context block exactly like Vane: `<result index=N title=...>{content}</result>` so the citation index is implicit-but-stable.
2. Include explicit `do not CITE this as a source` instruction on `<widgets_result>` block.
3. **Post-hoc regex-scan `\[(\d+)\]`**; drop or snap-to-nearest-valid any out-of-range citation; log metric.
4. Build SourceRegistry exactly like Vane: ordered, URL-dedup, content-concat. Implement as a clean left-fold (Vane's version has a subtle dict/array index drift bug we won't inherit).

## A7. Scraper choice — Trafilatura in Phase 1

- Phase 1: **Trafilatura** (pure Python, ~80% real-world coverage, no Chromium dep).
- Phase 2: optional `playwright_fallback` config flag for JS-heavy sites.
- Removes ~300MB headless browser from plugin footprint.

## A8. Widget implementation specifics

- **widget_weather.py** — Nominatim → Open-Meteo, 24h hourly + 7d daily; param-extractor LLM **mandatory** (not optional).
- **widget_calc.py** — Use `asteval` (sandboxed, no eval, closer to mathjs behaviour than sympy).
- **widget_stock.py** — `yfinance` with **5-minute per-ticker chart cache** and **comparison cap = 2** (Vane allows 3 but Yahoo rate-limits hurt; up to 32 HTTP calls per query otherwise).
- All three: graceful degradation pattern — catch external-API errors, return `{type, llmContext:'Failed to fetch…', data:{error:'…'}}` instead of throwing.

## A9. SearxNG client hardening

Beyond Vane's bare port, add:

- `time_range` and `safesearch` query params (Vane omits both)
- Document Google Scholar engine often disabled by default in BYO-SearxNG guide
- Use repeated `?engines=` params (per spec) rather than comma-joined (Vane is fragile here)
- Pagination support behind a flag (Vane is page-1 only)

## A10. Streaming protocol & WebUI

- `api/search.py` returns **NDJSON-over-`text/event-stream`** matching Vane's wire format for ecosystem compatibility; envelopes: `init`, `sources`, `block`, `updateBlock`, `researchComplete`, `response`, `messageEnd`, `done`.
- WebUI panel must include a JSON-Patch applier (`fast-json-patch` JS lib) to handle `updateBlock` ops.
- Abort handling: poll `request.is_disconnected()` in FastAPI and tear down the session.
- Drop blocks JSON to a sidecar file under `<context>/fauxplexica/` ONLY if/when we want history-fidelity (Phase 2). Phase 1 accepts that reload shows markdown, not block stream.

## A11. New / changed `default_config.yaml` keys

Add:

- `context_budget_chars: 60000` — cap composer context to fit smaller local models
- `quality_max_iterations: 10` — override (Vane uses 25; we throttle)
- `scrape_extractor_concurrency: 3` — per-page semaphore for extractor LLM
- `stock_comparison_max: 2`
- `stock_cache_ttl_seconds: 300`
- `searxng.pagination_pages: 1`
- `searxng.time_range_default: any`
- `webui.scraper_fallback_playwright: false`
- `rerank.cosine_keep_threshold: 0.5`
- `rerank.cosine_dedup_threshold: 0.75`

## A12. Reggie's ReAct loop — improvements over Vane

When Reggie implements `helpers/researcher.py`:

- **Enforce `__reasoning_preamble` in code**, not just prompt. Drop non-preamble first tool calls. (Vane threatens but doesn't enforce.)
- Handle empty-tool-call iteration as implicit `done` (Vane does this; keep).
- **Use A0's native `thoughts` array** to surface reasoning; emit a `reasoning` block per iteration into the block stream.

## A13. Plugin directory tree — additions to §3 of PLAN_PHASE1

```
a0_fauxplexica/
├── helpers/
│   ├── researcher.py        (NEW)
│   ├── reranker.py          (NEW)
│   ├── picker.py            (NEW)
│   ├── extractor.py         (NEW)
│   ├── scraper.py           (NEW)
│   ├── blockstream.py       (NEW)
│   └── utils.py             (NEW)
├── prompts/
│   ├── researcher_speed.md         (NEW)
│   ├── researcher_balanced.md      (NEW)
│   ├── researcher_quality.md       (NEW)
│   ├── composer_weather.md         (NEW)
│   ├── composer_recipe.md          (NEW)
│   ├── composer_translation.md     (NEW)
│   ├── composer_creative.md        (NEW)
│   └── composer_science_math.md    (NEW)
```

Owner attribution updates:

- `helpers/researcher.py` → **Reggie**
- `helpers/reranker.py`, `picker.py`, `extractor.py`, `scraper.py` → **Searx** (extended scope)
- `helpers/blockstream.py` → **Orchy**
- `helpers/utils.py` → **Scaff** (small utility port; can be done at scaffold time)
- All new `prompts/researcher_*.md` → **Reggie**
- All new `prompts/composer_*.md` → **Compo**

## A14. Roster — final Wave 1 / Wave 2 spawn list

| Wave | Super | Profile | Spawn condition |
|---|---|---|---|
| 1a | Scaff | developer | Spawned ✅ |
| 1a | Recon | researcher | Spawned ✅ — Pass 1 delivered |
| 1b | Searx | developer | After Scaff signals scaffold-ready |
| 1b | Classy | developer | After Scaff signals scaffold-ready |
| 1b | Widge | developer | After Scaff signals scaffold-ready |
| 1b | Filey | developer | After Scaff signals scaffold-ready |
| 2 | Orchy | developer | After Searx + Classy each report M1-equivalent |
| 2 | Reggie | developer | After Searx (needs scraper/extractor) |
| 2 | Compo | developer | After Classy (needs unified taxonomy) |
| 3 | Citer | developer | After Compo |
| 3 | Profy | developer | After Compo prompts stable |
| 3 | APIs | developer | After Orchy |
| 4 | WebUI | developer | After APIs + Citer block-stream contract stable |
| Continuous | QA | developer | Spawn at Wave 2 start |
| Continuous | Docs | researcher | Spawn at Wave 2 start |

## A15. Out-of-scope confirmations

Re-confirmed Phase 2 deferred items (no change from PLAN_PHASE1 §5):

- Discover feed, autocomplete suggestions, image/video rendering, custom-agent builder, auth overlay, Tavily/Exa providers (stub interface only), Playwright scraper fallback, block-stream sidecar persistence for history fidelity, mobile UI polish.

---

*End of Amendments R1. Apply in conjunction with `PLAN_PHASE1.md`. Conflicts: this document wins.*
