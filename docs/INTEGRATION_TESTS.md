# A0_Fauxplexica Integration Tests

Integration tests live under `tests/integration/` and are skipped by default
unless required environment variables are present. They are intended for local
validation against real infrastructure, not deterministic CI.

## Reranker smoke

File: `tests/integration/test_reranker_smoke.py`

Required:

```bash
export SEARXNG_URL=http://198.18.88.12
```

Optional OpenAI-compatible embedding endpoint:

```bash
export EMBEDDING_BASE_URL=https://api.openai.com/v1
export EMBEDDING_API_KEY=sk-...
export EMBEDDING_MODEL=text-embedding-3-small
# optional
export EMBEDDING_TIMEOUT=30
```

Run:

```bash
PYTHONPATH=/a0/plugins pytest -q tests/integration -m integration
```

The embedding endpoint is OpenAI `/v1/embeddings` compatible. A trailing
`/embeddings` segment on `EMBEDDING_BASE_URL` is accepted; otherwise the helper
appends `/embeddings` automatically.

If the embedding variables are absent, the test falls back to a deterministic
bag-of-words pseudo-embedder. That fallback validates sorting, thresholding,
deduplication, top-k truncation, empty input, vector determinism, and the
reranker's graceful failure contract, but it does not validate semantic quality.

## Expected assertions

The reranker smoke validates:

- real SearxNG JSON search returns results
- ranked output is sorted by descending cosine similarity
- `top_k` is honored
- off-topic noise is filtered or does not enter the top strict results
- an injected near-duplicate is removed by `dedup_threshold`
- a failing embedder returns the documented fallback shape (`similarity=1.0`)
- empty input returns `[]`
- embedding the same query twice has self-cosine 1.0
