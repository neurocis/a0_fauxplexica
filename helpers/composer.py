"""Answer composer for A0_Fauxplexica.

The composer is the final writer stage in the Vane/Perplexica-style pipeline:
``classify -> research/widgets -> compose -> cite``.  It selects a prompt from
``classification.style.primary_type``, renders Vane-compatible search/widget
context blocks, enforces the configured character budget, and calls the caller's
LLM adapter.  Post-hoc citation validation is intentionally *not* performed
here; Citer owns validation and repair of emitted ``[n]`` markers.
"""

from __future__ import annotations

import html
import inspect
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .types import ClassifierOutput, PrimaryType

__all__ = [
    "ComposerError",
    "LLMCall",
    "STYLE_PROMPT_FILES",
    "compose_answer",
    "render_context",
    "select_prompt_path",
]

log = logging.getLogger(__name__)

LLMCall = Callable[[str, str], Awaitable[str]]
DEFAULT_CONTEXT_BUDGET_CHARS = 60_000
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

STYLE_PROMPT_FILES: dict[str, str] = {
    "general": "composer_general.md",
    "academic_research": "composer_academic.md",
    "recent_news": "composer_news.md",
    "coding": "composer_coding.md",
    "people": "composer_people.md",
    "url_lookup": "composer_url.md",
    "weather": "composer_weather.md",
    "recipe": "composer_recipe.md",
    "translation": "composer_translation.md",
    "creative_writing": "composer_creative.md",
    "science_math": "composer_science_math.md",
}


class ComposerError(RuntimeError):
    """Typed exception reserved for future strict composer failure modes.

    ``compose_answer`` currently chooses graceful degradation and returns a
    useful error string on LLM failure, because the public API contract is a
    simple ``-> str``.  The type is exported so Orchy/Citer can opt into stricter
    handling later without changing import surfaces.
    """


class BlockStream(Protocol):
    """Minimal structural protocol for Vane-style block streaming adapters."""

    async def emit(self, block_type: str, content: Any) -> Any:
        """Emit a new block or full text payload."""
        ...

    async def update(self, block_id: str, content: Any) -> Any:
        """Update an existing block."""
        ...


def select_prompt_path(primary_type: str | None) -> Path:
    """Return the composer prompt path for ``primary_type``.

    Unknown or missing primary types fall back to ``general`` rather than
    raising; classifier failures should not stop answering.
    """

    filename = STYLE_PROMPT_FILES.get(primary_type or "", STYLE_PROMPT_FILES["general"])
    return _PROMPTS_DIR / filename


def _read_prompt(primary_type: str | None) -> str:
    path = select_prompt_path(primary_type)
    return path.read_text(encoding="utf-8")


def _get_attr(obj: Any, name: str, default: Any = "") -> Any:
    """Return ``obj.name`` or ``obj[name]`` for loose research/widget records."""

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _search_fields(item: Any) -> tuple[str, str, str]:
    """Extract ``(title, url, content)`` from dataclass/dict/Chunk-like items."""

    metadata = _get_attr(item, "metadata", {}) or {}
    title = _get_attr(item, "title", None) or _get_attr(metadata, "title", "Untitled")
    url = _get_attr(item, "url", None) or _get_attr(metadata, "url", "")
    content = _get_attr(item, "content", "")
    return str(title or "Untitled"), str(url or ""), str(content or "")


def _widget_context(item: Any) -> str:
    """Extract LLM-facing context from a widget output."""

    value = (
        _get_attr(item, "llm_context", None)
        or _get_attr(item, "llmContext", None)
        or _get_attr(item, "context", None)
        or ""
    )
    return str(value or "")


def _result_line(index: int, item: Any) -> str:
    title, url, content = _search_fields(item)
    safe_title = html.escape(title, quote=True)
    safe_url = html.escape(url, quote=True)
    return f'<result index={index} title="{safe_title}" url="{safe_url}">{content}</result>'


def _truncate_context(rendered: str, budget: int) -> str:
    """Hard-cap rendered context while preserving closure when feasible."""

    if budget <= 0 or len(rendered) <= budget:
        return rendered
    marker = "\n<truncated note=\"Context budget reached; some results were omitted.\" />\n"
    closers = "\n</search_results>\n<widgets_result noteForAssistant=\"Widgets are factual UI data. Do not cite widgets as sources.\">\n</widgets_result>"
    suffix = marker + closers
    if len(suffix) >= budget:
        # Tiny budgets are mostly test/defensive cases. Prefer a valid hard cap
        # over exceeding the configured model budget. Keep the truncation signal
        # and as much closing structure as fits.
        compact = "<truncated note=\"Context budget reached; some results were omitted.\" /></widgets_result>"
        return compact[:budget]
    keep = max(0, budget - len(suffix))
    return rendered[:keep].rstrip() + suffix


