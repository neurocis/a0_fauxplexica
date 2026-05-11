"""High-level Fauxplexica search pipeline coordinator.

The orchestrator intentionally stays thin: classify the query, start widgets
and research, emit stream events/blocks, then hand gathered context to the
composer. Researcher and composer are lazy-imported so this module remains safe
while sibling Wave 2 branches are still in flight.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import asdict, is_dataclass
from typing import Any, Awaitable, Callable

from .blockstream import BlockStream
from .classifier import classify
from .widgets_registry import execute_all

__all__ = ["run_fauxplexica_search"]

_log = logging.getLogger(__name__)

_DEFAULT_SOURCES = {"web", "academic", "discussions"}
_DEFAULT_WIDGETS = {"weather", "stock", "calculation", "calculation_result"}


async def run_fauxplexica_search(
    *,
    query: str,
    chat_history: list[dict] | None = None,
    mode: str = "balanced",
    enabled_sources: set[str] | None = None,
    enabled_widgets: set[str] | None = None,
    file_ids: list[str] | None = None,
    llm: Any = None,
    embedder: Any = None,
    config: dict | None = None,
    agent_context: Any = None,
    block_stream: BlockStream | None = None,
) -> dict[str, Any]:
    """Run the Wave 2 Fauxplexica classify→research/widgets→compose pipeline.

    Args mirror the public API requested by API/WebUI callers. The returned
    value is intentionally JSON-like and citation validation is deferred to the
    later Citer lane.
    """
    history = list(chat_history or [])
    sources_enabled = set(enabled_sources or _DEFAULT_SOURCES)
    widgets_enabled = set(enabled_widgets or _DEFAULT_WIDGETS)
    files = list(file_ids or [])
    cfg = dict(config or {})
    stream = block_stream or BlockStream()

    await stream.emit("init", {"query": query, "mode": mode})

    classification_obj = await classify(
        query=query,
        chat_history=history,
        enabled_sources=sources_enabled,
        enabled_widgets=widgets_enabled,
        llm=llm,
    )
    classification = _to_plain_dict(classification_obj)
    follow_up = classification.get("standalone_followup") or query

    widget_task = asyncio.create_task(
        execute_all(
            classification=classification_obj,
            chat_history=history,
            follow_up=follow_up,
            llm=llm,
            enabled=widgets_enabled,
        )
    )
    research_task = asyncio.create_task(
        _run_research(
            query=query,
            follow_up=follow_up,
            chat_history=history,
            classification=classification_obj,
            mode=mode,
            enabled_sources=sources_enabled,
            file_ids=files,
            llm=llm,
            embedder=embedder,
            config=cfg,
            agent_context=agent_context,
            block_stream=stream,
        )
    )

    widget_outputs, research_output = await asyncio.gather(widget_task, research_task)
    widgets = [_to_plain_dict(widget) for widget in widget_outputs]
    for widget in widgets:
        await stream.emit_block("widget", widget)

    research = _normalise_research_output(research_output)
    sources = research["sources"]
    await stream.emit("researchComplete", {"sources": sources, "research": research})

    answer = await _run_composer(
        query=query,
        follow_up=follow_up,
        chat_history=history,
        classification=classification_obj,
        research=research,
        sources=sources,
        widgets=widgets,
        mode=mode,
        llm=llm,
        config=cfg,
        agent_context=agent_context,
        block_stream=stream,
    )
    if not any(block.type == "text" for block in stream.blocks):
        await stream.emit_block("text", {"text": answer})
    await stream.emit("response", {"answer": answer})
    await stream.emit("messageEnd", {})
    await stream.close()

    return {
        "answer": answer,
        "classification": classification,
        "sources": sources,
        "citations": [],
        "widgets": widgets,
        "mode": mode,
        "blocks": stream.all_blocks(),
    }


async def _run_research(**kwargs: Any) -> dict[str, Any]:
    """Invoke Reggie's researcher if present; otherwise return an empty result."""
    try:
        from . import researcher  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # noqa: BLE001
        _log.warning("researcher import failed; using empty fallback: %s", exc)
        return {"sources": [], "findings": [], "warning": "TODO: researcher pending"}

    research_fn = getattr(researcher, "research", None)
    if research_fn is None:
        _log.warning("researcher.research missing; using empty fallback")
        return {"sources": [], "findings": [], "warning": "TODO: researcher pending"}

    return await _call_flexible(research_fn, **kwargs)


async def _run_composer(**kwargs: Any) -> str:
    """Invoke Compo's composer if present; otherwise return deterministic text."""
    try:
        from . import composer  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # noqa: BLE001
        _log.warning("composer import failed; using placeholder answer: %s", exc)
        return "Composer pending: Fauxplexica gathered context, but answer composition is not implemented yet."

    compose_fn = getattr(composer, "compose_answer", None)
    if compose_fn is None:
        _log.warning("composer.compose_answer missing; using placeholder answer")
        return "Composer pending: Fauxplexica gathered context, but answer composition is not implemented yet."

    result = await _call_flexible(compose_fn, **kwargs)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return str(result.get("answer") or result.get("text") or "")
    return str(result)


async def _call_flexible(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Call a possibly narrower async/sync integration function by signature."""
    try:
        sig = inspect.signature(fn)
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    except (TypeError, ValueError):
        pass
    result = fn(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _normalise_research_output(raw: Any) -> dict[str, Any]:
    """Coerce researcher output into a dict with a ``sources`` list."""
    if raw is None:
        return {"sources": [], "findings": []}
    research = _to_plain_dict(raw)
    if isinstance(research, list):
        return {"sources": research, "findings": []}
    if not isinstance(research, dict):
        return {"sources": [], "findings": [], "raw": research}
    sources = research.get("sources") or research.get("source_results") or []
    if not isinstance(sources, list):
        sources = list(sources) if isinstance(sources, tuple) else []
    research["sources"] = [_to_plain_dict(source) for source in sources]
    return research


def _to_plain_dict(value: Any) -> Any:
    """Convert dataclasses and helper objects with ``to_dict`` to plain values."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _to_plain_dict(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain_dict(v) for v in value]
    if isinstance(value, tuple):
        return [_to_plain_dict(v) for v in value]
    return value
