# A0_Fauxplexica API Draft

This is a draft contract for Phase 1 API and import surfaces. It documents current intent without claiming that all endpoints are fully integrated end-to-end.

## Public HTTP routes

### `POST /api/fauxplexica/search`

Main programmatic search endpoint, analogous to Vane's `/api/search`.

#### Request draft

```json
{
  "query": "What changed in Python 3.13?",
  "mode": "balanced",
  "sources": {
    "web": true,
    "academic": false,
    "discussions": false
  },
  "stream": true,
  "files": [],
  "context_id": "optional-a0-context-id"
}
```

Fields:

- `query` — required user query.
- `mode` — optional `speed`, `balanced`, or `quality`; defaults to config.
- `sources` — optional source-picker override.
- `stream` — when true, target transport is NDJSON over `text/event-stream` per Amendments R1.
- `files` — future/upload-aware references; actual file RAG uses the `_memory`-backed upload adapter.
- `context_id` — optional host context identifier for per-context upload namespaces/history.

#### Streaming response draft

Amendments R1 targets NDJSON envelopes compatible with Vane-like clients:

```json
{"type":"init","message_id":"..."}
{"type":"sources","sources":[...]}
{"type":"block","block":{"id":"...","type":"reasoning","content":"..."}}
{"type":"updateBlock","id":"...","ops":[{"op":"replace","path":"/content","value":"..."}]}
{"type":"researchComplete"}
{"type":"response","delta":"..."}
{"type":"messageEnd","message_id":"..."}
{"type":"done"}
```

Planned envelope types:

- `init`
- `sources`
- `block`
- `updateBlock`
- `researchComplete`
- `response`
- `messageEnd`
- `done`

Block/update payloads are owned by `helpers/blockstream.py` and the WebUI store.

#### Non-streaming response draft

For non-streaming clients, the target schema remains:

```json
{
  "answer": "... [1]",
  "citations": [
    {"index": 1, "url": "https://example.test", "title": "Example"}
  ],
  "sources": [
    {"title": "Example", "url": "https://example.test", "content": "..."}
  ],
  "query_type": "recent_news",
  "mode": "balanced"
}
```

### `GET /api/fauxplexica/providers`

Read-only provider/model listing shim over A0 `_model_config` concepts.

Draft response:

```json
{
  "providers": [
    {
      "id": "default",
      "name": "A0 default preset",
      "roles": ["classifier", "composer", "utility"]
    }
  ]
}
```

CRUD provider management is out of scope for Phase 1.

### `GET /api/fauxplexica/suggest`

Placeholder for Phase 2 smart suggestions/autocomplete. Do not depend on it for Phase 1.

## Helper import surfaces

Current helper modules are intended for internal plugin composition but are useful contracts for Wave 2 developers:

| Module | Surface |
|---|---|
| `helpers.classifier` | `async classify(query, chat_history, enabled_sources, enabled_widgets, llm)` |
| `helpers.searxng_client` | `SearxClient`, `SearxError` |
| `helpers.reranker` | `async rerank_results(query, results, embedder, keep_threshold=0.5, dedup_threshold=0.75, top_k=20)` |
| `helpers.picker` | `async pick_results(query, results, llm, max_picks=3)` |
| `helpers.scraper` | `async scrape_url(url, timeout=20, fallback_playwright=False)` |
| `helpers.extractor` | `async extract_facts(url, content, query, llm, semaphore=...)` |
| `helpers.uploads` | `async get_uploads_memory(...)`, `UploadsManager` |
| `helpers.widgets_registry` | `Widget`, `WidgetOutput`, `get_widgets()`, `async execute_all(...)` |
| `helpers.types` | shared dataclasses for search results and classifier output |
| `helpers.utils` | `split_text`, `cosine_similarity` |

Several Wave 2 surfaces (`helpers.orchestrator`, `helpers.researcher`, `helpers.composer`, `helpers.citations`, `helpers.blockstream`) currently define architectural ownership and contracts but require final owner outputs before this API document can be marked stable.

## Tool surfaces

Agent-facing tools currently visible:

| Tool module | Purpose |
|---|---|
| `tools.fauxplexica_search` | Top-level agentic search entrypoint. |
| `tools.fauxplexica_answer` | Compose final answer from collected sources. |
| `tools.fauxplexica_upload` | Ingest files into Fauxplexica upload RAG. |
| `tools.fauxplexica_uploads_search` | Search uploaded-file content. |
| `tools.widget_weather` | Weather widget implementation. |
| `tools.widget_calc` | Calculator widget implementation. |
| `tools.widget_stock` | Stock widget implementation. |

## Classifier contract

The unified classifier output combines routing and style axes:

```json
{
  "routing": {
    "skip_search": false,
    "personal_search": false,
    "academic_search": false,
    "discussion_search": false,
    "widgets": {
      "weather": false,
      "stock": false,
      "calculation": false
    }
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

`style.primary_type` selects composer prompt family. `routing` determines tool/widget behavior.

## Citation contract

The composer receives an ordered source context:

```xml
<search_results>
  <result index="1" title="...">...</result>
  <result index="2" title="...">...</result>
</search_results>
```

Inline citations such as `[1]` refer to the corresponding source registry entry. A0_Fauxplexica intends to improve on Vane by validating out-of-range citations after composition.

## Stability note

This document is a draft until Reggie, Compo, Orchy, Citer, APIs, and WebUI owners finalize their Wave 2+ contracts.
