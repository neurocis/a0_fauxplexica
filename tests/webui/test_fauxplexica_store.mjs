import { strict as assert } from 'node:assert';
import fs from 'node:fs';

const sourcePath = new URL('../../webui/fauxplexica-store.js', import.meta.url);
let source = fs.readFileSync(sourcePath, 'utf8');
source = source.replace(
  'import { createStore } from "/js/AlpineStore.js";',
  'const createStore = (name, store) => store;'
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const {
  parseNdjsonStream,
  classifyMode,
  buildSearchRequest,
  renderInlineCitations,
  normalizeRegistry,
  blocksToText,
} = await import(moduleUrl);

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


// Recon R1 fix 5.1 / 5.2: parser supports Vane top-level block/blockId and legacy data.block.
const envelopeStream = [
  JSON.stringify({ type: 'init', data: { query: 'q' } }),
  JSON.stringify({ type: 'block', block: { id: 'b1', type: 'text', data: { text: 'top-level' } } }),
  JSON.stringify({ type: 'updateBlock', blockId: 'b1', patch: [{ op: 'replace', path: '/data/text', value: 'patched-top' }] }),
  JSON.stringify({ type: 'block', data: { block: { id: 'b2', type: 'reasoning', data: { text: 'legacy' } } } }),
  JSON.stringify({ type: 'done', data: {} }),
].join('\n');
const envelopeEvents = parseNdjsonStream(envelopeStream);
assert.deepEqual(envelopeEvents.map(e => e.type), ['init', 'block', 'updateBlock', 'block', 'done']);
assert.equal(envelopeEvents[1].block.id, 'b1');
assert.equal(envelopeEvents[2].blockId, 'b1');
assert.deepEqual(envelopeEvents[2].patch[0], { op: 'replace', path: '/data/text', value: 'patched-top' });
assert.equal(envelopeEvents[3].data.block.id, 'b2');
console.log('WEBUI_RECON_R1_PARSER_OK');
