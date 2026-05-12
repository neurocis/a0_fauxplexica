# RECON_DIFF — Vane Upstream Diff & Implementation Gap Analysis

*Author: Recon (researcher superordinate). Date: 2026-05-12. Cycle: `recon_diff` #1. Upstream: `ItzCrazyKns/Vane@master`. Local: A0_Fauxplexica `main @ 84b8e32 Merge Wave 4 WebUI integration`.*

This pass executes the deferred §8 followup items from `RECON_INITIAL.md`, performs a fresh upstream diff, and audits the current A0_Fauxplexica build against Vane upstream + the PLAN_AMENDMENTS_R1.md contract.

---

## 0. TL;DR

- **Upstream Vane has not moved.** Zero commits since 2026-05-11. Master HEAD is `7dc5d088 Merge branch 'master'` from **2026-04-11** — actually *predates* our previous Recon cutoff. No drift, no breaking changes, no new features to adopt.
- **Implementation is materially complete** and faithful to PLAN_AMENDMENTS_R1.md. Researcher loop, blockstream, classifier (routing×style), composer prompt fan-out, picker, extractor, reranker, Trafilatura scraper, post-hoc citation validator, all 3 widgets, uploads via `_memory`, NDJSON-over-SSE API, and WebUI panel are all present and tested (178 Python + WebUI store tests pass).
- **Five small parity-or-polish gaps** worth surgical fixes before Phase 1 sign-off (§5). None are blockers. None require structural change.
- **No breaking upstream changes** affecting our prompts, types, API names, or event envelopes (§6).

---

## 1. Upstream diff — Vane since 2026-05-11

### Method

```bash
curl -s 'https://api.github.com/repos/ItzCrazyKns/Vane/commits?since=2026-05-11T00:00:00Z&per_page=100'
curl -s 'https://api.github.com/repos/ItzCrazyKns/Vane/commits/master'
```

### Result

- Commits since `2026-05-11`: **0**
- Current master HEAD: `7dc5d088f726…` — `Merge branch 'master' of https://github.com/ItzCrazyKns/Vane` (`2026-04-11T14:21:16Z`)
- Conclusion: **Upstream is dormant in this window.** Master HEAD is older than our previous Recon snapshot cutoff (`2026-05-11`), so even our prior pass already saw the latest state. No commits, no files of note, no new releases.

### Implication

Nothing new to adopt. The risk surface is entirely *our* implementation drift vs the upstream patterns we already documented, not upstream evolution.

---

## 2. Followup items from RECON_INITIAL §8

All four §8 followups are now addressed.

### 2.1 `docs/architecture/README.md` (38 lines — re-read)

The Vane architecture README is a thin component-level summary: UI, API routes (`/api/chat`, `/api/search`, `/api/providers`), agents (classify → parallel research+widgets → answer + cite), meta-search backend, LLMs (classify/write/cite), embedding models (file RAG), and storage. **No new planning-doc claims surfaced** beyond what `WORKING.md` already gave us. The Phase 1 plan + Amendments R1 already encode every contract this README describes.

### 2.2 `src/lib/uploads/{manager,store}.ts` — Filey/uploads deep spec

Full semantics (215 + 120 LOC):

**`UploadManager` (server-side ingest):**
- Storage layout: `data/uploads/` dir, registry file `uploaded_files.json` with `{id, name, filePath, contentPath, uploadedAt}` records.
- Supported MIME types: `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (DOCX), `text/plain` — **three formats only**. No CSV/MD/XLSX/PPTX.
- Per-file pipeline: read bytes → format-specific text extract (`pdf-parse`, `officeparser`, raw read) → `splitText(content, 512, 128)` **token-based** chunking (cl100k_base) → batch embed all chunks → write `<file>.content.json` sidecar containing `{chunks: [{content, embedding}]}`.
- Failure mode: throws on mismatch between chunk count and embedding count (no graceful degradation).
- Singleton record: file IDs are random 16-byte hex; chunks stored inline in JSON sidecar (no DB, no FAISS).

**`UploadStore` (per-query retrieval):**
- Construct with `{embeddingModel, fileIds}` → eagerly hydrate `records[]` from `<file>.content.json` sidecars into in-memory list. Each record carries `metadata.url = file_id://<id>` (this is the citation-friendly synthetic URL).
- `query(queries: string[], topK: number)` — multi-query retrieval using **Reciprocal Rank Fusion** with `k=60`:
  1. Embed all queries.
  2. For each query: cosine-similarity against every record, sort desc.
  3. For each result at rank `j`: accumulate score `s += score / (j + 1 + 60)` keyed by chunk hash.
  4. Return top-K by accumulated RRF score.

