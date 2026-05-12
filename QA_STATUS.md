# A0_Fauxplexica — QA Status

Last updated: 2026-05-11 14:36 PDT  
QA owner: QA — continuous validation / integration engineering  
Scope: validation only; not a feature owner

## 1. Current Baseline Summary — Integrated `main`

Baseline branch: `main`  
Baseline integrated merge commit: `9098d6c` — `Merge Wave 1b deliverables`

Validation commands run from `/a0/plugins/a0_fauxplexica`:

```bash
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
PYTHONPATH=/a0/plugins pytest -q tests
```

Results:

- `PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests` → PASS, exit `0`
- `PYTHONPATH=/a0/plugins pytest -q tests` → PASS, `132 passed in 2.90s`, exit `0`

Important command-environment note:

- Running `pytest -q tests` directly from `/a0/plugins/a0_fauxplexica` caused collection errors for widget tests importing `a0_fauxplexica.*`.
- Correct validation must set the package parent on `PYTHONPATH`:

```bash
PYTHONPATH=/a0/plugins pytest -q tests
```

This is not currently a product failure on `main`; it is a test invocation requirement.

Current Wave 2 context from orchestrator:

- Reggie — `helpers/researcher.py`, `prompts/researcher_*.md`
- Compo — `helpers/composer.py`, `prompts/composer_*.md`
- Orchy — `helpers/blockstream.py`, `helpers/orchestrator.py`

Observed during validation session:

- The working tree was restored to the branch that was active before each baseline checkout.
- At one point the active branch was `compo/composer` at `ef53ffc`; later the active branch was `docs/phase1-docs` when final baseline validation was run. QA did not merge feature branches.

## 2. Full Test Inventory

### Core schema / search pipeline tests

#### `tests/test_types.py`

Subsystem: shared data contracts and helper defaults.

Covers:

- `SearchResult.from_dict` minimal parsing.
- Camel-case `publishedDate` compatibility.
- Unknown-key preservation in `extra`.
- Bad score coercion to `None`.
- `SearchResult.to_dict` omission of empty fields.
- Optional field serialization.
- Thin wrapper module helpers.
- Picker/extractor default objects.

Integration sensitivity:

- High for Wave 2 because `helpers/types.py` is likely shared by researcher, composer, blockstream, and orchestrator.

#### `tests/test_classifier.py`

Subsystem: unified classifier and routing/style schema.

Covers:

- URL extraction.
- Pure math fast path.
- Lone URL fast path.
- Greeting fast path.
- Empty query behavior.
- LLM happy path.
- Academic/discussion/widget routing gates.
- URL prompt plumbing and URL regex authority.
- LLM exception fallback.
- Invalid JSON fallback.
- URL-biased fallback behavior.
- Unknown primary type normalization.
- String bool coercion.
- Standalone query fallback.
- Unknown enable flags dropped.
- `to_dict` output shape.

Integration sensitivity:

- Medium/high for Orchy because orchestrator/tool routing must preserve classifier semantics.
- Medium for widgets because classifier flags gate widget execution.

#### `tests/test_searxng_client.py`

Subsystem: SearxNG client.

Covers:

- Repeated engines/categories parameters and option plumbing.
- Pagination flattening order.
- Transient 5xx retry behavior.
- 4xx non-retry behavior.
- Search argument validation.

Integration sensitivity:

- High for Reggie because research loop search behavior depends on this client.

#### `tests/test_reranker.py`

Subsystem: embedding-based result re-ranking.

Covers:

- Filtering, deduplication, sorting, and slicing.
- `top_k` after sort.
- Embedder failure fallback and warning log.

Integration sensitivity:

- Medium/high for Reggie because search result order influences source selection and citations.

#### `tests/test_picker.py`

Subsystem: source/result picker.

Covers:

- Single structured LLM call and capped indices.
- JSON string response parsing.
- Empty or zero max behavior without LLM call.

Integration sensitivity:

- Medium/high for Reggie and Compo due source selection and citation source list construction.

#### `tests/test_extractor.py`

Subsystem: content fact extraction.

Covers:

