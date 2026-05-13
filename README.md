# A0_Fauxplexica

<p align="center">
  <img src="webui/thumbnail.jpg" alt="A0_Fauxplexica" width="640" />
</p>

<p align="center">
  <a href="#license"><img src="https://img.shields.io/badge/license-MIT-blue" alt="license"></a>
  <img src="https://img.shields.io/badge/status-Phase%201%20complete-brightgreen" alt="status">
  <img src="https://img.shields.io/badge/version-0.1.0-lightgrey" alt="version">
  <img src="https://img.shields.io/badge/Agent%20Zero-plugin-orange" alt="agent zero plugin">
  <img src="https://img.shields.io/badge/tests-183%20passing-success" alt="tests">
  <img src="https://img.shields.io/badge/SearxNG-BYO-informational" alt="searxng byo">
</p>

> **A Perplexity / Vane-style AI answering engine, rebuilt as a native [Agent Zero](https://github.com/agent0ai) plugin.**
>
> Bring your own SearxNG, plug in any OpenAI-compatible LLM and embedding endpoint, and get an answer engine that **classifies → researches → composes → cites** — fully visible, fully scriptable, fully agentic.

---

## Table of contents

- [Why A0_Fauxplexica?](#why-a0_fauxplexica)
- [Highlights](#highlights)
- [Architecture at a glance](#architecture-at-a-glance)
- [Search modes](#search-modes)
- [Two ways to use it](#two-ways-to-use-it)
  - [1. From any Agent Zero chat (tool call)](#1-from-any-agent-zero-chat-tool-call)
  - [2. From the Deep Research sidebar (WebUI)](#2-from-the-deep-research-sidebar-webui)
- [Installation](#installation)
- [Configuration](#configuration)
- [HTTP API](#http-api)
- [Citations contract](#citations-contract)
- [Widgets](#widgets)
- [Uploads / File Q&A](#uploads--file-qa)
- [Chat profile](#chat-profile)
- [Project layout](#project-layout)
- [Testing](#testing)
  - [Live integration tests](#live-integration-tests)
- [Phase 1 status](#phase-1-status)
- [Deferred to Phase 2+](#deferred-to-phase-2)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Why A0_Fauxplexica?

Perplexity and Vane proved that a small set of well-orchestrated stages — classify the question, search in parallel, synthesize with citations — produces dramatically better answers than "chatbot + raw web tool".

**A0_Fauxplexica brings that pipeline natively into Agent Zero, so every agent in your hierarchy can do real research.** It does not try to be a SaaS clone — there is no proprietary search index, no rented LLM, no telemetry. You provide:

- a SearxNG instance (any version, anywhere reachable),
- a chat LLM (any model your Agent Zero can call),
- and *optionally* an OpenAI-compatible embeddings endpoint for semantic reranking.

It then provides:

- a deterministic, inspectable classify → research → compose → cite pipeline,
- a `fauxplexica_search` / `fauxplexica_answer` tool that any A0 agent can call,
- a dedicated `A0_Fauxplexica` chat profile,
- a Vane-compatible typed block stream for live UI rendering,
- a Perplexity-style WebUI panel with mode picker, source toggles, widgets, and inline-bracket citations,
- and a sidebar **Deep Research** launcher that dispatches a tool call straight into your current chat so the mechanics happen *in front of you*.

## Highlights

- 🔭 **Three depth modes** — Speed, Balanced, Quality — with iteration and concurrency caps for cost control.
- 🧭 **Style-aware composer** — academic, news, weather, people, coding, recipe, translation, creative, science/math, URL lookup, general.
- 🪄 **Inline `[1]`/`[2]` citations** validated post-hoc against a 1-based source registry, with `keep` / `strip_invalid` / `annotate_invalid` policies.
- 🧠 **Embedding reranker** with cosine `keep_threshold` and `dedup_threshold`, plus graceful all-sim-1.0 fallback when no embedder is configured.
- 🛰️ **Vane-compatible typed block stream** — `init`, `block`, `updateBlock` (JSON-Patch), `researchComplete`, `response`, `messageEnd`, `done`, `error`.
- 🧰 **Widgets** — weather (Open-Meteo + Nominatim), calculator (`asteval` sandbox), stock (yfinance, 5-min cache). All dependencies are optional and degrade gracefully.
- 📎 **Uploads / RAG** — PDF, TXT, MD, CSV, DOCX ingested via Agent Zero's `_memory` infrastructure, scoped to the active chat.
- 🪟 **Agentic, not just UI** — `fauxplexica_search` and `fauxplexica_answer` are normal A0 tools usable from any chat profile, superordinate, or skill.
- 🛠️ **No frontend build step** — pure vanilla-JS WebUI in `webui/`.
- 🆓 **MIT licensed** and free of vendor lock-in.

## Architecture at a glance

```text
                ┌──────────────────────────────────────────┐
  user query →  │  classify (routing + style)              │
                └──────────────────┬───────────────────────┘
                                   │
           ┌───────────────────────┴───────────────────────┐
           │                                               │
  ┌────────▼─────────┐                          ┌──────────▼──────────┐
  │ widgets (parallel)│                          │ research (parallel) │
  │  weather/calc/    │                          │ search → rerank →   │
  │  stock            │                          │ (quality: pick +    │
  │                   │                          │  scrape + extract)  │
  └────────┬──────────┘                          └──────────┬──────────┘
           │                                               │
           └──────────────────────┬────────────────────────┘
                                  │
                       ┌──────────▼──────────┐
                       │   compose answer    │
                       │   (style-specific)  │
                       └──────────┬──────────┘
                                  │
                       ┌──────────▼──────────┐
                       │ validate citations  │
                       │ + source registry   │
                       └──────────┬──────────┘
                                  │
                       ┌──────────▼──────────┐
                       │  typed block stream │
                       │  → WebUI / agent    │
                       └─────────────────────┘
```

Full Vane → A0 mapping (Next.js → A0 plugin, `/api/search` → `/api/plugins/a0_fauxplexica/search`, SearchAgent → `helpers/orchestrator.py`, …) is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Search modes

| Mode       | Behavior                                                                                          | Iteration cap                                          |
|------------|---------------------------------------------------------------------------------------------------|--------------------------------------------------------|
| `speed`    | Shallow research, **no scraping**, fastest useful answer with citations.                          | small                                                  |
| `balanced` | Parallel research with rerank, optional widgets, good citation coverage.                          | moderate                                               |
| `quality`  | ReAct loop with picker → Trafilatura scrape → chunked extractor and careful synthesis.            | `quality_max_iterations` (10 default; Vane uses 25).   |

## Two ways to use it

### 1. From any Agent Zero chat (tool call)

Any A0 agent — including superordinates, skills, and your own chat — can invoke Fauxplexica as a normal tool:

```json
{
  "tool_name": "fauxplexica_search",
  "tool_args": {
    "query": "Compare current quantum-safe key exchange algorithms and standardization status",
    "mode": "quality",
    "sources": ["web", "academic"],
    "widgets": [],
    "max_sources": 10
  }
}
```

Result shape:

```json
{
  "query": "…",
  "mode": "quality",
  "answer": "…with inline [1][2] citations…",
  "sources": [
    {"index": 1, "title": "…", "url": "…", "snippet": "…", "source": "web", "score": 0.91}
  ],
  "widgets": [],
  "classification": {"style": {"primary_type": "academic_research"}}
}
```

`fauxplexica_answer` is a convenience alias of the same tool, provided so prompts can use whichever name reads better.

### 2. From the Deep Research sidebar (WebUI)

Click the **🔭 Deep Research** icon in the A0 left sidebar to open a modal that:

- lets you pick mode, sources, and widgets,
- shows a live JSON preview of the exact `fauxplexica_search` tool call,
- dispatches that tool call into your *currently open chat* (no parallel UI pipeline),
- closes the modal so you see the search execute live in the conversation — tool call → retrieval → citations → composed answer.

This design intentionally avoids a second "hidden" UI flow. **The mechanics are always visible in your chat.**

## Installation

A0_Fauxplexica is an Agent Zero plugin. Install it into the user plugins directory of your A0 instance:

```bash
git clone https://github.com/neurocis/a0_fauxplexica.git /a0/usr/plugins/a0_fauxplexica
```

Then:

1. **Restart the A0 backend** so plugin discovery picks it up.
2. Open **Plugins → A0_Fauxplexica → Settings** and set `searxng_url` (required for web/academic/social sources).
3. (Optional) Configure embeddings under `embeddings.*` for semantic reranking.
4. (Optional) Install the Python extras for full widget functionality:
   ```bash
   pip install -r /a0/usr/plugins/a0_fauxplexica/requirements.txt
   ```
   Missing dependencies do **not** crash the search pipeline — each widget gracefully degrades.

### SearxNG requirements

The plugin talks to SearxNG over JSON. Your SearxNG `settings.yml` must allow it:

```yaml
search:
  formats:
    - html
    - json
```

Then restart SearxNG so the config is picked up. Without `json` in `search.formats`, SearxNG returns `403 Forbidden` for the plugin's JSON requests.

## Configuration

Full reference: [`docs/CONFIG.md`](docs/CONFIG.md).

Key settings (from `default_config.yaml` and the Plugin Settings UI):

| Key                                          | Purpose                                                            |
|----------------------------------------------|--------------------------------------------------------------------|
| `searxng_url`                                | **Required.** Base URL of your SearxNG instance.                   |
| `default_mode`                               | `speed` \| `balanced` \| `quality`.                                |
| `sources.web` / `.academic` / `.discussions` | Source category toggles.                                           |
| `widgets_enabled.weather/.calculator/.stock` | Built-in widget toggles.                                           |
| `max_sources_per_query`                      | Hard cap after dedup/trust scoring.                                |
| `citation_style`                             | `inline_bracket` \| `footnote`.                                    |
| `context_budget_chars`                       | Cap composer context (fits smaller local models).                  |
| `quality_max_iterations`                     | Throttle the quality ReAct loop (default 10).                      |
| `scrape_extractor_concurrency`               | Per-page extractor LLM concurrency cap.                            |
| `rerank.cosine_keep_threshold`               | Embedding rerank keep cutoff.                                      |
| `rerank.cosine_dedup_threshold`              | Embedding rerank near-duplicate cutoff.                            |
| `embeddings.base_url`                        | OpenAI-compatible `/v1` endpoint (optional).                       |
| `embeddings.api_key`                         | Optional API key (some local gateways need none).                  |
| `embeddings.model`                           | e.g. `text-embedding-3-small`, `nomic-embed-text`.                 |
| `searxng.pagination_pages`                   | SearxNG pagination depth.                                          |
| `searxng.time_range_default`                 | Default time range filter.                                         |
| `webui.scraper_fallback_playwright`          | Phase 2 flag (off in Phase 1).                                     |

## HTTP API

Full contract: [`docs/API.md`](docs/API.md).

- `POST /api/plugins/a0_fauxplexica/search` — programmatic search. Supports `stream: true` (NDJSON-over-SSE typed blocks) and `stream: false` (single JSON answer + sources).
- `GET  /api/plugins/a0_fauxplexica/providers` — read-only listing of modes, sources, widgets, limits, and registered models.
- `GET  /api/plugins/a0_fauxplexica/suggest` — Phase 2 placeholder route reserved for autocomplete.

Minimal example:

```bash
curl -s -X POST http://localhost:5000/api/plugins/a0_fauxplexica/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "What is the EU AI Act?",
    "mode": "balanced",
    "enabled_sources": ["web"],
    "stream": false
  }'
```

Streaming envelope examples:

```text
{"type":"init","data":{"query":"…","mode":"balanced"}}
{"type":"block","block":{"id":"b1","type":"searching","data":{…}}}
{"type":"block","block":{"id":"b2","type":"search_results","data":{…}}}
{"type":"researchComplete","data":{"sources":[…]}}
{"type":"block","block":{"id":"b3","type":"text","data":{"text":"… [1] …"}}}
{"type":"updateBlock","blockId":"b3","patch":[{"op":"replace","path":"/data/text","value":"… [1][2] …"}]}
{"type":"response","data":{"answer":"… [1][2] …"}}
{"type":"messageEnd","data":{}}
{"type":"done","data":{}}
```

## Citations contract

- Inline 1-based bracket citations: `[1]`, `[2]`, `[1][3]`.
- Source registry normalizes results to `{index, title, url, snippet, source, score}`.
- Post-hoc validator detects:
  - out-of-range citation indices (configurable: `keep`, `strip_invalid`, `annotate_invalid`),
  - uncited sources (surfaced in WebUI sidebar),
  - duplicate citations.
- The WebUI links each `[n]` to a rich citation card with title, URL, snippet, source, and score.

## Widgets

| Widget     | Backend                | Notes                                                                                                |
|------------|------------------------|------------------------------------------------------------------------------------------------------|
| Weather    | Nominatim + Open-Meteo | Geocode → forecast; gracefully fails if `httpx` is missing.                                          |
| Calculator | `asteval` sandbox      | No raw `eval`; gracefully fails if `asteval` is missing.                                             |
| Stock      | `yfinance`             | 5-minute per-ticker cache; comparison capped (`stock_comparison_max`); gracefully fails if missing.  |

Disabled widgets are **never imported**, so missing optional deps cannot affect a search that doesn't use them.

## Uploads / File Q&A

Uploads reuse Agent Zero's `_memory` infrastructure via `helpers/uploads.py`:

- Supported: PDF, TXT, MD, CSV, DOCX.
- Scope: per-chat context.
- Tools: `fauxplexica_upload` (ingest) and `fauxplexica_uploads_search` (RAG query).

Multimodal / image parsing is intentionally deferred to Phase 2.

## Chat profile

The `A0_Fauxplexica` profile is shipped both at project scope (`.a0proj/`) and at plugin scope (`agents/fauxplexica/`).

- Key: `fauxplexica`
- Display name: `A0_Fauxplexica`
- Base profile: `developer`
- Defaults: `mode: balanced`, `citation_style: inline_bracket`, BYO SearxNG required, rich sidebar citations.
- Single connection definition per chat context.
- Preferred preset: `Fauxplexica Research` (strong chat model + utility classifier + optional local embeddings).

Detailed contract: [`PROFY_STATUS.md`](PROFY_STATUS.md).

## Project layout

```text
a0_fauxplexica/
├── agents/fauxplexica/         # plugin-distributed chat profile
├── api/                        # search, providers, suggest routes
├── docs/                       # ARCHITECTURE, API, CONFIG, INTEGRATION_TESTS
├── extensions/
│   ├── python/                 # message-loop + monologue extensions
│   └── webui/                  # sidebar Deep Research launcher
├── helpers/                    # pipeline: classifier, researcher, composer, ...
├── prompts/                    # classifier + researcher + composer prompts
├── tests/                      # pytest suite + WebUI tests + integration tests
├── tools/                      # fauxplexica_search / answer / upload / widgets
├── webui/                      # vanilla-JS modal + Alpine store
├── default_config.yaml         # plugin defaults
├── plugin.yaml                 # plugin manifest
├── requirements.txt            # optional widget deps
├── LICENSE                     # MIT
└── README.md                   # you are here
```

## Testing

From the repository root:

```bash
# Static import check
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests api

# Full Python suite (skips live integration unless SEARXNG_URL is set)
PYTHONPATH=/a0/plugins pytest -q tests --ignore=tests/integration
# → 183 passed, 1 skipped

# WebUI store + Recon R1 parser tests
node tests/webui/test_fauxplexica_store.mjs
# → WEBUI_STORE_TESTS_OK
# → WEBUI_RECON_R1_PARSER_OK
```

### Live integration tests

```bash
# Reranker smoke against real SearxNG (deterministic bag-of-words fallback)
SEARXNG_URL=http://your-searxng:8080 \
PYTHONPATH=/a0/plugins pytest -q tests/integration -m integration

# Reranker smoke with a real OpenAI-compatible embedding endpoint
SEARXNG_URL=http://your-searxng:8080 \
EMBEDDING_BASE_URL=https://api.openai.com/v1 \
EMBEDDING_API_KEY=sk-... \
EMBEDDING_MODEL=text-embedding-3-small \
PYTHONPATH=/a0/plugins pytest -q tests/integration -m integration
```

See [`docs/INTEGRATION_TESTS.md`](docs/INTEGRATION_TESTS.md) for the full env matrix.

## Phase 1 status

- ✅ Plugin scaffold + validators
- ✅ Vane-mapped pipeline (classify → research → compose → cite)
- ✅ Speed / Balanced / Quality modes
- ✅ Web / academic / discussions source controls
- ✅ Widgets (weather / calculator / stock) with graceful dependency degradation
- ✅ Uploads / RAG via `_memory` adapter
- ✅ Source registry + post-hoc citation validation
- ✅ Vane-compatible typed block stream (`block` / `updateBlock` / `researchComplete` / …)
- ✅ Vanilla-JS WebUI panel + Deep Research sidebar launcher
- ✅ `fauxplexica_search` / `fauxplexica_answer` agentic tools
- ✅ Dedicated `A0_Fauxplexica` chat profile
- ✅ API-configurable reranker integration smoke
- ✅ Live-validated against real SearxNG
- ✅ Phase 1 signoff in [`PHASE1_SIGNOFF.md`](PHASE1_SIGNOFF.md)

## Deferred to Phase 2+

- Discover feed
- Smart suggestions / autocomplete (route placeholder only)
- Image / video search rendering
- Custom-agent builder
- Authentication overlay
- Tavily / Exa providers beyond stubs
- Playwright scraper fallback for JS-heavy sites
- Block-stream sidecar persistence for full history reloads
- Mobile WebUI polish
- Multi-tenant hardening

## Contributing

Issues and pull requests are welcome at <https://github.com/neurocis/a0_fauxplexica>.

Ground rules:

- Keep the plugin self-contained — no new top-level Agent Zero dependencies without discussion.
- Maintain the typed block stream contract; new envelope types must be additive.
- Add tests under `tests/` (and `tests/integration/` for anything touching real SearxNG / embeddings).
- Run the full local test commands above before opening a PR.
- Commits should include `Co-authored-by:` lines where appropriate.

## License

[MIT](./LICENSE) © neurocis and contributors.

## Acknowledgements

- **[Agent Zero](https://github.com/agent0ai)** — the agentic harness that makes this plugin possible.
- **[Perplexity](https://www.perplexity.ai/)** — for proving that classify → research → compose → cite is the right shape for a modern answer engine.
- **[Vane](https://github.com/ItzCrazyKns)** — for an open, hackable reference implementation of that pipeline.
- **[SearxNG](https://github.com/searxng/searxng)** — for being a meta-search engine that respects the operator.
- **[Trafilatura](https://github.com/adbar/trafilatura)**, **[asteval](https://github.com/lmfit/asteval)**, **[yfinance](https://github.com/ranaroussi/yfinance)**, **[Open-Meteo](https://open-meteo.com/)**, **[Nominatim](https://nominatim.org/)** — for the well-behaved building blocks Fauxplexica relies on.

> *Fauxplexica* — because it's shamelessly Perplexity-shaped, gloriously yours.
