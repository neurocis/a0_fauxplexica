from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from unittest.mock import AsyncMock, patch

import pytest
from plugins.a0_fauxplexica.helpers.uploads import Document, UploadsManager


class FakeDB:
    def __init__(self):
        self.docs = {}

    def get_all_docs(self):
        return self.docs


class FakeMemory:
    def __init__(self):
        self.db = FakeDB()
        self.inserted = []
        self.deleted_ids = []
        self.search_calls = []

    async def insert_documents(self, docs):
        ids = [f"doc-{i}" for i, _doc in enumerate(docs)]
        for doc, doc_id in zip(docs, ids):
            doc.metadata["id"] = doc_id
            self.db.docs[doc_id] = doc
        self.inserted.extend(docs)
        return ids

    async def search_similarity_threshold(self, query, limit, threshold, filter=""):
        self.search_calls.append((query, limit, threshold, filter))
        return list(self.db.docs.values())[:limit]

    async def delete_documents_by_ids(self, ids):
        self.deleted_ids.extend(ids)
        removed = []
        for doc_id in ids:
            doc = self.db.docs.pop(doc_id, None)
            if doc is not None:
                removed.append(doc)
        return removed


@pytest.fixture
def context():
    agent = SimpleNamespace(context=SimpleNamespace(log=SimpleNamespace(log=lambda **kwargs: None)))
    ctx = SimpleNamespace(id="ctx123", agent0=agent)
    ctx.get_agent = lambda: agent
    return ctx


@pytest.mark.asyncio
async def test_ingest_txt_uses_context_scoped_memory_and_metadata(tmp_path, context):
    fake_memory = FakeMemory()
    path = tmp_path / "notes.txt"
    path.write_text("hello uploaded world", encoding="utf-8")

    with patch("plugins.a0_fauxplexica.helpers.uploads.get_uploads_memory", new=AsyncMock(return_value=fake_memory)) as get_by_subdir:
        manager = UploadsManager(context)
        file_id = await manager.ingest_file(str(path), file_id="file-1")

    assert file_id == "file-1"
    get_by_subdir.assert_awaited_once()
    assert get_by_subdir.await_args.args[0] == "fauxplexica_uploads/ctx123"
    assert len(fake_memory.inserted) == 1
    doc = fake_memory.inserted[0]
    assert doc.page_content == "hello uploaded world"
    assert doc.metadata["area"] == "fauxplexica_uploads"
    assert doc.metadata["file_id"] == "file-1"
    assert doc.metadata["filename"] == "notes.txt"
    assert doc.metadata["chunk_index"] == 0
    assert doc.metadata["total_chunks"] == 1
    assert manager.last_ingest_result["chunks_indexed"] == 1
    assert doc.metadata["url"] == "file_id://file-1"


@pytest.mark.asyncio
async def test_search_applies_file_id_override_filter(context):
    fake_memory = FakeMemory()
    fake_memory.db.docs["doc-1"] = Document(
        page_content="alpha content",
        metadata={"id": "doc-1", "area": "fauxplexica_uploads", "file_id": "f1", "filename": "a.txt"},
    )

    with patch("plugins.a0_fauxplexica.helpers.uploads.get_uploads_memory", new=AsyncMock(return_value=fake_memory)):
        manager = UploadsManager(context)
        results = await manager.search("alpha", ["f1", "f2"], k=3)

    assert results[0]["content"] == "alpha content"
    assert results[0]["metadata"]["file_id"] == "f1"
    assert fake_memory.search_calls[0][1] == 3
    assert "file_id in ['f1', 'f2']" in fake_memory.search_calls[0][3]


@pytest.mark.asyncio
async def test_list_and_remove_files(context):
    fake_memory = FakeMemory()
    fake_memory.db.docs["doc-1"] = Document(page_content="a", metadata={"id": "doc-1", "area": "fauxplexica_uploads", "file_id": "f1", "filename": "a.txt", "total_chunks": 2})
    fake_memory.db.docs["doc-2"] = Document(page_content="b", metadata={"id": "doc-2", "area": "fauxplexica_uploads", "file_id": "f1", "filename": "a.txt", "total_chunks": 2})
    fake_memory.db.docs["doc-3"] = Document(page_content="c", metadata={"id": "doc-3", "area": "main", "file_id": "other"})

    with patch("plugins.a0_fauxplexica.helpers.uploads.get_uploads_memory", new=AsyncMock(return_value=fake_memory)):
        manager = UploadsManager(context)
        files = await manager.list_files()
        removed = await manager.remove_file("f1")

    assert files == [{"file_id": "f1", "filename": "a.txt", "source_path": "", "mime_type": "", "chunk_count": 2, "total_chunks": 2}]
    assert removed == 2
    assert sorted(fake_memory.deleted_ids) == ["doc-1", "doc-2"]
    assert "doc-3" in fake_memory.db.docs


@pytest.mark.asyncio
async def test_unsupported_image_returns_error(tmp_path, context):
    fake_memory = FakeMemory()
    path = tmp_path / "image.png"
    path.write_bytes(b"not really an image")

    with patch("plugins.a0_fauxplexica.helpers.uploads.get_uploads_memory", new=AsyncMock(return_value=fake_memory)):
        manager = UploadsManager(context)
        result = await manager.ingest_file(str(path))

    assert isinstance(result, dict)
    assert "Image uploads are deferred" in result["error"]
    assert fake_memory.inserted == []


class StubMemory:
    def __init__(self, results_per_query):
        self._results = results_per_query
        self.calls = []

    async def search_similarity_threshold(self, query, limit, threshold, filter=""):
        self.calls.append((query, limit, filter))
        return list(self._results.get(query, []))


@pytest.mark.asyncio
async def test_search_fuses_multi_query_results_with_rrf(context):
    doc1 = Document(page_content="A", metadata={"id": "d1", "file_id": "f1", "url": "file_id://f1"})
    doc2 = Document(page_content="B", metadata={"id": "d2", "file_id": "f2", "url": "file_id://f2"})
    doc3 = Document(page_content="C", metadata={"id": "d3", "file_id": "f3", "url": "file_id://f3"})
    memory = StubMemory({
        "q1": [doc1, doc2],
        "q2": [doc2, doc3],
    })

    with patch("plugins.a0_fauxplexica.helpers.uploads.get_uploads_memory", new=AsyncMock(return_value=memory)):
        manager = UploadsManager(context)
        fused = await manager.search(["q1", "q2"], k=3)

    ids = [item["metadata"]["id"] for item in fused]
    assert ids[0] == "d2"
    assert set(ids) == {"d1", "d2", "d3"}
    rrf_scores = {item["metadata"]["id"]: item["rrf_score"] for item in fused}
    assert rrf_scores["d2"] > rrf_scores["d1"]
    assert rrf_scores["d2"] > rrf_scores["d3"]
    assert [call[0] for call in memory.calls] == ["q1", "q2"]


@pytest.mark.asyncio
async def test_search_single_query_returns_results_without_rrf_score(context):
    doc = Document(page_content="A", metadata={"id": "d1", "file_id": "f1"})
    memory = StubMemory({"q": [doc]})
    with patch("plugins.a0_fauxplexica.helpers.uploads.get_uploads_memory", new=AsyncMock(return_value=memory)):
        manager = UploadsManager(context)
        results = await manager.search("q", k=2)
    assert results[0]["metadata"]["id"] == "d1"
    assert "rrf_score" not in results[0]