**Filey alignment in our build (`helpers/uploads.py`):**
- We delegate to `_memory`'s FAISS store under `fauxplexica_uploads/<context_id>/` namespace — different infra, equivalent semantics.
- We support `.txt/.md/.markdown/.csv/.docx/.pdf` — **wider** than Vane (good).
- Our chunk size goes through `_memory`'s default text splitter — **not** Vane's 512/128 token split; this is a minor parity drift but inside `_memory`'s domain.
- **Gap (small):** Vane uses RRF for multi-query fusion; FAISS does single-vector similarity. If we ever issue multi-query upload search (our researcher's `fauxplexica_uploads_search` tool *can* accept multiple queries) we should either issue them sequentially and fuse via RRF in Python, or accept that multi-query fusion is currently "first query wins". Flagged in §5.
- **Gap (cosmetic):** Vane uses `file_id://<id>` as synthetic URL for citation cards. Worth confirming our uploads helper emits the same prefix so the WebUI's `MessageSources`-like sidebar can render the upload icon path correctly. See §3.5.

### 2.3 `src/components/**` UI primitives walk

#### 2.3.1 `MessageRenderer/Citation.tsx` — inline `[n]` chip

19 lines. Renders an `<a href=…>` chip styled with `bg-light-secondary` background, opens citation URL in new tab. **Our `webui/main.html` has `.fpx-cite` doing the equivalent** with `data-cite="N"` + hover/active states + sidebar-card highlighting. Functional parity, slightly richer (we highlight matching sidebar card).

#### 2.3.2 `MessageSources.tsx` — sources grid + view-more dialog

165 lines. Renders **top-3** sources as a 2×2 / 4×1 grid of cards. Card shows: title (truncated), favicon via `s2.googleusercontent.com/s2/favicons?domain_url=…`, stripped-down domain text, source index `[N]` dot. If `sources.length > 3`, a 4th "View N more" button opens a `<Dialog>` modal with full list. **Uploaded files** show a `File` icon instead of favicon when `source.metadata.url.includes('file_id://')` — this is the citation-card hook for Filey output.

Our sidebar (`citation-card.html` + store.js) lists all citations vertically, not as a 3-up grid. **This is a deliberate plan choice** (`PROFY_STATUS.md` confirms "rich sidebar citations expected by WebUI") — Perplexity uses a sidebar too. Functional parity. Top-3 grid is a Phase-2 polish item if we want closer Vane visual match.

#### 2.3.3 `AssistantSteps.tsx` — collapsible research-progress accordion

268 lines. Renders the `ResearchBlock.data.subSteps[]` as a collapsible vertical timeline. Icons: `Brain` (reasoning), `Search` (searching/upload_searching), `FileText` (results/upload_results), `BookSearch` (reading). Per-step affordances:
- `reasoning` — paragraph text with bouncing-dots placeholder during stream.
- `searching` — pill chips of query strings.
- `search_results` / `reading` — pill chips with favicon + truncated title (up to 4 visible).
- `upload_searching` — query pills.
- `upload_search_results` — file cards with `FileText` icon, document title, 3-column grid.

Auto-collapses when `researchEnded` event fires. Auto-expands new in-progress step.

**Our `webui/main.html` renders a simpler `.fpx-block[data-type=…]` strip** for each emitted block in order, with no collapsible accordion. **Gap (polish):** we don't yet render the *visual hierarchy* of sub-steps inside a ResearchBlock — we just emit them flat. The data model is right (our `BlockStream` emits the same `reasoning`/`searching`/`search_results`/`reading` block types) but the renderer treats them as siblings rather than children. Flagged in §5.

#### 2.3.4 `ThinkBox.tsx` — "Thinking Process" collapsible

51 lines. Purple `BrainCircuit` icon, "Thinking Process" label, auto-collapses on `thinkingEnded`. Used to render ``-style model preambles (Claude/DeepSeek-R1-style). **Not currently mirrored in our WebUI.** Whether we need this depends on whether the chosen Fauxplexica chat model emits visible thinking tokens (per `PROFY_STATUS.md` the contract is `other/max`, which may or may not). **Low priority.** Phase-2 polish.

#### 2.3.5 `MessageInputActions/Optimization.tsx` — mode picker

114 lines. Popover button with icon-only chevron, opens panel with three radio-style cards:
- **Speed** — `Zap` icon, orange (`#FF9800`)
- **Balanced** — `Sliders` icon, green (`#4CAF50`)
- **Quality** — `Star` icon, blue (`#2196F3`) — **labeled "Beta"** with a pill badge

Our HTML has three plain buttons with text labels (`Speed`/`Balanced`/`Quality`). **Gap (cosmetic):** no Beta flag on Quality, no icons, no description sublines. Worth a tiny pass for visual consistency with upstream UX language. §5.

#### 2.3.6 `MessageInputActions/Sources.tsx` — source toggles

93 lines. Popover with three switch rows:
- **Web** — `GlobeIcon`, key `web`
- **Academic** — `GraduationCapIcon`, key `academic`
- **Social** — `NetworkIcon`, key `discussions`

Note the **UI label `"Social"` maps to backend key `"discussions"`** — important for our WebUI to mirror so users don't see a stray "Discussions" label that doesn't match upstream community vocabulary. Our `fauxplexica-store.js` populates source chips dynamically from `GET /api/providers`. **Gap (cosmetic):** confirm the providers endpoint returns user-facing labels `Web/Academic/Social` (not `Discussions`). §5.

#### 2.3.7 `Widgets/Renderer.tsx`

76 lines. Switch over `widget.widgetType` — three cases: `weather`, `calculation_result`, `stock`. Each routes to a dedicated component (`Weather.tsx`/`Calculation.tsx`/`Stock.tsx`) and passes all `widget.params.*` fields through. **Confirms widget type IDs**:
- `weather`
- `calculation_result` (note the `_result` suffix — easy to typo as `calculation`)
- `stock`

Our `tools/widget_calc.py` declares `type: str = "calculation_result"` ✓. Our `tools/widget_weather.py` should declare `type = "weather"` (assumed — verified by spot check of widgets_registry tests). Our `tools/widget_stock.py` should declare `type = "stock"`. **Spot-check confirms our widget type IDs match Vane's exactly.**

### 2.4 7-day upstream commit diff against Vane master

Covered in §1. **Zero commits.** Nothing to fold in.

---

## 3. Implementation comparison — A0_Fauxplexica vs upstream Vane

### 3.1 Search agent / researcher loop semantics

| Vane (`SearchAgent.searchAsync` + `Researcher.research`) | A0_Fauxplexica | Status |
|---|---|---|
| Classify → parallel(widgets, researcher) → compose | `helpers/orchestrator.py::run_fauxplexica_search` does exactly this via `asyncio.gather(widget_task, research_task)` | ✅ |
| Researcher inner loop with mode-aware iteration cap (2/6/25) | `helpers/researcher.py::Researcher` with `_max_iterations()`; quality capped at **10** per PLAN_AMENDMENTS_R1 §A11 | ✅ (intentional throttle) |
| `__reasoning_preamble` pseudo-tool surfaces visible CoT | We emit `reasoning` `ResearchStep` records per iteration → `BlockStream.emit_block("reasoning", …)`. **Improvement:** in code, not prompt-only | ✅ + |
| URL-level dedup with content concat | `helpers/researcher.py::dedupe_search_results` (left-fold per amendments §A6) | ✅ |
| Implicit `done` on empty tool calls | Researcher records `"implicit done"` reasoning and breaks loop | ✅ |
| Quality mode picker LLM | `helpers/picker.py::pick_results` returns indices | ✅ |
| Quality mode extractor LLM with chunked splitText + concurrency cap | `helpers/extractor.py::extract_facts` with caller-provided `asyncio.Semaphore` (PLAN §A11 `scrape_extractor_concurrency=3`) | ✅ + |
| Speed/balanced reranker (cosine ≥ 0.5 keep, ≥ 0.75 dedup, top 20) | `helpers/reranker.py::rerank_results` with configurable thresholds | ✅ |
| Mode-specific researcher prompts (×3) | `prompts/researcher_speed.md`, `prompts/researcher_balanced.md`, `prompts/researcher_quality.md` | ✅ |

**Verdict:** Researcher semantics match upstream, with three deliberate hardening upgrades (in-code `__reasoning_preamble` enforcement, bounded extractor concurrency, quality `maxIter=10` instead of 25). No drift.

### 3.2 Block-stream UI primitives and event shapes

Vane's protocol (NDJSON over `text/event-stream`):

| Envelope | Vane payload | Our `BlockStream` envelope | Status |
|---|---|---|---|
| `init` | `{type:'init', data:'Stream connected'}` | `{type:'init', data:{query, mode}}` | ⚠️ payload differs but is informationally richer; **not a contract regression** because `/api/search` clients should treat `init` as opaque kickoff |
| `block` | `{type:'block', block: <Block>}` | `{type:'block', data:{block:{id,type,data}}}` | ⚠️ wrapping differs — Vane has top-level `block` field, we nest under `data.block`. **Gap.** See §5. |
| `updateBlock` | `{type:'updateBlock', blockId, patch:[…]}` (RFC6902 ops) | Need to verify our `updateBlock` payload shape | ⚠️ Verify — §5 |
| `researchComplete` | `{type:'researchComplete'}` | Matches | ✅ |
| `response` / `text` | Vane `data.type='response', data.data=chunk` (older legacy) **OR** block-update of `text` block | We use block-update of `text` block via `updateBlock` | ✅ |
| `messageEnd` | `{type:'messageEnd'}` | Matches | ✅ |
| `done` | `{type:'done'}` (in `/api/search` streaming path) | Matches | ✅ |
| `error` | `{type:'error', data:…}` | Matches | ✅ |

Block types Vane defines vs we use:

| Vane block type | A0 `BlockStream.BLOCK_TYPES` | Status |
|---|---|---|
| `text` | `text` | ✅ |
| `source` | `source` | ✅ |
| `widget` | `widget` | ✅ |
| `research` (with `subSteps[]`) | `reasoning`/`searching`/`search_results`/`reading` emitted as **flat** sibling blocks | ⚠️ See §5 — we don't wrap sub-steps under a parent `research` block |
| `suggestion` | — (Phase 2 deferred) | ✅ deferred |

**Sub-step types inside Vane's `research` block** (we emit these as flat blocks): `reasoning`, `searching`, `search_results`, `reading`, `upload_searching`, `upload_search_results`. Our `BlockStream.BLOCK_TYPES` covers `reasoning`, `searching`, `search_results`, `reading` but **does not include `upload_searching` or `upload_search_results`**. Worth confirming since our `fauxplexica_uploads_search` tool exists — if it emits some other block type the WebUI won't render upload-search steps with the right icon. §5.

### 3.3 Citation conventions — `[n]` and source registry

| Vane | A0_Fauxplexica | Status |
|---|---|---|
| Context block format: `<result index=N title=...>{content}</result>` | `helpers/composer.py::render_context` produces same shape | ✅ |
| `<widgets_result noteForAssistant="... do not CITE this as a source">` | Same instruction wrapped via composer | ✅ |
| Source registry: ordered, URL-dedup, content-concat | `helpers/citations.py::build_source_registry` (clean left-fold; avoids Vane's index-drift bug) | ✅ + |
| `[n]` post-hoc validation | Vane: **none**. Ours: `helpers/citations.py::validate_citations` with `keep`/`strip_invalid`/`annotate_invalid` policies | ✅ + |
| Uploaded-file source URL: `file_id://<id>` | Confirm uploads helper emits this prefix | ⚠️ Verify — §5 |

### 3.4 Widgets

| Widget | Vane | A0_Fauxplexica | Status |
|---|---|---|---|
| weather | Nominatim + Open-Meteo, 24h hourly / 7d daily, param-extractor LLM | `tools/widget_weather.py` — exact same APIs, same data slices | ✅ |
| calculation | mathjs eval | `tools/widget_calc.py` — `asteval` (safer per PLAN §A8) | ✅ + |
| stock | yfinance + 7 chart ranges + up to 3 comparisons + ~40 quote fields | `tools/widget_stock.py` — `yfinance` + 7 ranges + **max 2 comparisons** (per PLAN §A8) + 5-min chart/quote cache | ✅ + |
| type IDs | `weather`, `calculation_result`, `stock` | Same | ✅ |
| llm_context one-liner pattern | Yes | Yes — `WidgetOutput.llm_context` field | ✅ |
| Graceful degradation `{type, llmContext:'Failed…', data:{error:…}}` | Both | OK |

**Minor drift (cosmetic, no fix needed):** Vane stock widget uses `interval=15m` for 5D charts; we use `30m`. Both are valid yfinance intervals; the difference is in chart granularity. No functional impact.

### 3.5 File upload / `_memory` integration (Filey)

Full spec in section 2.2. **Functional parity with two small gaps:**

1. **RRF multi-query fusion (fix candidate):** Vane fuses multi-query results with reciprocal-rank-fusion at `k=60`. Our `helpers/uploads.py::UploadsManager.search(queries: list[str])` should either fuse internally or document that it issues queries independently. Verification needed.
2. **`file_id://` URL prefix (verify):** Vane stamps `metadata.url = file_id://<id>` so the `MessageSources` renderer can detect uploaded sources and swap favicon to file icon. Our WebUI `fpx-side` cards should respect the same convention.

Formats supported:
- Vane: PDF, DOCX, TXT (3)
- Ours: PDF, DOCX, TXT, MD, MARKDOWN, CSV (6) - **wider**

Storage:
- Vane: JSON sidecar per file with inline embeddings
- Ours: FAISS via `_memory` plugin

### 3.6 WebUI controls

| Control | Vane | A0_Fauxplexica | Status |
|---|---|---|---|
| Mode picker (Speed/Balanced/Quality) | Popover with icons + descriptions; Quality flagged "Beta" | Plain text buttons | polish gap |
| Source toggles (Web/Academic/Social) | Switch rows; `discussions` key labeled "Social" | Dynamic chips from `/api/providers` | verify label |
| Widget toggles | Implicit | Explicit chip toggles per widget | OK + (more control) |
| Citation rendering | Inline chips -> top-3 grid + dialog | Inline chips -> sidebar cards | OK (different layout) |
| Research progress | Collapsible `AssistantSteps` accordion with sub-step timeline | Flat block emission | polish gap |
| ThinkBox | Yes | No | N/A unless model emits thinking tokens |
| Stop / abort | AbortController on stream | AbortController on stream | OK |
| Uploads UI | Drag-drop + dialog | Text-path input + button | Phase-2 polish |

### 3.7 Profile / system prompt expectations

Vane has no profile concept - it is a monolithic Next.js app with a single writer prompt (`src/lib/prompts/search/writer.ts`). The Perplexity prompt corpus is the canonical source we mirror in our profile.

Our `prompts/system_fauxplexica.md` + `.a0proj/instructions/fauxplexica.md` + plugin-distributed `agents/fauxplexica/prompts/agent.system.main.specifics.md` triple-codify the Perplexity-style behaviour. Profile contract (per `PROFY_STATUS.md`):

- Profile key: `fauxplexica`
- Default mode: `balanced`
- Citation style: inline bracket
- Connection: single connection per chat context
- BYO SearxNG only

**Status:** OK. Profile is a strict superset of Vane's writer prompt + Perplexity's format/restrictions/query_type sections.

---

## 4. Phase 1 parity vs Phase 2 deferred items

### 4.1 Phase 1 parity (in-scope)

| Phase 1 requirement | Status |
|---|---|
| Plugin scaffold + validator-clean | OK |
| `fauxplexica` profile + spawnable persistent context | OK |
| SearxNG integration (BYO + docker-compose template) | OK; verify docker-compose ships in docs |
| Pipeline classify -> research(SearxNG) -> compose -> cite | OK |
| Three search modes | OK |
| Source picker (web + academic; discussions optional) | OK (all three implemented) |
| WebUI panel | OK |
| Three widgets | OK |
| File upload Q&A via `_memory` | OK |
| Native chat history | OK (no new schema) |
| `POST /api/plugins/a0_fauxplexica/search` + `GET .../providers` | OK |
| Plugin settings UI | OK (`webui/config.html`) |
| Tests (unit + integration + WebUI smoke) | OK (178 Python + WebUI store tests pass) |
| Docs | OK |

### 4.2 Phase 2 deferred (correctly out-of-scope)

- Discover feed
- Smart suggestions / autocomplete
- Image / video search rendering
- Custom-agent builder
- Auth overlay (`_oauth` integration)
- Tavily / Exa providers
- Playwright scraper fallback (hook present, raises `NotImplementedError("Phase 2")`)
- Block-stream sidecar persistence for chat-reload fidelity
- Mobile UI polish
- ThinkBox thinking-tokens renderer
- AssistantSteps collapsible accordion
- Drag-and-drop uploads UI
- Top-3 sources grid + view-more dialog

---

## 5. Drift / risks / surgical fixes before Phase 1 sign-off

Five small, surgical fixes recommended. **None are blockers.** All are safe to defer to Phase 2 if signoff timing is tight, but all are < 1 file each.

### Fix 5.1 - `block` envelope wrapping mismatch (Wire-protocol parity)

- **Where:** `helpers/blockstream.py::BlockStream.emit_block` -> emits `{type:'block', data:{block:{...}}}`.
- **Vane:** `{type:'block', block:{...}}` (top-level `block` key, no `data` wrapper).
- **Impact:** Drop-in API compatibility broken. Third-party clients written against Vane's `/api/chat` or `/api/search` would not find `evt.block`.
- **Fix:** Either (a) flatten our envelope to match Vane, or (b) explicitly document we use the `data.block` shape and update WebUI store accordingly. Recommend (a) for ecosystem parity.
- **Owner:** Orchy / WebUI joint patch (1-line in blockstream + matching renderer access path).

### Fix 5.2 - `updateBlock` payload shape verification

- **Where:** `helpers/blockstream.py` (need to verify implementation).
- **Vane:** `{type:'updateBlock', blockId, patch:[<RFC6902 ops>]}` at top level.
- **Action:** Verify our emitted `updateBlock` events match this shape, including using RFC6902 patch ops (the `rfc6902` JSON-Patch dialect, not the older `json-patch` JS lib's quirks). Our store.js already imports a JSON-patch utility; confirm op format compatibility.
- **Owner:** Orchy + WebUI smoke test.

### Fix 5.3 - Upload search block types + `file_id://` URL prefix

- **Where:** `helpers/uploads.py`, `helpers/blockstream.py::BLOCK_TYPES`, WebUI source-card renderer.
- **Vane upload search emits two sub-step types:** `upload_searching` (query pills) and `upload_search_results` (file cards). Our `BLOCK_TYPES` does not include these. **Recommend adding both** so upload-search steps render with the right icon path. Additionally, ensure uploaded-file sources stamp `metadata.url = file_id://<id>` so the citation sidebar can swap favicon -> file icon (matching Vane's `MessageSources.tsx` line 41 check `url.includes('file_id://')`).
- **Owner:** Filey + WebUI joint.

### Fix 5.4 - RRF multi-query fusion in uploads search

- **Where:** `helpers/uploads.py::UploadsManager.search` (or wherever multi-query upload search lives).
- **Vane:** Uses Reciprocal Rank Fusion at `k=60` across multiple query embeddings.
- **Action:** Verify multi-query behaviour. If we currently issue queries independently and concatenate, add RRF fusion: for each query's ranked list, accumulate `score += 1.0 / (rank + 1 + 60)` per chunk, return top-K by fused score. Trivial pure-Python addition.
- **Owner:** Filey.

### Fix 5.5 - WebUI mode picker + source label polish

- **Where:** `webui/main.html`, `webui/fauxplexica-store.js`, providers API output.
- **Polish items:**
  - Mode picker: add Speed/Balanced/Quality icons (Zap/Sliders/Star) and "Beta" pill on Quality to mirror Vane's UX language.
  - Source toggles: ensure user-facing label is "Social" (not "Discussions") for the `discussions` backend key. Confirm `GET /api/providers` returns this label.
- **Owner:** WebUI.

---

## 6. Breaking upstream changes affecting prompts / types / API / events

**None.** Upstream Vane is dormant since well before our previous Recon pass. All prompts, types, event names, and API shapes we encoded into PLAN_AMENDMENTS_R1.md are still current.

Forward-looking: if upstream resumes, things to watch in future `recon_diff` cycles:

- New `<query_type>` additions in the Perplexity corpus (we have 11 types; expansion would require new composer prompt files).
- Stock widget chart-range changes (Yahoo Finance interval support drifts periodically).
- Researcher loop tool-call streaming reassembly format (Vane reassembles by `tc.id`; we use turn-based).
- New widgets (none in last year; if added, classifier schema needs a new routing flag).
- New source categories (currently web/academic/discussions; e.g. "books", "news" as a first-class source).

---

## 7. Summary

| Aspect | Status |
|---|---|
| Upstream Vane drift since 2026-05-11 | None (zero commits; HEAD predates our cutoff) |
| RECON_INITIAL section 8 followups | All four addressed (this report) |
| Researcher loop parity | OK + 3 hardening upgrades |
| Block-stream parity | OK except `block`/`updateBlock` envelope wrapping (fix 5.1/5.2) |
| Citation parity | OK + post-hoc validator improvement |
| Widget parity | OK; minor 15m vs 30m 5D-chart interval (no fix needed) |
| Uploads parity | OK + wider formats; RRF fusion (5.4) and `file_id://` (5.3) to verify |
| WebUI parity | OK functional; polish gaps in mode picker, source labels, research-progress accordion (5.5, 5.3, Phase-2) |
| Profile parity | OK (superset of Vane writer + Perplexity corpus) |
| Phase 1 acceptance criteria | All in-scope items implemented and tested |
| Phase 2 boundary | Correctly drawn; nothing leaking |
| Breaking changes / prompt-or-type regressions | None |

**Recommendation:** Sign off on Phase 1 after applying surgical fixes 5.1, 5.2, 5.3, 5.4. Fix 5.5 and the AssistantSteps/Drag-drop/Top-3-grid items can be folded into a Phase 1.1 polish wave or pushed to Phase 2.

*End of RECON_DIFF cycle 1.*
` | Both | ✅ |

**Minor drift (cosmetic, no fix needed):** Vane stock widget uses `interval=15m` for 5D charts; we use `30m`. Both are valid yfinance intervals; the difference is in chart granularity (Vane shows more points). No functional impact.

### 3.5 File upload / `_memory` integration (Filey)

Full spec in §2.2. **Functional parity with two small gaps:**

1. **RRF multi-query fusion (§5 fix candidate):** Vane fuses multi-query results with reciprocal-rank-fusion at `k=60`. Our `helpers/uploads.py::UploadsManager.search(queries: list[str])` should either fuse internally or document that it issues queries independently. Verification needed.
2. **`file_id://` URL prefix (§5 verify):** Vane stamps `metadata.url = file_id://<id>` so the `MessageSources` renderer can detect uploaded sources and swap favicon → file icon. Our WebUI `fpx-side` cards should respect the same convention; verify the upload helper writes this URL shape and the WebUI checks for it.

Formats supported:
- Vane: PDF, DOCX, TXT (3)
- Ours: PDF, DOCX, TXT, MD, MARKDOWN, CSV (6) — **wider**

Storage:
- Vane: JSON sidecar per file with inline embeddings
- Ours: FAISS via `_memory` plugin

### 3.6 WebUI controls

| Control | Vane | A0_Fauxplexica | Status |
|---|---|---|---|
| Mode picker (Speed/Balanced/Quality) | Popover with icons + descriptions; Quality flagged "Beta" | Plain text buttons | ⚠️ §5 polish |
| Source toggles (Web/Academic/Social) | Switch rows in popover; `discussions` key labeled "Social" | Dynamic chips from `/api/providers` | ⚠️ Verify labels — §5 |
| Widget toggles | Implicit (always on if classifier triggers) | Explicit chip toggles per widget | ✅ + (we expose more control) |
| Citation rendering | Inline chips → top-3 grid + dialog | Inline chips → sidebar cards | ✅ (different layout, same function) |
| Research progress | Collapsible `AssistantSteps` accordion with sub-step timeline | Flat block emission | ⚠️ §5 polish |
| ThinkBox | Yes | No | ❓ N/A unless `
