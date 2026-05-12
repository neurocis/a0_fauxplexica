# A0_Fauxplexica — Phase 1 Sign-Off

**Date:** 2026-05-12
**Plugin path:** `/a0/plugins/a0_fauxplexica/`
**Main HEAD:** `10668db Merge composer text-emit fix from e2e smoke`
**Status:** ✅ Phase 1 Complete

---

## Scope delivered (matches PLAN_PHASE1 + PLAN_AMENDMENTS_R1)

- Native Agent Zero plugin scaffold + validator-clean structure
- Dedicated `A0_Fauxplexica` chat profile + Fauxplexica-specific model preset
- SearxNG-based meta search (BYO only)
- Classify → research → compose pipeline with mode-specific behavior
- Three search modes: Speed / Balanced / Quality
- Source toggles: web / academic / discussions (UI label: `Social`)
- Widgets: weather, calculator, stock (with 5-min stock cache, asteval-based calc, Nominatim+Open-Meteo weather)
- File-RAG via `_memory` adapter (PDF/TXT/MD/CSV/DOCX) with per-context namespace and `file_id://` URL stamping
- Reciprocal Rank Fusion (RRF, k=60) for multi-query upload search (Vane-parity)
- Citation validation with `keep` / `strip_invalid` / `annotate_invalid` policies
- Source registry with stable 1-based indices and URL dedupe
- WebUI: answer panel, mode/source/widget controls, blockstream renderer, rich citation sidebar cards, providers/status panel, upload hooks
- NDJSON-over-SSE streaming protocol with Vane-compatible envelopes:
  - top-level `block` field on `block` events (+ legacy `data.block`)
  - top-level `blockId`/`patch` on `updateBlock` (+ legacy `data.id`/`data.ops`)
- Block types: `reasoning`, `searching`, `search_results`, `reading`, `upload_searching`, `upload_search_results`, `source`, `widget`, `text`
- Event types: `init`, `block`, `updateBlock`, `researchComplete`, `response`, `messageEnd`, `done`, `error`
- API endpoints:
  - `POST /api/plugins/a0_fauxplexica/search`
  - `GET /api/plugins/a0_fauxplexica/providers`
- Settings/config surface with documented BYO-SearxNG behavior
- Tests + Phase 1 docs (README, API, CONFIG, ARCHITECTURE)

## Out-of-scope by design (deferred to Phase 2)

Discover feed, autocomplete suggestions, image/video search rendering, AssistantSteps collapsible accordion, drag-drop uploads, top-3 sources grid with view-more dialog, ThinkBox, Playwright scraper fallback, block-stream sidecar persistence, mobile polish, multi-tenant hardening, Tavily/Exa providers.

## Wave summary

| Wave | Scope | Key commits |
|---|---|---|
| 1a | Scaffold + Recon initial intel | `251b834`, `9434f2b` |
| 1b | Search (Searx) + Classifier (Classy) + Widgets (Widge) + Uploads (Filey) | `9098d6c` (merge) |
| 2 | Researcher (Reggie) + Composer (Compo) + Orchestrator/BlockStream (Orchy) + QA + Docs | `607bc2e` (merge), `c0ddd54` (integration fix) |
| 3 | Citations (Citer) + Profile (Profy) + API (APIs) | `eae2572`, `b48ee20` |
| 4 | WebUI | `84b8e32` |
| Polish | Docs refresh | `5c66f9d` |
| Recon R1 | Envelope parity, upload URLs, RRF, mode picker UI polish | `ebd507b`, `af59615` |
| Smoke | Composer text-emit Vane envelope fix | `10668db` |

## Validation

On `main @ 10668db`:

```text
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests api
clean

PYTHONPATH=/a0/plugins pytest -q tests
181 passed

node tests/webui/test_fauxplexica_store.mjs
WEBUI_STORE_TESTS_OK
WEBUI_RECON_R1_PARSER_OK

# Offline end-to-end smoke (stubbed search/scrape/llm)
EVENT_TYPES = ['init', 'researchComplete', 'block', 'response', 'messageEnd', 'done']
SMOKE_OK
```

The smoke exercises the full pipeline end-to-end through `run_fauxplexica_search`, BlockStream events, citation handling, graceful failure of SearxNG (BYO not configured) and graceful failure of composer LLM. No `unsupported event type` warnings remain.

## Upstream parity

Recon `recon_diff` cycle 1 confirmed:
- Zero new upstream Vane commits since 2026-05-11.
- No breaking changes vs implementation.
- All recommended surgical fixes (5.1–5.4) applied.
- UI polish fix 5.5 applied.

## Outstanding items (non-blocking)

- Live end-to-end smoke against a user-supplied BYO SearxNG instance.
- Future Recon `recon_diff` passes if upstream Vane resumes activity.
- Phase 2 scope items listed above.

## Sign-off

Phase 1 is feature-complete, parity-matched against upstream Vane, fully tested at the unit+integration+offline-e2e level, documented, and merged on `main`.