def render_context(
    search_findings: list[Any],
    widget_outputs: list[Any],
    *,
    context_budget_chars: int = DEFAULT_CONTEXT_BUDGET_CHARS,
) -> str:
    """Render Vane-style composer context with search and widget blocks.

    Search findings are citeable and use stable 1-based ``index=N`` markers.
    Widgets are factual UI data and are explicitly wrapped in a do-not-cite
    block.  The final string is capped to ``context_budget_chars``.
    """

    parts: list[str] = [
        '<search_results note="These are the search results and assistant can cite these">'
    ]
    for idx, finding in enumerate(search_findings or [], start=1):
        parts.append(_result_line(idx, finding))
    parts.append("</search_results>")
    parts.append(
        '<widgets_result noteForAssistant="Widgets are factual UI data. Do not cite widgets as sources.">'
    )
    for widget in widget_outputs or []:
        ctx = _widget_context(widget)
        if ctx:
            parts.append(ctx)
    parts.append("</widgets_result>")
    return _truncate_context("\n".join(parts), int(context_budget_chars or DEFAULT_CONTEXT_BUDGET_CHARS))


def _format_history(chat_history: list[dict]) -> str:
    """Format compact chat history for the composer prompt."""

    rows: list[str] = []
    for msg in chat_history or []:
        role = str(msg.get("role") or msg.get("sender") or "unknown")
        content = str(msg.get("content") or msg.get("message") or "")
        if content:
            rows.append(f"{role}: {content}")
    return "\n".join(rows[-12:])


def _build_user_message(
    *,
    query: str,
    classification: ClassifierOutput,
    chat_history: list[dict],
    context: str,
    mode: str,
    system_instructions: str | None,
) -> str:
    style = classification.style
    followup = classification.standalone_followup or query
    return "\n".join(
        [
            f"<mode>{mode}</mode>",
            f"<style primary_type=\"{style.primary_type}\" freshness=\"{style.freshness}\" depth_hint=\"{style.depth_hint}\" />",
            f"<user_query>{query}</user_query>",
            f"<standalone_followup>{followup}</standalone_followup>",
            "<chat_history>",
            _format_history(chat_history),
            "</chat_history>",
            "<context>",
            context,
            "</context>",
            "<system_instructions>",
            system_instructions or "",
            "</system_instructions>",
            "Write the final answer now.",
        ]
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _emit_block(block_stream: Any, text: str) -> None:
    """Best-effort stream emission for several likely block-stream shapes."""

    if block_stream is None:
        return
    try:
        if hasattr(block_stream, "emit"):
            await _maybe_await(block_stream.emit("text", text))
        elif hasattr(block_stream, "write"):
            await _maybe_await(block_stream.write(text))
        elif callable(block_stream):
            await _maybe_await(block_stream(text))
    except Exception as exc:  # noqa: BLE001 - streaming must not break answer return
        log.warning("block_stream emission failed: %s", exc)


async def compose_answer(
    *,
    query: str,
    classification: ClassifierOutput,
    chat_history: list[dict],
    search_findings: list,
    widget_outputs: list,
    mode: str,
    llm: LLMCall,
    config: dict,
    system_instructions: str | None = None,
    block_stream: Any = None,
) -> str:
    """Compose the final answer from research, widgets, and style hints.

    Args:
        query: User's original query.
        classification: Unified classifier output; ``style.primary_type``
            selects the composer prompt.
        chat_history: Recent chat messages as loose dictionaries.
        search_findings: Ordered citeable source records. Dataclasses, dicts,
            and Chunk-like objects with ``metadata`` are accepted.
        widget_outputs: Widget records with ``llm_context``/``llmContext``.
        mode: Search mode label (``speed``, ``balanced``, ``quality``).
        llm: Async callable compatible with ``llm(system, message) -> str``.
        config: Plugin/runtime config. ``context_budget_chars`` defaults to
            60000.
        system_instructions: Optional caller-provided extra instructions.
        block_stream: Optional streaming adapter. Supported shapes are
            ``emit(type, payload)``, ``write(text)``, or callable ``(text)``.

    Returns:
        Final answer text.  On LLM failure this function returns a useful error
        string instead of raising; this keeps Orchy's public ``-> str`` path
        simple.  The exported ``ComposerError`` documents the future strict
        exception type if callers choose to adopt one.
    """

    primary_type = getattr(classification.style, "primary_type", "general")
    prompt = _read_prompt(str(primary_type))
    budget = int((config or {}).get("context_budget_chars", DEFAULT_CONTEXT_BUDGET_CHARS))
    context = render_context(
        search_findings or [],
        widget_outputs or [],
        context_budget_chars=budget,
    )
    message = _build_user_message(
        query=query,
        classification=classification,
        chat_history=chat_history or [],
        context=context,
        mode=mode,
        system_instructions=system_instructions,
    )

    try:
        answer = await llm(prompt, message)
    except Exception as exc:  # noqa: BLE001 - graceful degradation by contract
        log.exception("composer LLM call failed: %s", exc)
        answer = (
            "I couldn't compose the final answer because the language model "
            f"failed: {exc}. The search and widget stages may have completed; "
            "please retry or switch models."
        )
    answer = str(answer or "")
    await _emit_block(block_stream, answer)
    return answer