- Content splitting and semaphore use.
- JSON string response parsing.
- Empty content short-circuit without LLM call.

Integration sensitivity:

- Medium/high for Reggie due iterative research and scrape/extract loop costs.

#### `tests/test_scraper.py`

Subsystem: URL scraping adapter.

Covers:

- Successful extracted content.
- Empty extraction fallback.
- Fetch exception fallback.
- Playwright hook currently raises Phase 2 marker.

Integration sensitivity:

- Medium/high for Reggie. Scrape fallback shape must stay compatible with source/citation flow.

### Upload / personal search tests

#### `tests/test_uploads.py`

Subsystem: file upload ingestion, metadata, search/list/remove operations.

Covers:

- TXT ingestion using context-scoped memory and metadata.
- Search with `file_id` override filter.
- List and remove files.
- Unsupported image error.

Integration sensitivity:

- Medium for Orchy if uploads/personal search become part of unified orchestration.

### Composer tests

#### `tests/test_composer.py`

Subsystem: answer composition and citation rendering.

Present on feature branch observation: `compo/composer` contained this test file. It was not present in the baseline `main` inventory output during prior Wave 1b validation record, but it is visible in the current repository checkout and should be treated as Compo-targeted validation when validating that branch.

Expected coverage area:

- Composer helper behavior.
- Prompt/style selection.
- Source/citation formatting contracts.
- Final answer structure.

Integration sensitivity:

- High for Compo/Reggie/Orchy handoff because composer consumes research output, source lists, and blockstream/final answer events.

### Widget tests

#### `tests/test_widgets/test_widget_cache.py`

Subsystem: TTL cache used by widget integrations.

Covers:

- Miss returns `None`.
- Set/get round trip.
- Expiration.
- Clear behavior.
- Invalid TTL validation.
- `contains` TTL behavior.

Integration sensitivity:

- Low/medium, mostly stock/weather widget stability.

#### `tests/test_widgets/test_widget_calc.py`

Subsystem: calculation widget.

Covers:

- Routing predicate from classification object/dict.
- Simple arithmetic.
- `sqrt` function.
- Percent calculations.
- No-expression graceful output.
- Extractor failure fallback.
- Eval error fallback.
- Code fence stripping.
- Utility model call shape support.

Integration sensitivity:

- Medium for Orchy due widget execution ordering and block updates.

#### `tests/test_widgets/test_widget_weather.py`

Subsystem: weather widget.

Covers:

- Routing predicate.
- Weather code description lookup.
- Happy path for Paris.
- No-location output.
- Empty geocode fallback.
- Open-Meteo 500 failure.
- Extractor exception fallback.

Integration sensitivity:

- Medium for Orchy due widget execution routing and blockstream output.

#### `tests/test_widgets/test_widget_stock.py`

Subsystem: stock widget.

Covers:

- Routing predicate.
- Strict and lenient ticker JSON parsing.
- No-ticker output.
- Happy path with comparison cap.
- Extractor failure fallback.
- Empty quote fallback.
- Fetch exception fallback.
- Quote cache behavior.

Integration sensitivity:

- Medium for Orchy; external dependency risk due `yfinance`.

#### `tests/test_widgets/test_widgets_registry.py`

Subsystem: widget registry/executor.

Covers:

- No widgets triggered.
- Disabled widget skipped even when triggered.
- Triggered widget runs.
- Exception converted to failure output.
- One failure does not kill other widgets.
- Predicate exception containment.
- `None` return filtered.
- Wrong-shape output wrapped as failure.
- Failure output shape.

Integration sensitivity:

- High for Orchy because this defines resilient tool/widget execution semantics.

## 3. Dependency Inventory — `requirements.txt`

Baseline dependencies observed:

```text
asteval
httpx
pytest
pytest-asyncio
yfinance
pdfplumber>=0.11
python-docx>=1.1
```

Dependency purpose / risk notes:

- `asteval` — safe-ish expression evaluation for calculator widget. Watch for calculator API changes.
- `httpx` — async HTTP for SearxNG, weather, scraping, and API-adjacent tests. Central dependency for network mocks.
- `pytest` — test runner.
- `pytest-asyncio` — async test support for helpers/tools.
- `yfinance` — stock widget data. Known fragile unofficial Yahoo Finance dependency; rate limits and upstream breakage expected.
- `pdfplumber>=0.11` — PDF upload extraction.
- `python-docx>=1.1` — DOCX upload extraction.

