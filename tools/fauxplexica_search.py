"""A0 tool wrapper for running the Fauxplexica deep-research pipeline.

Lets any A0 context (agent, superordinate, skill) invoke the full
classify -> research/widgets -> compose -> cite pipeline via a normal
tool call instead of the WebUI modal.

Returns the composed answer plus a structured registry of sources, the
top widget outputs, and the classifier output. The agent receives this as
a JSON tool result it can summarise or quote with citations.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from helpers.tool import Response, Tool
from plugins.a0_fauxplexica.helpers.blockstream import BlockStream
from plugins.a0_fauxplexica.helpers.orchestrator import run_fauxplexica_search


_VALID_MODES = {"speed", "balanced", "quality"}
_DEFAULT_MODE = "balanced"
_DEFAULT_SOURCES = ["web", "academic"]
_DEFAULT_WIDGETS: list[str] = []


class FauxplexicaSearch(Tool):
    """Run a Fauxplexica deep research query and return the composed answer."""

    async def execute(
        self,
        query: str = "",
        mode: str = _DEFAULT_MODE,
        sources: Any = None,
        widgets: Any = None,
        file_ids: Any = None,
        max_sources: int | str | None = None,
        **_kwargs: Any,
    ) -> Response:
        question = str(query or self.message or "").strip()
        if not question:
            payload = {"error": "missing_query", "message": "fauxplexica_search requires 'query'."}
            return Response(message=json.dumps(payload), break_loop=False, additional=payload)

        mode_norm = str(mode or _DEFAULT_MODE).strip().lower()
        if mode_norm not in _VALID_MODES:
            mode_norm = _DEFAULT_MODE

        enabled_sources = set(_coerce_list(sources, _DEFAULT_SOURCES))
        enabled_widgets = set(_coerce_list(widgets, _DEFAULT_WIDGETS))
        files = _coerce_list(file_ids, [])

        config = _load_plugin_config(self.agent)
        if enabled_sources and not str(config.get("searxng_url") or "").strip():
            payload = {
                "error": "missing_searxng_url",
                "message": "Fauxplexica plugin needs 'searxng_url' configured before running source-backed searches.",
            }
            return Response(message=json.dumps(payload), break_loop=False, additional=payload)

        llm = _build_llm_adapter(self.agent)
        block_stream = BlockStream()
        context = getattr(self.agent, "context", None)

        try:
            result = await run_fauxplexica_search(
                query=question,
                chat_history=[],
                mode=mode_norm,
                enabled_sources=enabled_sources,
                enabled_widgets=enabled_widgets,
                file_ids=[str(f) for f in files],
                llm=llm,
                config=config,
                agent_context=context,
                block_stream=block_stream,
            )
        except Exception as exc:  # noqa: BLE001
            payload = {"error": "search_failed", "message": str(exc), "query": question}
            return Response(message=json.dumps(payload), break_loop=False, additional=payload)

        try:
            max_n = int(max_sources) if max_sources is not None else 8
        except (TypeError, ValueError):
            max_n = 8

        sources_out = _trim_sources(result.get("sources") or [], max_n)
        widgets_out = _summarise_widgets(result.get("widgets") or [])

        payload = {
            "query": question,
            "mode": result.get("mode") or mode_norm,
            "answer": result.get("answer") or "",
            "sources": sources_out,
            "widgets": widgets_out,
            "classification": result.get("classification") or {},
        }
        return Response(message=json.dumps(payload, ensure_ascii=False), break_loop=False, additional=payload)


def _coerce_list(value: Any, default: Iterable[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, list):
        items = value
    elif isinstance(value, (set, tuple)):
        items = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return list(default)
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                items = parsed if isinstance(parsed, list) else [parsed]
            except Exception:
                items = [p.strip() for p in text.split(",")]
        else:
            items = [p.strip() for p in text.split(",")]
    else:
        items = [value]
    return [str(it).strip() for it in items if str(it).strip()]


def _load_plugin_config(agent: Any) -> dict[str, Any]:
    try:
        from helpers import plugins  # type: ignore
        cfg = plugins.get_plugin_config("a0_fauxplexica", agent=agent) or {}
        return dict(cfg) if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _build_llm_adapter(agent: Any) -> Any:
    if agent is None:
        return None
    call = getattr(agent, "call_utility_model", None)
    if call is None or not callable(call):
        return None

    async def _llm(system: str, message: str) -> str:
        response = await call(system=system, message=message)
        return str(response or "")

    return _llm


def _trim_sources(sources: list[Any], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, src in enumerate(sources[: max(1, limit)], start=1):
        if not isinstance(src, dict):
            continue
        out.append({
            "index": int(src.get("index") or idx),
            "title": str(src.get("title") or src.get("url") or ""),
            "url": str(src.get("url") or ""),
            "snippet": str(src.get("snippet") or "")[:400],
            "source": str(src.get("source") or ""),
            "score": src.get("score"),
        })
    return out


def _summarise_widgets(widgets: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in widgets or []:
        if not isinstance(w, dict):
            continue
        out.append({
            "type": str(w.get("type") or ""),
            "llm_context": str(w.get("llm_context") or w.get("llmContext") or ""),
            "data": w.get("data") or {},
        })
    return out
