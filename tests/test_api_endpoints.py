from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = Path('/a0')
for p in (str(FRAMEWORK_ROOT), str(PLUGIN_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from api import providers as providers_api  # noqa: E402
from api import search as search_api  # noqa: E402


class DummyHandler:
    def __init__(self):
        self.contexts = []

    def use_context(self, ctxid, create_if_not_exists=True):
        self.contexts.append((ctxid, create_if_not_exists))
        return type('Ctx', (), {'id': ctxid, 'agent0': None})()


class DummyRequest:
    args = {}


@pytest.mark.asyncio
async def test_search_missing_query_returns_structured_400():
    out = await search_api.FauxplexicaSearch.process(DummyHandler(), {}, DummyRequest())
    assert out.status_code == 400
    payload = json.loads(out.get_data(as_text=True))
    assert payload['ok'] is False
    assert payload['error']['code'] == 'missing_query'


@pytest.mark.asyncio
async def test_search_delegates_to_orchestrator(monkeypatch):
    monkeypatch.setattr(search_api, '_load_config', lambda agent=None: {'searxng_url': 'http://searx.test', 'sources': {'web': True}, 'widgets_enabled': {'weather': True}})
    seen = {}

    async def fake_run(**kwargs):
        seen.update(kwargs)
        await kwargs['block_stream'].emit('init', {'query': kwargs['query'], 'mode': kwargs['mode']})
        await kwargs['block_stream'].emit_block('text', {'text': 'Answer'})
        await kwargs['block_stream'].close()
        return {
            'answer': 'Answer',
            'classification': {'style': {'primary_type': 'general'}},
            'sources': [{'title': 'T', 'url': 'https://x'}],
            'citations': [],
            'widgets': [],
            'mode': kwargs['mode'],
            'blocks': kwargs['block_stream'].all_blocks(),
        }

    monkeypatch.setattr(search_api, 'run_fauxplexica_search', fake_run)
    out = await search_api.FauxplexicaSearch.process(
        DummyHandler(),
        {'query': 'hello', 'mode': 'speed', 'enabled_sources': ['web'], 'enabled_widgets': ['weather'], 'chat_history': [], 'file_ids': ['f1']},
        DummyRequest(),
    )
    assert isinstance(out, dict)
    assert out['answer'] == 'Answer'
    assert out['mode'] == 'speed'
    assert seen['query'] == 'hello'
    assert seen['enabled_sources'] == {'web'}
    assert seen['file_ids'] == ['f1']


@pytest.mark.asyncio
async def test_search_stream_returns_ndjson_event_stream(monkeypatch):
    monkeypatch.setattr(search_api, '_load_config', lambda agent=None: {'searxng_url': 'http://searx.test'})

    async def fake_run(**kwargs):
        await kwargs['block_stream'].emit('init', {'query': kwargs['query']})
        await kwargs['block_stream'].emit('response', {'answer': 'A'})
        await kwargs['block_stream'].close()
        return {'answer': 'A', 'mode': kwargs['mode']}

    monkeypatch.setattr(search_api, 'run_fauxplexica_search', fake_run)
    out = await search_api.FauxplexicaSearch.process(DummyHandler(), {'query': 'q', 'stream': True}, DummyRequest())
    assert out.status_code == 200
    assert out.mimetype == 'text/event-stream'
    rows = [json.loads(line) for line in out.get_data(as_text=True).splitlines()]
    assert [row['type'] for row in rows] == ['init', 'response', 'done']


@pytest.mark.asyncio
async def test_search_missing_searx_config_when_sources_enabled(monkeypatch):
    monkeypatch.setattr(search_api, '_load_config', lambda agent=None: {'searxng_url': '', 'sources': {'web': True}})
    out = await search_api.FauxplexicaSearch.process(DummyHandler(), {'query': 'q'}, DummyRequest())
    assert out.status_code == 400
    assert json.loads(out.get_data(as_text=True))['error']['code'] == 'missing_searxng_url'


@pytest.mark.asyncio
async def test_providers_lists_configured_capabilities(monkeypatch):
    monkeypatch.setattr(providers_api, '_load_config', lambda agent=None: {
        'searxng_url': 'http://searx.test',
        'default_mode': 'quality',
        'sources': {'web': True, 'academic': False, 'discussions': True},
        'widgets_enabled': {'weather': False, 'calculator': True, 'stock': True},
    })
    monkeypatch.setattr(providers_api, '_load_model_registry', lambda: {'chat_providers': [{'value': 'x'}], 'embedding_providers': [], 'presets': []})
    out = await providers_api.FauxplexicaProviders.process(DummyHandler(), {}, DummyRequest())
    assert out['ok'] is True
    assert out['providers'][0]['configured'] is True
    assert {s['id']: s['enabled'] for s in out['sources']} == {'web': True, 'academic': False, 'discussions': True}
    labels = {s['id']: s['label'] for s in out['sources']}
    assert labels['discussions'] == 'Social'
    assert [m for m in out['modes'] if m['default']][0]['id'] == 'quality'
    assert out['model_registry']['chat_providers'][0]['value'] == 'x'
