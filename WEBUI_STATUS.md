# WebUI Status — A0_Fauxplexica Phase 1

Status: **implemented coordinator-led** because the WebUI worker (`LKLd8hXw`) had no persistent chat data on disk and was retired before it could start.

## Files updated

- `/a0/plugins/a0_fauxplexica/webui/main.html`
- `/a0/plugins/a0_fauxplexica/webui/citation-card.html`
- `/a0/plugins/a0_fauxplexica/webui/config.html`
- `/a0/plugins/a0_fauxplexica/webui/fauxplexica-store.js`
- `/a0/plugins/a0_fauxplexica/tests/webui/test_fauxplexica_store.mjs`

## Capabilities

- Search form bound to `POST /api/plugins/a0_fauxplexica/search` (streaming and non-streaming)
- NDJSON-over-SSE blockstream renderer for `init`, `block`, `updateBlock`, `researchComplete`, `response`, `messageEnd`, `done`, `error`
- Mode selector (Speed/Balanced/Quality) bound to providers default
- Source toggles (web/academic/discussions) and widget toggles (weather/calculator/stock) populated from `GET /api/plugins/a0_fauxplexica/providers`
- Inline bracket citations `[n]` are rendered as clickable anchors that highlight the matching sidebar card
- Rich citation sidebar cards rendered from `webui/citation-card.html` template (title/url/snippet/source/score)
- Missing SearxNG URL surfaced as inline configuration warning
- File uploads UI bound to `tools/fauxplexica_upload` and `tools/fauxplexica_uploads_search`
- Cancel/Stop button using `AbortController`
- Lightweight `config.html` showing providers JSON for diagnostics

## Validation

- `node tests/webui/test_fauxplexica_store.mjs` → `WEBUI_STORE_TESTS_OK`
- `PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests api` → clean
- `PYTHONPATH=/a0/plugins pytest -q tests` → 178 passed

## Deviations

- No build step or frontend framework introduced (vanilla ES module, matches existing plugin pattern).
- Backend-driven E2E browser tests deferred (no running browser harness in plugin tests).
- Stream parser handles NDJSON; native EventSource is not used because the backend returns NDJSON over `text/event-stream` (per existing `api/search.py`).
