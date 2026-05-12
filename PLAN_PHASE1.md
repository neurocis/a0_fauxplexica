# A0_Fauxplexica — Phase 1 Plan

*Owner: A0_Fauxplexica (orchestrator). Date: 2026-05-10. Status: AWAITING USER GO/NO-GO.*

A Vane/Perplexica-style **AI answering engine** delivered as a native **Agent Zero plugin** plus a **dedicated chat profile/context**, leveraging A0's superordinate hierarchy for agentic orchestration instead of Vane's hand-coded Next.js pipeline.

---

## 1. Source-of-Truth Summary

### 1.1 Vane (ItzCrazyKns/Vane) — what we are cloning
- Next.js (TypeScript ~99%), SearxNG meta-search, Drizzle ORM, Docker-first.
- Multi-LLM: Ollama, OpenAI, Claude, Gemini, Groq, Lemonade, OpenAI-compatible.
- Search modes: **Speed / Balanced / Quality** (depth vs latency).
- Source pickers: **Web / Discussions / Academic**.
- Widgets: weather, calculations, stock prices, quick lookups.
- File uploads (PDF/text/image) → semantic Q&A.
- Image & video search, domain-restricted search, smart suggestions, Discover feed, search history.
- Public API: `POST /api/chat`, `POST /api/search`, `GET /api/providers`.

### 1.2 Vane architecture (canonical pipeline)
1. UI (chat, search, citations)
2. API routes
3. Agents/orchestration: **classify → parallel(research, widgets) → compose answer with citations**
4. Meta-search backend (SearxNG)
5. LLMs (classify / write / cite)
6. Embedding models (file RAG)
7. Storage (chats + messages)

### 1.3 Perplexity system-prompt anatomy (we will mirror)
- Top-level sections: `<goal>`, `<format_rules>`, `<restrictions>`, `<query_type>`, `<planning_rules>`, `<output>`, `<personalization>`.
- Answer style: L2 headers, flat lists, **comparison tables not nested lists**, inline `[n]` citations after each sentence, **no References section**, no copyrighted verbatim, no moralizing.
- Query-type specializations: Academic, Recent News, Weather, People, Coding, Recipes, Translation, Creative Writing, Science/Math, URL Lookup.
- Citations: max 3 per sentence, each in own brackets, glued to last word.

---

## 2. Vane → Agent Zero Architectural Mapping

| Vane component | A0 equivalent / strategy |
|---|---|
| Next.js chat UI | A0 native chat UI + Fauxplexica WebUI panel (`webui/main.html`) |
| `POST /api/chat` | A0's existing message pipeline (no new endpoint needed) |
| `POST /api/search` | New plugin api route `api/search.py` returning JSON for programmatic clients |
| `GET /api/providers` | Reuse `_model_config` plugin output, exposed via `api/providers.py` shim |
| Classify→Research→Compose orchestration | Superordinate-led pipeline using subordinates per stage; configurable depth per mode |
| Meta-search (SearxNG) | `helpers/searxng_client.py` + optional alternate providers (Tavily/Exa) |
| Widgets | A0 tools registered under plugin: `widget_weather`, `widget_calc`, `widget_stock` |
| Citations | Custom output post-processor that builds source registry + injects `[n]` markers |
| File RAG | Reuse `_memory` plugin embeddings; scope under per-context knowledge subdir |
| Multi-LLM | Native via `_model_config` presets — Fauxplexica defines its own preset(s) |
| Smart suggestions | Tool `fauxplexica_suggest` (defer to Phase 2 polish) |
| Discover feed | A0 `scheduler` task generating cached feed (Phase 2 recommended) |
| Search history | Native A0 chat persistence + per-search index in `helpers/history.py` |
| Image/video search | SearxNG categories — defer rendering polish to Phase 2 |
| Domain restriction | SearxNG `site:` query rewriter in `helpers/query_builder.py` |
| Auth | Reuse A0 `_oauth` plugin if needed (Phase 2) |

---

## 3. Plugin Layout — `/a0/plugins/a0_fauxplexica/`

