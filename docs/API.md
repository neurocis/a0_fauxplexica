# A0_Fauxplexica API

Phase 1 API contract reflecting the current implementation in `api/search.py`, `api/providers.py`, and `helpers/orchestrator.py`.

## Public HTTP routes

All routes are mounted under the A0 plugin API path:

```
/api/plugins/a0_fauxplexica/*
```

### `POST /api/plugins/a0_fauxplexica/search`

Programmatic search endpoint. Thin wrapper around `helpers.orchestrator.run_fauxplexica_search`.

Request body:

```json
{
  "query": "What changed in Python 3.13?",
  "mode": "balanced",
  "chat_history": [],
  "enabled_sources": ["web", "academic"],
  "enabled_widgets": ["weather", "calculator", "stock"],
  "file_ids": [],
  "stream": true,
  "ctxid": "optional-a0-context-id"
}
```

Field notes:

- `query` is required.
- `mode` defaults to `balanced`. Allowed: `speed`, `balanced`, `quality`. Invalid values fall back to `balanced`.
- `chat_history` and `file_ids` must be arrays when provided.
- `enabled_sources` and `enabled_widgets` accept arrays of strings or objects mapping ids to booleans.
- `stream: true` returns NDJSON-over-SSE; `stream: false` returns a JSON answer.
- If `enabled_sources` is non-empty but `searxng_url` is not configured, the route returns a structured error `missing_searxng_url`.

Streaming response (`text/event-stream`, NDJSON line-per-event):

```text
{"type":"init","data":{"query":"...","mode":"balanced"}}
{"type":"block","data":{"type":"reasoning","data":{"text":"..."}}}
{"type":"updateBlock","data":{"id":"...","ops":[{"op":"replace","path":"/text","value":"..."}]}}
{"type":"researchComplete","data":{"sources":[...]}}
{"type":"response","data":{"answer":"..."}}
{"type":"messageEnd","data":{}}
{"type":"done","data":{}}
```

Event envelope types emitted by `helpers.blockstream.BlockStream`:

- `init`
- `block`
- `updateBlock`
- `researchComplete`
- `response`
- `messageEnd`
- `done`
- `error`

Non-streaming response (`application/json`):

```json
{
  "answer": "... [1]",
  "classification": {"routing": {"...": {}}, "style": {"primary_type": "general"}},
  "sources": [{"index": 1, "title": "Example", "url": "https://example.test", "snippet": "..."}],
  "citations": [],
  "widgets": [],
  "mode": "balanced",
  "blocks": [{"type": "text", "data": {"text": "..."}}]
}
```

Structured error response:

```json
{"ok": false, "error": {"code": "missing_query", "message": "Request field 'query' is required."}}
```

Known error codes:

- `missing_query` (HTTP 400)
- `invalid_request` (HTTP 400)
- `missing_searxng_url` (HTTP 400)
- `search_failed` (HTTP 500)

### `GET /api/plugins/a0_fauxplexica/providers`

Read-only provider/source/widget/mode/model-registry listing. Used by the WebUI to populate toggles and defaults.

Response:

```json
{
  "ok": true,
  "ctxid": null,
  "providers": [
    {"id": "searxng", "type": "search", "label": "SearxNG", "configured": true, "byo": true}
  ],
  "sources": [
    {"id": "web", "label": "Web", "enabled": true},
    {"id": "academic", "label": "Academic", "enabled": true},
    {"id": "discussions", "label": "Discussions", "enabled": false}
  ],
  "widgets": [
    {"id": "weather", "label": "Weather", "enabled": true},
    {"id": "calculator", "label": "Calculator", "enabled": true},
    {"id": "stock", "label": "Stock", "enabled": true}
  ],
  "modes": [
    {"id": "speed", "label": "Speed", "default": false},
    {"id": "balanced", "label": "Balanced", "default": true},
    {"id": "quality", "label": "Quality", "default": false}
  ],
  "model_registry": {
    "chat_providers": [],
    "embedding_providers": [],
    "presets": []
  },
  "limits": {
    "max_sources_per_query": 12,
    "context_budget_chars": 60000,
    "quality_max_iterations": 10
  }
}
```

### `GET /api/plugins/a0_fauxplexica/suggest`

Placeholder reserved for Phase 2 smart suggestions / autocomplete. Phase 1 callers must not depend on it.

## Helper import surfaces

Useful internal contracts:

| Module | Surface |
|---|---|
| `helpers.classifier` | `async classify(...) -> ClassifierOutput` |
| `helpers.searxng_client` | `SearxClient`, `SearxError` |
| `helpers.reranker` | `async rerank_results(query, results, embedder, keep_threshold=0.5, dedup_threshold=0.75, top_k=20)` |
| `helpers.picker` | `async pick_results(query, results, llm, max_picks=3)` |
| `helpers.scraper` | `async scrape_url(url, timeout=20, fallback_playwright=False)` |
| `helpers.extractor` | `async extract_facts(url, content, query, llm, semaphore=...)` |
| `helpers.researcher` | `async research(query, mode, chat_history, file_ids, ...)` |
| `helpers.composer` | `async compose_answer(query, classification, chat_history, search_findings, widget_outputs, mode, llm, config, ...)` |
| `helpers.citations` | `build_source_registry`, `validate_citations`, `extract_citation_indices`, `SourceRecord`, `CitationValidationResult` |
| `helpers.orchestrator` | `async run_fauxplexica_search(query, ..., block_stream=BlockStream())` |
| `helpers.blockstream` | `Block`, `BlockStream`, `emit`, `emit_block`, `update_block`, `close`, `all_blocks`, `events` |
| `helpers.uploads` | `async get_uploads_memory(...)`, `UploadsManager` |
| `helpers.widgets_registry` | `Widget`, `WidgetOutput`, `get_widgets()`, `async execute_all(...)` |
| `helpers.types` | shared dataclasses for search results and classifier output |
| `helpers.utils` | `split_text`, `cosine_similarity` |

## Tool surfaces

| Tool | Purpose |
|---|---|
| `tools.fauxplexica_search` | Top-level agentic search entrypoint. |
| `tools.fauxplexica_answer` | Compose final answer from collected sources. |
| `tools.fauxplexica_upload` | Ingest files into Fauxplexica upload RAG. |
| `tools.fauxplexica_uploads_search` | Search uploaded-file content. |
| `tools.widget_weather` | Weather widget implementation. |
| `tools.widget_calc` | Calculator widget implementation. |
| `tools.widget_stock` | Stock widget implementation. |

## Classifier contract

```json
{
  "routing": {
    "skip_search": false,
    "personal_search": false,
    "academic_search": false,
    "discussion_search": false,
    "widgets": {"weather": false, "stock": false, "calculation": false}
  },
  "style": {
    "primary_type": "general",
    "freshness": "any",
    "depth_hint": "medium"
  },
  "standalone_followup": "...",
  "detected_urls": []
}
```

`style.primary_type` selects the composer prompt family. `routing` controls tool/widget behavior.

## Citation contract

The source registry returned by `helpers.citations.build_source_registry` produces stable 1-based records with `index/title/url/snippet/source/score/metadata`. `validate_citations(answer, sources, policy=...)` returns a structured `CitationValidationResult` exposing valid/invalid/cited/uncited indices, a repaired answer, and the policy used. Phase 1 supports policies `keep`, `strip_invalid`, and `annotate_invalid`.

Duplicate URLs are dedupe-collapsed before assigning citation indices, preserving first-seen order.

## Stability note

The schemas above match the current `main` branch and are validated by the Python test suite (178 tests) and the WebUI Node tests.
