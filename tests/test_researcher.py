import pytest

from helpers.researcher import ResearchOutput, dedupe_search_results, research
from helpers.types import ClassifierOutput, RoutingFlags, StyleHints, SearchResult


class DummyEmbedder:
    async def aembed_query(self, text):
        # Same dimensionality; enough for deterministic reranker behavior.
        lower = (text or '').lower()
        return [1.0, 0.0] if 'alpha' in lower or 'query' in lower else [0.8, 0.2]


class DummyLLM:
    async def structured(self, prompt, schema=None):
        return {"picked_indices": [0, 1]}


class DummyBlockStream:
    def __init__(self):
        self.events = []

    async def emit(self, payload):
        self.events.append(payload)


class DummyAgentContext:
    id = 'ctx1'


def classifier(*, academic=False, discussion=False, personal=False, freshness='any'):
    return ClassifierOutput(
        routing=RoutingFlags(
            skip_search=False,
            personal_search=personal,
            academic_search=academic,
            discussion_search=discussion,
        ),
        style=StyleHints(freshness=freshness),
        standalone_followup='query',
    )


@pytest.mark.asyncio
async def test_speed_mode_searx_reranked_deduped(monkeypatch):
    async def fake_search(self, query, **kwargs):
        return [
            {"title": "A", "url": "https://a.test", "content": "alpha query content", "engine": "e"},
            {"title": "A2", "url": "https://a.test", "content": "alpha query more", "engine": "e"},
            {"title": "B", "url": "https://b.test", "content": "beta", "engine": "e"},
        ]

    monkeypatch.setattr('helpers.researcher.SearxClient.search', fake_search)
    out = await research(
        query='alpha query',
        classification=classifier(),
        chat_history=[],
        mode='speed',
        enabled_sources={'web'},
        file_ids=None,
        llm=DummyLLM(),
        embedder=DummyEmbedder(),
        config={'searxng_url': 'http://searx.test', 'rerank': {'cosine_keep_threshold': 0.0, 'cosine_dedup_threshold': 0.99}},
    )

    assert isinstance(out, ResearchOutput)
    assert [r.url for r in out.search_findings] == ['https://a.test', 'https://b.test']
    assert 'alpha query more' in out.search_findings[0].content
    assert any(s.type == 'reasoning' for s in out.steps)


@pytest.mark.asyncio
async def test_balanced_mode_iteration_guard_and_empty_tool_done(monkeypatch):
    calls = 0

    async def fake_search(self, query, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr('helpers.researcher.SearxClient.search', fake_search)
    out = await research(
        query='query',
        classification=classifier(),
        chat_history=[],
        mode='balanced',
        enabled_sources={'web'},
        file_ids=None,
        llm=DummyLLM(),
        embedder=DummyEmbedder(),
        config={'searxng_url': 'http://searx.test'},
    )

    assert calls == 1
    assert out.search_findings == []
    assert any('implicit' in s.data.get('summary', '') or 'No applicable' in s.data.get('summary', '') for s in out.steps)
    assert len([s for s in out.steps if s.type == 'reasoning']) <= 6


@pytest.mark.asyncio
async def test_quality_mode_picker_scrape_extractor_path(monkeypatch):
    async def fake_search(self, query, **kwargs):
        return [
            {"title": "One", "url": "https://one.test", "content": "snippet one", "engine": "e"},
            {"title": "Two", "url": "https://two.test", "content": "snippet two", "engine": "e"},
        ]

    async def fake_pick(query, results, llm, *, max_picks=3):
        return [1]

    async def fake_scrape(url, **kwargs):
        return 'scraped page text'

    async def fake_extract(url, content, query, llm, *, semaphore):
        return 'extracted facts for ' + url

    monkeypatch.setattr('helpers.researcher.SearxClient.search', fake_search)
    monkeypatch.setattr('helpers.researcher.pick_results', fake_pick)
    monkeypatch.setattr('helpers.researcher.scrape_page_url', fake_scrape)
    monkeypatch.setattr('helpers.researcher.extract_facts', fake_extract)

    out = await research(
        query='query',
        classification=classifier(),
        chat_history=[],
        mode='quality',
        enabled_sources={'web'},
        file_ids=None,
        llm=DummyLLM(),
        embedder=DummyEmbedder(),
        config={'searxng_url': 'http://searx.test', 'scrape_extractor_concurrency': 2},
    )

    assert [r.url for r in out.search_findings] == ['https://two.test']
    assert out.search_findings[0].content == 'extracted facts for https://two.test'
    assert any(s.type == 'reading' for s in out.steps)
    assert any(s.type == 'source' for s in out.steps)


@pytest.mark.asyncio
async def test_uploads_search_invoked_with_file_ids_even_without_personal_flag(monkeypatch):
    called = False

    async def fake_upload_search(self, query, file_ids=None, *, k=8):
        nonlocal called
        called = True
        assert file_ids == ['f1']
        return [{"content": "upload content", "metadata": {"file_id": "f1", "filename": "doc.txt", "chunk_index": 0}, "score": 0.9}]

    monkeypatch.setattr('helpers.researcher.UploadsManager.search', fake_upload_search)
    out = await research(
        query='query',
        classification=classifier(personal=False),
        chat_history=[],
        mode='balanced',
        enabled_sources=set(),
        file_ids=['f1'],
        llm=DummyLLM(),
        embedder=DummyEmbedder(),
        config={},
        agent_context=DummyAgentContext(),
    )

    assert called is True
    assert out.search_findings[0].engine == 'uploads'
    assert out.search_findings[0].content == 'upload content'


def test_url_dedup_content_concat_preserves_order():
    out = dedupe_search_results([
        SearchResult(title='A', url='https://a.test', content='first'),
        SearchResult(title='B', url='https://b.test', content='second'),
        SearchResult(title='A2', url='https://a.test', content='third'),
    ])
    assert [r.url for r in out] == ['https://a.test', 'https://b.test']
    assert out[0].content == 'first\n\nthird'
    assert out[0].title == 'A'


@pytest.mark.asyncio
async def test_block_stream_optional_noop_and_emit(monkeypatch):
    async def fake_search(self, query, **kwargs):
        return [{"title": "A", "url": "https://a.test", "content": "alpha query", "engine": "e"}]

    monkeypatch.setattr('helpers.researcher.SearxClient.search', fake_search)
    # None should no-op without raising.
    await research(
        query='alpha query', classification=classifier(), chat_history=[], mode='speed', enabled_sources={'web'},
        file_ids=None, llm=DummyLLM(), embedder=DummyEmbedder(), config={'searxng_url': 'http://searx.test'}
    )
    stream = DummyBlockStream()
    await research(
        query='alpha query', classification=classifier(), chat_history=[], mode='speed', enabled_sources={'web'},
        file_ids=None, llm=DummyLLM(), embedder=DummyEmbedder(), config={'searxng_url': 'http://searx.test'}, block_stream=stream
    )
    assert stream.events
    assert stream.events[0]['type'] == 'reasoning'


@pytest.mark.asyncio
async def test_dependency_failure_graceful_fallback(monkeypatch):
    async def bad_search(self, query, **kwargs):
        raise RuntimeError('network down')

    monkeypatch.setattr('helpers.researcher.SearxClient.search', bad_search)
    out = await research(
        query='query',
        classification=classifier(),
        chat_history=[],
        mode='balanced',
        enabled_sources={'web'},
        file_ids=None,
        llm=DummyLLM(),
        embedder=DummyEmbedder(),
        config={'searxng_url': 'http://searx.test'},
    )
    assert out.search_findings == []
    assert any('failed' in s.data.get('summary', '') for s in out.steps)