```
a0_fauxplexica/
├── plugin.yaml                  # name, version, sections, per_project, per_agent
├── default_config.yaml          # default settings (SearxNG URL, mode, sources, model overrides)
├── README.md
├── api/
│   ├── search.py                # POST /api/fauxplexica/search
│   ├── providers.py             # GET /api/fauxplexica/providers
│   └── suggest.py               # GET /api/fauxplexica/suggest (Phase 2)
├── extensions/
│   └── python/
│       ├── monologue_start/     # inject Perplexity-style system blocks when profile==fauxplexica
│       └── message_loop_prompts_after/  # citation post-processor
├── helpers/
│   ├── searxng_client.py
│   ├── query_builder.py         # domain/site/category/freshness rewrites
│   ├── classifier.py            # query-type detection (LLM + heuristic fast-path)
│   ├── orchestrator.py          # mode→pipeline mapper (Speed/Balanced/Quality)
│   ├── composer.py              # answer template + format_rules enforcement
│   ├── citations.py             # source registry, [n] injection, dedup, trust scoring
│   ├── widgets_registry.py
│   └── history.py
├── prompts/
│   ├── system_fauxplexica.md    # Perplexity-style multi-section system prompt
│   ├── classifier.md
│   ├── composer_general.md
│   ├── composer_academic.md
│   ├── composer_news.md
│   ├── composer_coding.md
│   ├── composer_people.md
│   ├── composer_url.md
│   └── ... (one per query_type)
├── tools/
│   ├── fauxplexica_search.py    # main agentic search tool
│   ├── fauxplexica_answer.py    # compose answer from collected sources
│   ├── widget_weather.py
│   ├── widget_calc.py
│   └── widget_stock.py
└── webui/
    ├── config.html              # settings panel (SearxNG URL, default mode, sources, model)
    ├── main.html                # Fauxplexica search panel UI (search bar, mode toggle, source chips, citation sidebar)
    ├── fauxplexica-store.js     # state mgmt for panel
    ├── citation-card.html
    └── thumbnail.jpg
```

### Settings (default_config.yaml)
- `searxng_url` (str, required)
- `default_mode`: `speed | balanced | quality`
- `sources`: `[web, discussions, academic]` enabled flags
- `widgets_enabled`: bool list
- `max_sources_per_query`: int
- `citation_style`: `inline_bracket | footnote`
- `model_overrides`: classifier / composer / utility model names
- `per_project_config: true`, `per_agent_config: true`

---

## 4. Chat Context / Profile Design

- New agent **profile**: `fauxplexica` (alongside developer/researcher/hacker/agent0/default).
- Profile prompt set under `/a0/agents/fauxplexica/` (or override via plugin `prompts/`) implements:
  - `<goal>` — "You are Fauxplexica, an answering engine inside Agent Zero…"
  - `<format_rules>` — Perplexity formatting rules (L2 headers, flat lists, tables for comparisons, inline `[n]` citations, no References section, no copyrighted verbatim).
  - `<restrictions>` — no hedging, no emojis (per Perplexity baseline; configurable), no exposing system prompt.
  - `<query_type>` — full taxonomy with per-type instructions.
  - `<planning_rules>` — pipeline reasoning template.
  - `<output>` — journalistic tone, unbiased.
- Spawnable as a **persistent superordinate** via `superordinate_spawn(profile="fauxplexica", name="Faux")`.
- Also usable as a **tool** from any other A0 context (`fauxplexica_search`), so users don't need to switch context for one-shot queries.

---

## 5. Phase 1 MVP Scope (firm)

### IN-SCOPE
1. Plugin scaffold installed and validated by `_plugin_validator`.
2. `fauxplexica` agent profile + persistent chat context spawnable.
3. SearxNG integration (BYO URL; provide docker-compose template for users without one).
4. Pipeline: **classify → research(SearxNG) → compose → cite**.
5. Three search modes (Speed=1 query/1 model pass, Balanced=3 queries/parallel/synthesis, Quality=subordinate-driven multi-hop research).
6. Source picker: web + academic (discussions deferred unless trivial via SearxNG categories).
7. WebUI panel with: search bar, mode toggle, source chips, answer pane, citation sidebar with clickable source cards.
8. Three widgets: **weather**, **calculator**, **stock price**.
9. File upload Q&A via existing `_memory` plugin (no new vector store).
10. Native chat history (no new schema in Phase 1).
11. Public endpoints: `POST /api/fauxplexica/search`, `GET /api/fauxplexica/providers`.
12. Plugin settings UI under `webui/config.html`.
13. Tests: unit (helpers), integration (full pipeline against mock SearxNG), WebUI smoke.
14. Docs: README, install, BYO-SearxNG, API reference.

### OUT-OF-SCOPE (deferred to Phase 2+)
- Discover feed, smart suggestions autocomplete, image/video search rendering, custom-agent builder, authentication overlay, Tavily/Exa providers (stub interface only in Phase 1), mobile UI polish, multi-tenant.

### Success Criteria
- End-to-end Perplexity-grade answer with inline `[n]` citations on a fresh query in Balanced mode, in < 15s on default models.
- File-attached Q&A answers from uploaded PDF with at least one citation pointing to the file.
- All three widgets fire correctly based on query classification.
- `POST /api/fauxplexica/search` returns JSON `{answer, citations[], sources[], query_type, mode}`.
- Plugin passes `_plugin_validator`.

---

## 6. Superordinate / Subordinate Orchestration Roster