Integration risk:

- `requirements.txt` is a likely cross-branch conflict file if Reggie adds scraping/search dependencies, Compo adds formatting/rendering dependencies, or Orchy adds streaming/API helpers.
- Current plan amendment mentions Trafilatura as scraper choice, but `trafilatura` is not currently in the observed requirements. If a Wave 2 branch introduces it, validate dependency install/import assumptions explicitly.

## 4. Risk Register — Wave 2 Integration Conflicts

### R1. `helpers/types.py` shared contract drift

Risk level: High

Why:

- `helpers/types.py` is the shared schema surface for search results and defaults.
- Reggie may need richer research/source/citation types.
- Compo may need answer/citation/source structures.
- Orchy may need blockstream event and orchestration state types.

Failure modes:

- Constructor/from-dict incompatibilities.
- Optional fields renamed or made required.
- Citation/source index mismatch.
- Existing tests pass in isolation but integrated composer/researcher handoff fails.

Validation focus:

```bash
PYTHONPATH=/a0/plugins pytest -q tests/test_types.py tests/test_picker.py tests/test_extractor.py tests/test_reranker.py
```

After each branch merge candidate, also inspect:

```bash
git diff main...HEAD -- helpers/types.py
```

### R2. `requirements.txt` conflicts and missing imports

Risk level: High

Why:

- Multiple Wave 2 branches may add dependencies.
- Baseline has minimal dependency pins.
- Missing package parent on `PYTHONPATH` already caused test collection errors for widget tests when invoked incorrectly.

Failure modes:

- New imports not represented in `requirements.txt`.
- Version-dependent test failures.
- Feature branch passes because dependency exists in local venv but not in clean install.

Validation focus:

```bash
cat requirements.txt
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
PYTHONPATH=/a0/plugins pytest -q tests
```

If requirements change, recommend a clean environment or at least explicit import smoke checks before merge.

### R3. Lazy imports between Orchy/Reggie/Compo

Risk level: High

Why:

- Wave 2 splits orchestration, research, composition, and streaming across separate branches.
- Likely circular edges:
  - orchestrator imports researcher and composer;
  - composer imports citation/source types;
  - researcher imports blockstream or emits blockstream-compatible events;
  - blockstream imports shared types.

Failure modes:

- Import cycles only visible at runtime.
- `TYPE_CHECKING` / forward reference mistakes.
- Compileall passes but instantiation fails.
- Tests pass branch-local but fail after combining branches.

Validation focus:

```bash
PYTHONPATH=/a0/plugins python - <<'PY'
from a0_fauxplexica.helpers import orchestrator, researcher, composer, blockstream
print('imports ok')
PY
```

And targeted pytest subsets after each branch.

### R4. Blockstream contract drift

Risk level: High

Why:

- Plan requires progressive block-based streaming render.
- Recon notes Vane uses newline-delimited JSON over `text/event-stream`, not standard SSE `data:` framing.
- Block update semantics use JSON-Patch ops like `{op:'replace', path:'/data/subSteps', value:[...]}`.
- Orchy owns `helpers/blockstream.py` and `helpers/orchestrator.py`; Compo/Reggie may independently assume shapes.

Failure modes:

- Renderer cannot apply updates.
- Research substeps not represented consistently.
- Composer final answer does not close/replace expected blocks.
- WebUI/API mismatch between NDJSON-over-SSE and true SSE.
- Abort/cancellation semantics omitted.

Validation focus:

- Unit tests for block event schema if present on Orchy branch.
- Integrated smoke test of orchestrator emitting start/search/source/final/error events.
- Manual diff of `helpers/blockstream.py` against composer/researcher call sites.

### R5. Citation validation not yet merged / citation correctness gap

Risk level: High

Why:

- Planning docs explicitly call out missing post-hoc validation of citations.
- Desired behavior: regex scan `\[(\d+)\]`, handle out-of-range citations, and log metric for invalid citations.
- Compo and Reggie both touch the source/citation boundary.

