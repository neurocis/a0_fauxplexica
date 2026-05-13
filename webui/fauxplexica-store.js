// A0_Fauxplexica WebUI store.
//
// Phase 2 design: the modal does NOT run the research pipeline itself. Instead
// it composes a `fauxplexica_search` tool-call request and dispatches it into
// the chat the user currently has open, so the user sees the full mechanics —
// tool call, retrieval, citations, composed answer — directly in the conversation.
//
// Pure functions below remain exported for unit tests so existing WebUI
// store tests keep passing.

import { createStore } from "/js/AlpineStore.js";

const BLOCK_EVENTS = new Set([
  "init", "block", "updateBlock", "researchComplete",
  "response", "messageEnd", "done", "error",
]);

const CITATION_RE = /\[(\d+)\]/g;

export function parseNdjsonStream(text) {
  if (!text) return [];
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line); }
      catch { return { type: "error", data: { code: "bad_json", message: line } }; }
    })
    .filter((evt) => evt && BLOCK_EVENTS.has(String(evt.type || "")));
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

export function renderInlineCitations(answer, registry) {
  const indices = new Set((registry || []).map((r) => Number(r.index)));
  return String(answer || "").replace(CITATION_RE, (match, idx) => {
    const n = Number(idx);
    if (!indices.has(n)) return "";
    return `<a class="fpx-cite" href="#fpx-source-${n}" data-cite="${n}">[${n}]</a>`;
  });
}

export function normalizeRegistry(items) {
  const out = [];
  let i = 1;
  for (const it of items || []) {
    if (!it) continue;
    const url = String(it.url || it.link || "").trim();
    if (!url) continue;
    const title = String(it.title || url).trim();
    const snippet = String(it.snippet || it.content || "").trim();
    const source = String(it.source || it.origin || "web").trim();
    const score = Number(it.score ?? it.similarity ?? 0) || 0;
    out.push({ index: i, url, title, snippet, source, score });
    i += 1;
  }
  return out;
}

export function blocksToText(blocks) {
  if (!Array.isArray(blocks)) return "";
  const text = blocks.find((b) => b && b.type === "text");
  if (text && text.data && typeof text.data.text === "string") return text.data.text;
  return "";
}

export const FauxplexicaStore = {
  parseNdjsonStream,
  renderInlineCitations,
  classifyMode,
  buildSearchRequest,
  blocksToText,
  normalizeRegistry,
};

// ---------------------------------------------------------------------------
// Alpine store for the modal — dispatches the tool call into the open chat.
// ---------------------------------------------------------------------------

const SOURCE_OPTIONS = [
  { id: "web", label: "Web" },
  { id: "academic", label: "Academic" },
  { id: "discussions", label: "Social / Discussions" },
];

const WIDGET_OPTIONS = [
  { id: "weather", label: "Weather" },
  { id: "calculator", label: "Calculator" },
  { id: "stock", label: "Stock" },
];

function defaultSources() {
  return { web: true, academic: true, discussions: false };
}

function defaultWidgets() {
  return { weather: false, calculator: false, stock: false };
}

function selectedKeys(obj) {
  return Object.entries(obj || {})
    .filter(([, v]) => !!v)
    .map(([k]) => k);
}

function generateGUID() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "fpx-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function buildPromptText(args) {
  const argsJson = JSON.stringify(args, null, 2);
  return [
    "Please run a Fauxplexica deep-research search to answer the question below.",
    "Use the `fauxplexica_search` tool with exactly these arguments so I can see the full mechanics in this chat:",
    "",
    "```json",
    argsJson,
    "```",
    "",
    `Question: ${args.query}`,
  ].join("\n");
}

export const store = createStore("fauxplexica", {
  query: "",
  mode: "balanced",
  sources: defaultSources(),
  widgets: defaultWidgets(),
  sourceOptions: SOURCE_OPTIONS,
  widgetOptions: WIDGET_OPTIONS,

  hasContext: false,
  dispatching: false,
  lastError: "",
  lastOk: "",
  statusLine: "",

  onOpen() {
    this.lastError = "";
    this.lastOk = "";
    this.statusLine = "";
    this.dispatching = false;
    try {
      const ctx = typeof globalThis.getContext === "function" ? globalThis.getContext() : null;
      this.hasContext = !!ctx;
    } catch {
      this.hasContext = false;
    }
    if (!this.hasContext) {
      this.statusLine = "No chat selected.";
    } else {
      this.statusLine = "Ready.";
    }
  },

  cleanup() {
    this.dispatching = false;
  },

  reset() {
    this.query = "";
    this.mode = "balanced";
    this.sources = defaultSources();
    this.widgets = defaultWidgets();
    this.lastError = "";
    this.lastOk = "";
    this.statusLine = this.hasContext ? "Ready." : "No chat selected.";
  },

  toggleSource(id) {
    if (!id) return;
    this.sources = { ...this.sources, [id]: !this.sources[id] };
  },

  toggleWidget(id) {
    if (!id) return;
    this.widgets = { ...this.widgets, [id]: !this.widgets[id] };
  },

  get toolArgs() {
    const q = String(this.query || "").trim();
    return {
      query: q,
      mode: classifyMode(this.mode),
      sources: selectedKeys(this.sources),
      widgets: selectedKeys(this.widgets),
      max_sources: 8,
    };
  },

  get previewText() {
    const args = this.toolArgs;
    return JSON.stringify({ tool_name: "fauxplexica_search", tool_args: args }, null, 2);
  },

  get canDispatch() {
    return !!this.hasContext && !this.dispatching && String(this.query || "").trim().length > 0;
  },

  async dispatch() {
    this.lastError = "";
    this.lastOk = "";
    const args = this.toolArgs;
    if (!args.query) {
      this.lastError = "Please enter a research question.";
      return;
    }
    let ctxid = "";
    try {
      ctxid = typeof globalThis.getContext === "function" ? globalThis.getContext() : "";
    } catch { ctxid = ""; }
    if (!ctxid) {
      this.hasContext = false;
      this.lastError = "No chat is open. Open or create a chat first.";
      return;
    }
    if (typeof globalThis.sendJsonData !== "function") {
      this.lastError = "Agent Zero API bridge is unavailable.";
      return;
    }

    this.dispatching = true;
    this.statusLine = "Dispatching tool call into current chat…";
    try {
      const text = buildPromptText(args);
      const message_id = generateGUID();
      const resp = await globalThis.sendJsonData("/message_async", {
        text,
        context: ctxid,
        message_id,
      });
      if (resp && resp.context) {
        if (typeof globalThis.setContext === "function") {
          try { globalThis.setContext(resp.context); } catch (_e) { /* ignore */ }
        }
      }
      this.lastOk = "Tool call dispatched. Check the chat for live execution.";
      this.statusLine = "Sent.";
      // Close the modal so the user sees their chat with the tool call playing out.
      if (typeof globalThis.closeModal === "function") {
        try { globalThis.closeModal(); } catch (_e) { /* ignore */ }
      }
    } catch (err) {
      this.lastError = (err && err.message) || String(err);
      this.statusLine = "Dispatch failed.";
    } finally {
      this.dispatching = false;
    }
  },
});
