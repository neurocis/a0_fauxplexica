// A0_Fauxplexica WebUI store and renderer.
// Implements Phase 1 search panel, blockstream renderer, citation sidebar,
// uploads hooks, and providers/config panel.

const API_BASE = "/api/plugins/a0_fauxplexica";
const BLOCK_EVENTS = new Set(["init", "block", "updateBlock", "researchComplete", "response", "messageEnd", "done", "error"]);

const CITATION_RE = /\[(\d+)\]/g;

export function parseNdjsonStream(text) {
  if (!text) return [];
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line); } catch { return { type: "error", data: { code: "bad_json", message: line } }; }
    })
    .filter((evt) => evt && BLOCK_EVENTS.has(String(evt.type || "")));
}

export function renderInlineCitations(answer, registry, onClick) {
  const indices = new Set((registry || []).map((r) => Number(r.index)));
  return String(answer || "").replace(CITATION_RE, (match, idx) => {
    const n = Number(idx);
    if (!indices.has(n)) return "";
    const safeOn = (typeof onClick === "function") ? `data-cite="${n}"` : `data-cite="${n}"`;
    return `<a class="fpx-cite" href="#fpx-source-${n}" ${safeOn}>[${n}]</a>`;
  });
}

export function classifyMode(value) {
  const v = String(value || "balanced").toLowerCase();
  return ["speed", "balanced", "quality"].includes(v) ? v : "balanced";
}

export function buildSearchRequest({ query, mode, stream, sources, widgets, chatHistory, fileIds }) {
  return {
    query: String(query || "").trim(),
    mode: classifyMode(mode),
    stream: !!stream,
    enabled_sources: Array.from(sources || []),
    enabled_widgets: Array.from(widgets || []),
    chat_history: Array.isArray(chatHistory) ? chatHistory : [],
    file_ids: Array.isArray(fileIds) ? fileIds.map(String) : [],
  };
}

export function blocksToText(blocks) {
  if (!Array.isArray(blocks)) return "";
  const text = blocks.find((b) => b && b.type === "text");
  if (text && text.data && typeof text.data.text === "string") return text.data.text;
  return "";
}

export async function fetchProviders() {
  const res = await fetch(`${API_BASE}/providers`, { method: "GET", credentials: "include" });
  if (!res.ok) throw new Error(`providers: HTTP ${res.status}`);
  return res.json();
}

export async function postSearch(body, { signal } = {}) {
  const res = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
    signal,
  });
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("text/event-stream")) {
    const text = await res.text();
    return { kind: "stream", status: res.status, events: parseNdjsonStream(text) };
  }
  const data = await res.json().catch(() => ({}));
  return { kind: data && data.ok === false ? "error" : "answer", status: res.status, data };
}

export async function postUpload(filePath) {
  const res = await fetch(`${API_BASE}/tools/fauxplexica_upload`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ file_path: filePath }),
  });
  return res.json().catch(() => ({ error: "bad_response" }));
}