Failure modes:

- Answer cites `[42]` with only 7 sources.
- Source numbering inconsistent after dedup/filter/pick.
- Citation repair drops too much or silently hides errors.
- Composer tests pass with ideal citations but integrated research produces invalid citation indices.

Validation focus:

```bash
PYTHONPATH=/a0/plugins pytest -q tests/test_composer.py tests/test_types.py tests/test_picker.py
```

If citation tests are added later, include them in every Compo/Reggie/Orchy validation subset.

### R6. A0 plugin validator endpoint/login limitation from Scaff

Risk level: Medium

Why:

- Plugin validator validation is part of Phase 1 success criteria.
- Scaff identified endpoint/login limitations around A0 plugin validator usage.
- Do not restart A0 backend per current constraints.

Failure modes:

- Code passes unit tests but cannot be validated through A0 plugin validator due auth/endpoint constraints.
- False negative from validator if login endpoint or session state is unavailable.

Validation focus:

- Record validator limitation separately from Python unit test status.
- Do not block pure helper merges solely on unavailable validator endpoint.
- When endpoint access is available, use the validator without restarting backend.

### R7. External service fragility: SearxNG, Yahoo Finance, scraping

Risk level: Medium/high

Why:

- SearxNG public instances are unreliable; BYO instance expected.
- Yahoo Finance / `yfinance` frequently breaks and rate-limits.
- Scraping has fallback behavior and Phase 1 avoids Playwright complexity.

Failure modes:

- Tests over-mock happy path and miss real integration breakage.
- Stock widget burns 8+ chart calls per ticker and rate limits.
- Search client parameter serialization differs between SearxNG instances.

Validation focus:

- Keep unit tests mocked/deterministic.
- Add optional real-service smoke tests only when instructed and configured.
- Track dependency addition and network assumptions in branch notes.

## 5. Proposed Wave 2 Integration Test Matrix

All commands assume:

```bash
cd /a0/plugins/a0_fauxplexica
export PYTHONPATH=/a0/plugins
```

### Universal pre-merge checks for any Wave 2 branch

```bash
git status --short
git rev-parse --short HEAD
git log --oneline -5
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
```

Then run targeted branch tests and affected integrated subsets below.

### Reggie — `helpers/researcher.py`, `prompts/researcher_*.md`

Primary risks:

- Search/research loop shape.
- SearxNG client use.
- Scrape/extract/pick/rerank interaction.
- Citation/source numbering handoff to composer.
- Lazy import cycle with orchestrator/blockstream/composer.

Targeted tests:

```bash
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_searxng_client.py \
  tests/test_scraper.py \
  tests/test_extractor.py \
  tests/test_picker.py \
  tests/test_reranker.py \
  tests/test_types.py
```

Affected integrated subset:

```bash
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_classifier.py \
  tests/test_searxng_client.py \
  tests/test_scraper.py \
  tests/test_extractor.py \
  tests/test_picker.py \
  tests/test_reranker.py \
  tests/test_types.py
```

Import smoke:

```bash
PYTHONPATH=/a0/plugins python - <<'PY'
from a0_fauxplexica.helpers import researcher
print('researcher import ok')
PY
```

### Compo — `helpers/composer.py`, `prompts/composer_*.md`

Primary risks:

- Citation validation gap.
- Source numbering/formatting contract.
- Prompt/style routing drift from classifier taxonomy.
- Handoff from Reggie research output.
- Final answer event shape expected by Orchy/blockstream.

Targeted tests:

```bash
PYTHONPATH=/a0/plugins pytest -q tests/test_composer.py tests/test_types.py
```

Affected integrated subset:

```bash
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_classifier.py \
  tests/test_types.py \
  tests/test_picker.py \
  tests/test_composer.py
```

Import smoke:

```bash
PYTHONPATH=/a0/plugins python - <<'PY'
from a0_fauxplexica.helpers import composer
print('composer import ok')
PY
```

### Orchy — `helpers/blockstream.py`, `helpers/orchestrator.py`

Primary risks:

