import { strict as assert } from 'node:assert';
import {
  parseNdjsonStream,
  classifyMode,
  buildSearchRequest,
  renderInlineCitations,
  normalizeRegistry,
  blocksToText,
} from '../../webui/fauxplexica-store.js';

const stream = ['{"type":"init","data":{"query":"q"}}','{"type":"response","data":{"answer":"a"}}','{"type":"done","data":{}}'].join('\n');
const events = parseNdjsonStream(stream);
assert.deepEqual(events.map(e=>e.type), ['init','response','done']);
const bad = parseNdjsonStream('not-json');
assert.equal(bad.length, 1);
assert.equal(bad[0].type, 'error');
assert.equal(bad[0].data.code, 'bad_json');

assert.equal(classifyMode('Quality'), 'quality');
assert.equal(classifyMode('xx'), 'balanced');
assert.equal(classifyMode(null), 'balanced');

const body = buildSearchRequest({ query: ' hello ', mode: 'speed', stream: true, sources: new Set(['web']), widgets: new Set(['weather']), chatHistory: [{role:'user',text:'hi'}], fileIds: ['f1'] });
assert.equal(body.query, 'hello');
assert.equal(body.mode, 'speed');
assert.equal(body.stream, true);
assert.deepEqual(body.enabled_sources, ['web']);
assert.deepEqual(body.enabled_widgets, ['weather']);
assert.deepEqual(body.file_ids, ['f1']);
assert.equal(body.chat_history[0].text, 'hi');

const registry = normalizeRegistry([{ title:'T', url:'https://x', snippet:'s', source:'web', score:'0.9' }, { url:'https://y' }]);
assert.equal(registry.length, 2);
assert.equal(registry[0].index, 1);
assert.equal(registry[0].score, 0.9);
assert.equal(registry[1].title, 'https://y');

const html = renderInlineCitations('Alpha [1] beta [9] gamma.', registry);
assert.ok(html.includes('href="#fpx-source-1"'));
assert.ok(!html.includes('[9]'));
assert.ok(html.includes('beta '));

assert.equal(blocksToText([{type:'text',data:{text:'x'}}]), 'x');
assert.equal(blocksToText([]), '');
console.log('WEBUI_STORE_TESTS_OK');