export async function postUploadsSearch(query, fileIds) {
  const res = await fetch(`${API_BASE}/tools/fauxplexica_uploads_search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ query, file_ids: fileIds || [] }),
  });
  return res.json().catch(() => ({ error: "bad_response" }));
}

function el(id) { return document.getElementById(id); }
function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.substring(2).toLowerCase(), v);
    else if (v === false || v === null || v === undefined) continue;
    else node.setAttribute(k, v);
  }
  for (const kid of kids) {
    if (kid === null || kid === undefined) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function renderSourceToggles(container, items, selected, onChange) {
  container.innerHTML = "";
  for (const item of items || []) {
    const id = String(item.id || item.label || "");
    if (!id) continue;
    const pressed = selected.has(id);
    const chip = h("button", {
      type: "button",
      class: "fpx-chip",
      "data-id": id,
      "aria-pressed": String(pressed),
    }, item.label || id);
    chip.addEventListener("click", () => {
      if (selected.has(id)) selected.delete(id); else selected.add(id);
      chip.setAttribute("aria-pressed", String(selected.has(id)));
      onChange && onChange(new Set(selected));
    });
    container.append(chip);
  }
}

function renderBlocks(target, blocks) {
  target.innerHTML = "";
  for (const b of blocks || []) {
    const t = b && b.type ? String(b.type) : "text";
    if (t === "text") continue;
    const label = h("div", { class: "fpx-meta" }, t);
    const data = h("pre", { class: "fpx-block", "data-type": t }, JSON.stringify(b && b.data ? b.data : {}, null, 2));
    target.append(label, data);
  }
}

function citationCard(record, isActive) {
  const tpl = document.getElementById("fauxplexica-citation-card");
  const card = tpl && tpl.content ? tpl.content.firstElementChild.cloneNode(true) : h("article", { class: "fauxplexica-citation-card" });
  card.dataset.index = String(record.index);
  card.id = `fpx-source-${record.index}`;
  if (isActive) card.classList.add("active");
  const title = card.querySelector(".fpx-cite-title");
  if (title) { title.textContent = record.title || record.url || `Source ${record.index}`; title.href = record.url || "#"; }
  const badge = card.querySelector(".fpx-cite-badge");
  if (badge) badge.textContent = `[${record.index}]`;
  const snippet = card.querySelector(".fpx-cite-snippet");
  if (snippet) snippet.textContent = record.snippet || "";
  const sourceEl = card.querySelector(".fpx-cite-source");
  if (sourceEl) sourceEl.textContent = record.source || "";
  const scoreEl = card.querySelector(".fpx-cite-score");
  if (scoreEl && record.score != null) scoreEl.textContent = `score ${Number(record.score).toFixed(2)}`;
  return card;
}

function renderSidebar(target, registry, activeIndex) {
  target.innerHTML = "";
  for (const rec of registry || []) {
    target.append(citationCard(rec, Number(rec.index) === Number(activeIndex)));
  }
}

function renderAnswer(target, answer, registry, onCitationClick) {
  if (!target) return;
  target.style.display = answer ? "" : "none";
  if (!answer) { target.innerHTML = ""; return; }
  target.innerHTML = renderInlineCitations(answer, registry, onCitationClick);
  target.querySelectorAll(".fpx-cite").forEach((a) => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const idx = Number(a.getAttribute("data-cite")) || 0;
      onCitationClick && onCitationClick(idx);
    });
  });
}

function setStatus(text, isError) {
  const el = document.getElementById("fpx-status");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("fpx-error", !!isError);
}

function surfaceMissingSearx(providers, warningEl) {
  if (!warningEl) return;
  const searx = (providers.providers || []).find((p) => p.id === "searxng");
  if (searx && !searx.configured) {
    warningEl.hidden = false;
    warningEl.textContent = "SearxNG URL is not configured. Set 'searxng_url' in the plugin settings to enable web/academic search.";
  } else {
    warningEl.hidden = true;
  }
}

export async function renderConfigPanel(container) {
  container.innerHTML = "";
  try {
    const providers = await fetchProviders();
    const summary = h("pre", { class: "fpx-block" }, JSON.stringify({
      providers: providers.providers,
      sources: providers.sources,
      widgets: providers.widgets,
      modes: providers.modes,
      limits: providers.limits,
    }, null, 2));
    container.append(summary);
  } catch (err) {
    container.append(h("div", { class: "fpx-error" }, `Failed to load providers: ${err.message}`));
  }
}

export async function initPanel({ root = document } = {}) {
  const form = root.getElementById ? root.getElementById("fpx-form") : document.getElementById("fpx-form");
  if (!form) return null;
  const queryEl = el("fpx-query");
  const streamEl = el("fpx-stream");
  const submitEl = el("fpx-submit");
  const cancelEl = el("fpx-cancel");
  const blocksEl = el("fpx-blocks");
  const answerEl = el("fpx-answer");
  const sidebarEl = el("fpx-citations");
  const summaryEl = el("fpx-summary");
  const warningEl = el("fpx-config-warning");
  const modeBtns = Array.from(document.querySelectorAll("#fpx-modes .fpx-btn[data-mode]"));
  const sourcesEl = el("fpx-sources");
  const widgetsEl = el("fpx-widgets");

  const state = {
    mode: "balanced",
    sources: new Set(["web", "academic"]),
    widgets: new Set(["weather", "calculator", "stock"]),
    fileIds: [],
    registry: [],
    activeIndex: null,
    abortController: null,
  };

  modeBtns.forEach((btn) => btn.addEventListener("click", () => {
    state.mode = classifyMode(btn.getAttribute("data-mode"));
    modeBtns.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
  }));

  try {
    const providers = await fetchProviders();
    state.mode = classifyMode((providers.modes || []).find((m) => m.default)?.id || "balanced");
    modeBtns.forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-mode") === state.mode)));
    state.sources = new Set((providers.sources || []).filter((s) => s.enabled).map((s) => String(s.id)));
    state.widgets = new Set((providers.widgets || []).filter((w) => w.enabled).map((w) => String(w.id)));
    renderSourceToggles(sourcesEl, providers.sources || [], state.sources, (next) => { state.sources = next; });
    renderSourceToggles(widgetsEl, providers.widgets || [], state.widgets, (next) => { state.widgets = next; });
    surfaceMissingSearx(providers, warningEl);
  } catch (err) {
    setStatus(`Failed to load providers: ${err.message}`, true);
  }

  const onCitationClick = (idx) => {
    state.activeIndex = idx;
    renderSidebar(sidebarEl, state.registry, state.activeIndex);
    renderAnswer(answerEl, answerEl.dataset.answer || "", state.registry, onCitationClick);
  };

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const query = String(queryEl.value || "").trim();
    if (!query) return;
    submitEl.disabled = true;
    cancelEl.disabled = false;
    setStatus("Searching…");
    answerEl.innerHTML = "";
    answerEl.dataset.answer = "";
    state.registry = [];
    sidebarEl.innerHTML = "";
    blocksEl.innerHTML = "";
    summaryEl.textContent = "";
    const body = buildSearchRequest({
      query,
      mode: state.mode,
      stream: streamEl.checked,
      sources: state.sources,
      widgets: state.widgets,
      chatHistory: [],
      fileIds: state.fileIds,
    });
    state.abortController = new AbortController();
    try {
      const result = await postSearch(body, { signal: state.abortController.signal });
      if (result.kind === "stream") {
        let answer = "";
        let mode = body.mode;
        let blocks = [];
        for (const evt of result.events) {
          if (evt.type === "block" && evt.data && evt.data.type === "text" && evt.data.data && typeof evt.data.data.text === "string") answer = evt.data.data.text;
          if (evt.type === "updateBlock" && evt.data && Array.isArray(evt.data.ops)) {
            const replace = evt.data.ops.find((op) => op && op.op === "replace" && op.path === "/text");
            if (replace && typeof replace.value === "string") answer = replace.value;
          }
          if (evt.type === "response" && evt.data && typeof evt.data.answer === "string") answer = evt.data.answer;
          if (evt.type === "researchComplete" && evt.data && Array.isArray(evt.data.sources)) state.registry = normalizeRegistry(evt.data.sources);
          if (evt.type === "error" && evt.data && evt.data.message) setStatus(`Error: ${evt.data.message}`, true);
          blocks.push(evt);
        }
        if (!state.registry.length) state.registry = normalizeRegistry(extractSources(blocks));
        answerEl.dataset.answer = answer;
        renderAnswer(answerEl, answer, state.registry, onCitationClick);
        renderSidebar(sidebarEl, state.registry, state.activeIndex);
        renderBlocks(blocksEl, blocks);
        summaryEl.textContent = `${state.registry.length} source(s) • mode ${mode}`;
        setStatus("Done.");
      } else if (result.kind === "answer") {
        const data = result.data || {};
        state.registry = normalizeRegistry(data.sources || []);
        answerEl.dataset.answer = data.answer || "";
        renderAnswer(answerEl, data.answer || "", state.registry, onCitationClick);
        renderSidebar(sidebarEl, state.registry, state.activeIndex);
        renderBlocks(blocksEl, data.blocks || []);
        summaryEl.textContent = `${state.registry.length} source(s) • mode ${data.mode || body.mode}`;
        setStatus("Done.");
      } else {
        const data = result.data || {};
        const message = data && data.error && data.error.message ? data.error.message : `HTTP ${result.status}`;
        setStatus(`Error: ${message}`, true);
      }
    } catch (err) {
      if (err && err.name === "AbortError") setStatus("Cancelled."); else setStatus(`Error: ${err.message}`, true);
    } finally {
      submitEl.disabled = false;
      cancelEl.disabled = true;
    }
  });

  cancelEl.addEventListener("click", () => {
    if (state.abortController) state.abortController.abort();
  });

  el("fpx-upload-btn").addEventListener("click", async () => {
    const path = String(el("fpx-upload-path").value || "").trim();
    if (!path) return;
    el("fpx-upload-status").textContent = `Uploading ${path}…`;
    const res = await postUpload(path);
    if (res && res.file_id) {
      state.fileIds.push(String(res.file_id));
      el("fpx-upload-status").textContent = `Indexed ${res.filename || path} (${res.chunks_indexed || 0} chunks)`;
    } else {
      el("fpx-upload-status").textContent = `Upload error: ${res && res.error ? res.error : "unknown"}`;
    }
  });

  el("fpx-uploads-search-btn").addEventListener("click", async () => {
    const q = String(el("fpx-uploads-query").value || "").trim();
    if (!q) return;
    const res = await postUploadsSearch(q, state.fileIds);
    el("fpx-uploads-results").textContent = JSON.stringify(res && res.results ? res.results : res, null, 2);
  });

  return state;
}

function extractSources(events) {
  for (const evt of events || []) {
    if (evt && evt.type === "researchComplete" && evt.data && Array.isArray(evt.data.sources)) return evt.data.sources;
  }
  return [];
}

export function normalizeRegistry(sources) {
  const out = [];
  let i = 1;
  for (const raw of sources || []) {
    if (!raw || typeof raw !== "object") continue;
    out.push({
      index: raw.index || i,
      title: raw.title || raw.name || raw.url || `Source ${raw.index || i}`,
      url: raw.url || raw.link || "",
      snippet: raw.snippet || raw.content || "",
      source: raw.source || raw.provider || raw.engine || "web",
      score: typeof raw.score === "number" ? raw.score : (raw.score != null ? Number(raw.score) : null),
    });
    i += 1;
  }
  return out;
}

export const FauxplexicaStore = {
  parseNdjsonStream,
  renderInlineCitations,
  classifyMode,
  buildSearchRequest,
  blocksToText,
  normalizeRegistry,
};

if (typeof window !== "undefined" && typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { initPanel().catch((err) => console.error("Fauxplexica init failed", err)); });
  } else {
    initPanel().catch((err) => console.error("Fauxplexica init failed", err));
  }
}
