"""Live integration tests.

These tests are skipped by default. They require external services to be
reachable and configured via environment variables:

- ``SEARXNG_URL``: A SearxNG instance with ``search.formats: [html, json]``
  in its ``settings.yml``. Required by every integration test in this package.
- ``EMBEDDING_BASE_URL``, ``EMBEDDING_API_KEY``, ``EMBEDDING_MODEL``: An
  OpenAI-compatible embeddings endpoint (e.g. OpenAI, Ollama with ``/v1``,
  vLLM, LiteLLM). Optional; when set the reranker smoke uses real semantic
  vectors. When unset, the smoke falls back to a deterministic bag-of-words
  pseudo-embedder so the rerank *machinery* is still exercised end-to-end.

These tests do not run in CI by default. To run locally:

.. code-block:: bash

    SEARXNG_URL=http://198.18.88.12 \
    EMBEDDING_BASE_URL=https://api.openai.com/v1 \
    EMBEDDING_API_KEY=sk-... \
    EMBEDDING_MODEL=text-embedding-3-small \
    PYTHONPATH=/a0/plugins pytest -q tests/integration -m integration
"""