- Blockstream schema drift.
- Lazy import cycles with researcher/composer/widgets.
- Widget execution contract preservation.
- Classifier routing into search/widgets/uploads.
- Error/cancellation behavior.

Targeted tests:

```bash
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_classifier.py \
  tests/test_widgets \
  tests/test_uploads.py \
  tests/test_types.py
```

Affected integrated subset:

```bash
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_classifier.py \
  tests/test_widgets \
  tests/test_uploads.py \
  tests/test_searxng_client.py \
  tests/test_scraper.py \
  tests/test_extractor.py \
  tests/test_picker.py \
  tests/test_reranker.py \
  tests/test_types.py
```

Import smoke:

```bash
PYTHONPATH=/a0/plugins python - <<'PY'
from a0_fauxplexica.helpers import blockstream, orchestrator
print('blockstream/orchestrator import ok')
PY
```

### Pairwise integration checks

After two Wave 2 branches are candidates for merge, run the relevant pairwise checks before recommending the second merge.

#### Reggie + Compo

Focus: research output to composer input, citations, sources.

```bash
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_searxng_client.py \
  tests/test_scraper.py \
  tests/test_extractor.py \
  tests/test_picker.py \
  tests/test_reranker.py \
  tests/test_composer.py \
  tests/test_types.py
```

#### Reggie + Orchy

Focus: orchestrated research execution, block events, imports.

```bash
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_classifier.py \
  tests/test_searxng_client.py \
  tests/test_scraper.py \
  tests/test_extractor.py \
  tests/test_picker.py \
  tests/test_reranker.py \
  tests/test_widgets \
  tests/test_uploads.py \
  tests/test_types.py
```

#### Compo + Orchy

Focus: final answer block emission, style routing, widget/search result composition.

```bash
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
PYTHONPATH=/a0/plugins pytest -q \
  tests/test_classifier.py \
  tests/test_composer.py \
  tests/test_widgets \
  tests/test_uploads.py \
  tests/test_types.py
```

### Final Wave 2 combined validation

When Reggie, Compo, and Orchy are all integrated into a candidate branch:

```bash
cd /a0/plugins/a0_fauxplexica
PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests
PYTHONPATH=/a0/plugins pytest -q tests
PYTHONPATH=/a0/plugins python - <<'PY'
from a0_fauxplexica.helpers import blockstream, orchestrator, researcher, composer
print('wave2 imports ok')
PY
```

If tests pass and no validator endpoint is available, report Python validation as PASS and plugin-validator status as NOT RUN / blocked by endpoint-login limitation.

## 6. Recommended Wave 2 Merge Order

Provisional order, subject to branch-specific validation results:

1. Reggie first if it only adds/updates research internals and preserves existing shared types.
2. Compo second, because citation/source formatting should be checked against Reggie outputs.
3. Orchy last, because orchestrator/blockstream is the integration surface that wires classifier, widgets, uploads, researcher, and composer together.

Alternative:

- If Orchy defines foundational blockstream types needed by Reggie/Compo, merge Orchy first only after confirming it does not import not-yet-merged `researcher`/`composer` in a way that breaks main.

Merge recommendation rule:

- QA will recommend a merge command only after inspecting the completed branch/commit and running compileall, targeted tests, affected integrated subset, and import smoke checks.
- QA will not merge unless explicitly instructed.

## 7. Next Validation Trigger

Notify QA when any Wave 2 super completes and provide branch/commit:

- Reggie completion — branch/commit for `helpers/researcher.py` and `prompts/researcher_*.md`.
- Compo completion — branch/commit for `helpers/composer.py` and `prompts/composer_*.md`.
- Orchy completion — branch/commit for `helpers/blockstream.py` and `helpers/orchestrator.py`.

On notification, QA will:

1. Inspect the branch/commit.
2. Run `PYTHONPATH=/a0/plugins python -m compileall -q helpers tools tests`.
3. Run the branch targeted tests.
4. Run affected integrated subsets.
5. Run import smoke checks for lazy import/cycle detection.
6. Update this `QA_STATUS.md`.
7. Recommend a merge command if safe, without performing the merge unless explicitly instructed.
