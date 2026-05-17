---
name: fauxplexica-uploads
description: Index local files into the Fauxplexica per-chat-context upload namespace and answer questions over uploaded documents (RAG). Use when the user wants to ingest, index, attach, or query their own files (PDFs, text, code, docs) and get cited answers grounded in those files rather than the open web.
version: 0.2.0
tags:
  - rag
  - uploads
  - file-index
  - documents
  - private-knowledge
  - perplexica
  - fauxplexica
triggers:
  - upload to fauxplexica
  - index this file
  - index this pdf
  - ingest this document
  - add to fauxplexica
  - rag over my files
  - answer from my uploads
  - query my uploaded files
  - search my documents
  - private knowledge research
  - perplexica uploads
  - vane uploads
---

# Fauxplexica Uploads Skill

Index local files into the **Fauxplexica per-chat upload namespace** and answer questions over those files with inline citations — the same Perplexity/Vane-style synthesis as `fauxplexica-research`, but the source corpus is the user's documents rather than the open web.

## When to use

Load this skill when the user wants to:

- *"Index this PDF and answer questions about it"*
- *"Ingest these documents into Fauxplexica"*
- *"RAG over my uploaded files"*
- *"Search my docs for X"*
- *"Answer from my uploads, not the web"*

Useful for: research papers, contracts, manuals, codebases, meeting notes, internal docs, knowledge bases.

## How it works

1. **Upload** — `fauxplexica_upload` indexes one local file into the **current chat context's upload namespace**. Each chat has its own isolated upload corpus.
2. **Search** — `fauxplexica_uploads_search` performs embedding-based retrieval against the indexed chunks and returns the most relevant passages.
3. **Answer** — passages are fed to the composer with inline `[N]` citations referencing the source files.

## Invocation

### Index a file

```
fauxplexica_upload:
  path: "/absolute/path/to/file.pdf"
```

- Supported: PDFs, text, markdown, code files, and any format the extractor can read.
- Scope: isolated to the **current chat context** — other chats won't see these uploads.

### Query uploaded content

```
fauxplexica_uploads_search:
  query: "<question about uploaded files>"
```

Returns ranked chunks with source-file attribution.

### Combined: index then answer

Typical flow:
1. Call `fauxplexica_upload` once per file the user wants indexed.
2. Call `fauxplexica_uploads_search` (or have the main `fauxplexica_search` pipeline pick up uploads automatically) to answer.

## Prerequisites

- `a0_fauxplexica` plugin installed and enabled
- Embedding model configured (defaults to project embedder)
- The file must be accessible at an absolute path on the A0 host

## Output guarantees

- Citations reference the actual uploaded file (filename + chunk locator)
- No fabricated quotes or page numbers
- Empty corpus → clear "no uploads indexed for this chat" response, not hallucinated content

## See also

- `fauxplexica-research` — for web/academic source synthesis
- `fauxplexica-widgets` — for explicit weather/stock/calc widget calls