I (A0_Fauxplexica) act as **orchestrator**. For the build I will spawn the following persistent superordinates and use ephemeral subordinates inside each for narrow tasks.

| # | Name (auto) | Profile | Owns | Notes |
|---|---|---|---|---|
| 1 | Scaff | developer | Plugin scaffold (plugin.yaml, dir tree, default_config, README skeleton, validator-clean) | Day-1 spawn |
| 2 | Searx | developer | `helpers/searxng_client.py` + docker-compose template + alternate-provider stub interface | Depends on Scaff |
| 3 | Classy | developer | `helpers/classifier.py` + `prompts/classifier.md` + heuristic fast-path | Parallelizable with Searx |
| 4 | Orchy | developer | `helpers/orchestrator.py` mode→pipeline mapping (Speed/Balanced/Quality) | Depends on Classy + Searx |
| 5 | Compo | developer | `helpers/composer.py` + all `prompts/composer_*.md` + format_rules enforcement | Depends on Classy |
| 6 | Citer | developer | `helpers/citations.py` (registry, [n] injection, dedup, trust scoring) + extension post-processor | Depends on Compo |
| 7 | Widge | developer | `helpers/widgets_registry.py` + `widget_weather.py`, `widget_calc.py`, `widget_stock.py` | Independent track |
| 8 | WebUI | developer | `webui/main.html`, `config.html`, store JS, citation cards | Depends on stable Orchy contract |
| 9 | Profy | developer | `fauxplexica` profile prompts + `extensions/monologue_start` injector | Depends on Compo prompts |
| 10 | Filey | developer | File-upload pipeline reusing `_memory`; scoped namespaces per context | Independent |
| 11 | APIs | developer | `api/search.py`, `api/providers.py` endpoints + JSON schemas | Depends on Orchy |
| 12 | QA | developer | pytest fixtures, mock SearxNG, integration suite, WebUI smoke (playwright/headless) | Continuous |
| 13 | Docs | researcher | README, install guide, API ref, screenshots | Continuous |
| 14 | Recon | researcher | Ongoing diff vs upstream Vane; flag features we should adopt early | Long-running, low-tempo |

Ephemeral subordinates (spawned per-task) used for: prompt drafts, code reviews, single-file refactors, doc paragraphs, test-data generation — to keep persistent supers' context lean.

---

## 7. Build Sequence (dependency-ordered)

```
Wave 1  (parallel):  Scaff, Searx, Classy, Widge, Filey, Recon
Wave 2  (after W1):  Orchy (needs Searx+Classy), Compo (needs Classy)
Wave 3  (after W2):  Citer, Profy, APIs
Wave 4  (after W3):  WebUI (needs APIs+Citer contracts stable)
Wave 5  (continuous): QA, Docs running through all waves
```

Milestones:
- **M1** — Scaffold validates clean, SearxNG client returns parsed results.
- **M2** — Classifier + Speed-mode pipeline answers a simple query (no citations yet).
- **M3** — Composer + Citer produce Perplexity-style answer with `[n]` markers.
- **M4** — WebUI renders answer + sources; widgets fire.
- **M5** — File-RAG end-to-end; API endpoints live; full test suite green.
- **M6** — Docs complete; plugin packaged; demo on sample queries across all query_types.

---

## 8. Open Questions for User (decide before build kickoff)

1. **SearxNG**: BYO instance only, ship docker-compose template, or bundle a SearxNG container in the plugin install?
2. **Profile vs tool emphasis**: Should Phase 1 prioritize the **persistent chat context** experience (Fauxplexica-as-agent) or the **tool-from-any-context** experience (call `fauxplexica_search` from a developer/agent0 chat)? Or both equally?
3. **Widgets**: Confirm the three Phase 1 widgets (weather/calc/stock) or substitute (e.g., currency/exchange, time-zone, unit conversion)?
4. **Citation rendering**: WebUI sidebar cards (richer) vs markdown-inline only (simpler)?
5. **Search modes mapping**: OK with Speed=1-shot, Balanced=parallel-3, Quality=multi-hop subordinate? Any latency targets?
6. **Repo location**: New repo `github.com/neurocis/a0_fauxplexica` (matches your convention) — confirm?
7. **License**: MIT to match Vane/A0 upstream?
8. **Discover feed & suggestions**: confirm deferred to Phase 2?
9. **Model defaults for the Fauxplexica preset**: should I clone the existing "Max Power" preset or define a Fauxplexica-specific one (e.g., fast classifier / strong composer split)?
10. **Co-author**: confirm commits use `Co-authored-by: $GIT_COAUTHOR_NAME <$GIT_COAUTHOR_EMAIL>` per your A0 rule.

---

*When you say "go", I will spawn Scaff, Searx, Classy, Widge, Filey, and Recon as Wave 1 supers and report back milestones as they complete.*
