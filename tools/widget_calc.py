"""Calculation widget — deterministic arithmetic via ``asteval``.

Mirrors Vane's ``calculationWidget.ts`` (mathjs in TS-land). Two-stage:

1. Inner param-extractor LLM call → extract the math expression as a clean
   string (or ``NOT_PRESENT``).
2. Evaluate with ``asteval`` — sandboxed, never raw ``eval``.

Graceful degradation: parse / eval errors return a failure ``WidgetOutput``
rather than raising.

See PLAN_AMENDMENTS_R1.md §A8 and RECON_INITIAL.md §5.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

try:
    from asteval import Interpreter
except ModuleNotFoundError:  # pragma: no cover - exercised in backend runtime if optional deps missing
    Interpreter = None


from ..helpers.widgets_registry import WidgetOutput, build_failure_output

if TYPE_CHECKING:
    from ..helpers.types import ClassifierOutput  # noqa: F401

__all__ = ["CalculationWidget"]

_log = logging.getLogger(__name__)

_EXTRACTOR_SYSTEM_PROMPT = """You extract a single math expression from a user query.

Rules:
- Output ONLY the bare expression suitable for a calculator (no prose, no equals sign, no units).
- Use standard operators: + - * / ** ( ) and common functions like sqrt, sin, cos, tan, log, exp.
- Examples:
  - "what's 2 plus 2" -> 2 + 2
  - "15% of 240" -> 0.15 * 240
  - "sqrt of 144" -> sqrt(144)
  - "compound interest on 1000 at 5% for 3 years" -> 1000 * (1 + 0.05)**3
- If the query contains no math expression at all, output exactly: NOT_PRESENT
Never explain. Output the expression only."""


class CalculationWidget:
    """Calculator widget — id ``'calculation_result'``."""

    type: str = "calculation_result"

    def should_execute(self, classification: "ClassifierOutput") -> bool:
        return _routing_widget_flag(classification, "calculation")

    async def execute(
        self,
        *,
        chat_history: list,
        follow_up: str,
        classification: "ClassifierOutput",
        llm: Any,
    ) -> Optional[WidgetOutput]:
        # Stage 1: extract expression via inner LLM call.
        try:
            expression = await _extract_expression(follow_up, chat_history, llm)
        except Exception as exc:  # noqa: BLE001
            _log.exception("calc: extractor LLM call failed: %s", exc)
            return build_failure_output(self.type, f"extractor failed: {exc}")

        if not expression or expression.strip().upper() == "NOT_PRESENT":
            return WidgetOutput(
                type=self.type,
                llm_context="No math expression detected.",
                data={"error": "no_expression"},
            )

        expression = expression.strip()

        # Stage 2: evaluate with asteval.  If the plugin dependency was not
        # installed into the Agent Zero backend runtime, do not fail the whole
        # search: return a structured widget failure and let research/answering
        # continue.
        if Interpreter is None:
            _log.warning("calc: asteval is not installed; calculator widget unavailable")
            return build_failure_output(
                self.type,
                "Calculator widget dependency 'asteval' is not installed in the backend runtime.",
            )

        interp = Interpreter(minimal=False, use_numpy=False)
        try:
            result = interp(expression)
        except Exception as exc:  # noqa: BLE001 — asteval should report via errors list, but belt-and-suspenders
            _log.warning("calc: asteval raised on %r: %s", expression, exc)
            return build_failure_output(self.type, f"eval error: {exc}")

        if interp.error:
            err_msgs = "; ".join(str(e.get_error()[1]) for e in interp.error)
            _log.warning("calc: asteval errors on %r: %s", expression, err_msgs)
            return WidgetOutput(
                type=self.type,
                llm_context=f"Could not evaluate: {expression}",
                data={"expression": expression, "error": err_msgs},
            )

        if result is None:
            return WidgetOutput(
                type=self.type,
                llm_context=f"Could not evaluate: {expression}",
                data={"expression": expression, "error": "empty result"},
            )

        # Coerce result to a JSON-safe primitive.
        result_type = "number" if isinstance(result, (int, float)) else "string"
        result_value: Any
        if isinstance(result, bool):
            # Bools are ints in Python — treat as string for display.
            result_value = str(result)
            result_type = "string"
        elif isinstance(result, (int, float)):
            result_value = result
        else:
            result_value = str(result)

        return WidgetOutput(
            type=self.type,
            llm_context=f"Calculation: {expression} = {result_value}",
            data={
                "expression": expression,
                "result": result_value,
                "result_type": result_type,
            },
        )


def _routing_widget_flag(classification: Any, key: str) -> bool:
    """Duck-typed access to ``classification.routing.widgets[key]``.

    Tolerates the shim period before Classy lands ``helpers/types.py``.
    """
    if classification is None:
        return False
    routing = getattr(classification, "routing", None)
    if routing is None and isinstance(classification, dict):
        routing = classification.get("routing")
    if routing is None:
        return False
    widgets = getattr(routing, "widgets", None)
    if widgets is None and isinstance(routing, dict):
        widgets = routing.get("widgets")
    if widgets is None:
        return False
    if isinstance(widgets, dict):
        return bool(widgets.get(key, False))
    return bool(getattr(widgets, key, False))


async def _extract_expression(query: str, chat_history: list, llm: Any) -> str:
    """Call the param-extractor LLM and return a sanitized expression string."""
    history_snippet = _format_history(chat_history)
    user_msg = (
        f"{history_snippet}\nLatest user query: {query}\n\n"
        "Extract the math expression. Output the expression only, or NOT_PRESENT."
    )
    raw = await _invoke_llm(llm, system=_EXTRACTOR_SYSTEM_PROMPT, user=user_msg)
    return _strip_code_fence(raw)


def _format_history(chat_history: list, max_turns: int = 4) -> str:
    """Format the last ``max_turns`` messages for the extractor prompt."""
    if not chat_history:
        return ""
    tail = chat_history[-max_turns:]
    lines = []
    for msg in tail:
        role = _get_attr(msg, "role", "user")
        content = _get_attr(msg, "content", "")
        if not content:
            continue
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "Recent context:\n" + "\n".join(lines)


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


async def _invoke_llm(llm: Any, *, system: str, user: str) -> str:
    """Invoke ``llm`` in whichever shape the orchestrator handed us.

    Supported shapes (in priority order):
      1. callable ``llm(system=..., user=...) -> Awaitable[str]``
      2. agent-like object with ``.call_utility_model(system=..., message=...)``
      3. callable ``llm(prompt: str) -> Awaitable[str]`` — fallback: we
         concatenate system + user into a single prompt.
    """
    if hasattr(llm, "call_utility_model"):
        return await llm.call_utility_model(system=system, message=user)
    if callable(llm):
        try:
            return await llm(system=system, user=user)
        except TypeError:
            return await llm(f"{system}\n\n{user}")
    raise RuntimeError(f"unsupported llm handle: {type(llm).__name__}")


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\n?|\n?```$")


def _strip_code_fence(text: str) -> str:
    """Strip a single leading/trailing markdown code fence if present."""
    if not text:
        return ""
    t = text.strip()
    # Remove fenced block markers.
    t = _FENCE_RE.sub("", t).strip()
    return t
