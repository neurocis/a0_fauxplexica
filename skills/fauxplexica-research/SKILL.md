---
name: fauxplexica-research
description: Run a Perplexity/Vane-style multi-source research pipeline with inline citations, query classification, SearxNG-backed web/academic/discussion search, scraping, reranking, and evidence-backed synthesis. Use when the user asks for deep research, a Perplexity-style answer, source synthesis, citation-bearing responses, or multi-hop investigation with references.
version: 0.2.0
tags:
  - research
  - citations
  - perplexity
  - perplexica
  - vane
  - searxng
  - synthesis
  - rag
triggers:
  - perplexity research
  - perplexica research
  - vane research
  - deep research
  - fauxplexica
  - perplexity-style answer
  - answer with citations
  - research and cite
  - cite sources
  - multi-source synthesis
  - research and synthesize
  - evidence-backed answer
---

# Fauxplexica Research Skill

Perplexity/Vane-style **deep research answer engine** powered by the `a0_fauxplexica` plugin pipeline.

## When to use

Load this skill whenever the user asks for an answer that needs **live web evidence with inline citations** — not from training-memory speculation. Typical triggers:

- *"Do deep research on …"*
- *"Give me a Perplexity-style / Perplexica / Vane research answer about …"*
- *"Answer with citations"*
- *"Compare X and Y across sources"*
- *"What are the latest developments / current state of …"*

## How it works

The Fauxplexica pipeline runs end-to-end:

1. **Classify** — query routed to a composer (general, coding, news, academic, people, recipe, science/math, translation, URL, weather, creative).
2. **Plan** — picker chooses sources (web / discussions / academic) and research mode (speed / balanced / quality).
3. **Search** — SearxNG federated search (BYO instance required).
4. **Scrape & extract** — fetches result pages, extracts main content.
5. **Rerank** — embedding-based cosine relevance ranking and dedup.
6. **Compose** — synthesizes the final answer with inline `[N]` bracket citations.
7. **Validate** — citation postprocess ensures every `[N]` resolves to a real source.

Optional **widgets** (weather, calculator, stock) auto-attach when relevant.

## Modes

| Mode | Behavior | When to use |
|---|---|---|
| **speed** | Shallow/fast, few sources | Quick factual lookups |
| **balanced** *(default)* | Parallel research, good citation coverage | Most queries |
| **quality** | Multi-hop, deeper extraction, more sources | Complex/important questions |

## Invocation

Use the plugin's tool directly:

```
fauxplexica_search:
  query: "<user question>"
  mode: balanced       # or "speed" / "quality"
```

Or the alias `fauxplexica_answer` (identical behavior, named for answer-style usage).

The `fauxplexica` agent profile is also available and pre-tuned for this pipeline.

## Prerequisites

- `a0_fauxplexica` plugin installed and enabled
- **SearxNG instance** configured (`searxng_url` in plugin config) — BYO; without it the pipeline cannot fetch sources
- Embedding model configured (defaults to project embedder)

## Output guarantees

- Inline `[N]` citations after each sourced claim
- No fabricated URLs, titles, dates, or quotes
- Tables/bullets where they improve clarity
- Concise direct answer first, evidence second

## See also

- `fauxplexica-uploads` — for RAG over user-uploaded files
- `fauxplexica-widgets` — for explicit user-driven widget calls
