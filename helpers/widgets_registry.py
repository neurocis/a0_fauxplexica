"""Widget registry + parallel executor for A0_Fauxplexica.

Mirrors Vane's ``widgets/executor.ts`` two-stage pattern:

1. ``should_execute(classification)`` — pure predicate over the classifier output;
   the executor AND-gates this with the caller-provided ``enabled`` set.
2. ``execute(...)`` — typically performs an inner param-extractor LLM call,
   hits an external API, returns a ``WidgetOutput``.

Graceful degradation is mandatory: any per-widget exception is caught by the
executor and converted into a ``WidgetOutput`` carrying ``data.error`` plus a
user-visible ``Failed to fetch …`` ``llm_context`` string. Widgets must NEVER
bubble exceptions up out of the registry.

See:
- PLAN_PHASE1.md §3 (Plugin Layout)
- PLAN_AMENDMENTS_R1.md §A8 (Widget implementation specifics)
- RECON_INITIAL.md §5 (Vane widget anatomy)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Iterable, List, Optional, Protocol, Set

if TYPE_CHECKING:
    # ``helpers/types.py`` is authored by Classy. We only import the symbol for
    # static type checking — at runtime we treat ``classification`` as a duck
    # so widgets keep working before Classy's module lands.
    from .types import ClassifierOutput  # noqa: F401

__all__ = [
    "WidgetOutput",
    "Widget",
    "build_failure_output",
    "execute_all",
    "WIDGETS",
    "get_widgets",
]

_log = logging.getLogger(__name__)


@dataclass
class WidgetOutput:
    """Canonical widget result envelope.

    Attributes:
        type: Stable widget id (e.g. ``'weather'``, ``'calculation_result'``,
            ``'stock'``). Must match the widget's declared ``type``.
        llm_context: One-line factual string consumed by the Composer. The
            Citer will wrap it with a "do not cite" instruction before passing
            to the model — keep it terse and bare-fact.
        data: Rich payload for the WebUI renderer. Structure is widget-defined.
    """

    type: str
    llm_context: str
    data: dict = field(default_factory=dict)


class Widget(Protocol):
    """Structural protocol implemented by every widget tool.

    Implementers live in ``a0_fauxplexica/tools/widget_*.py`` and are
    registered in ``WIDGETS`` below.
    """

    type: str

    def should_execute(self, classification: "ClassifierOutput") -> bool:
        """Return True if this widget should run given the classifier output."""
        ...

    async def execute(
        self,
        *,
        chat_history: list,
        follow_up: str,
        classification: "ClassifierOutput",
        llm: Any,
    ) -> Optional[WidgetOutput]:
        """Run the widget and return a ``WidgetOutput`` (or ``None`` to opt out)."""
        ...


def build_failure_output(widget_type: str, error: BaseException | str) -> WidgetOutput:
    """Build the canonical graceful-degradation output for a failed widget."""
    err_str = str(error) if not isinstance(error, str) else error
    return WidgetOutput(
        type=widget_type,
        llm_context=f"Failed to fetch {widget_type} data.",
        data={"error": err_str},
    )


def _build_widgets() -> List[Widget]:
    """Construct the canonical widget registry.

    Kept in a helper so tests can monkeypatch/inspect without duplicating the
    import dance. Imports happen after ``WidgetOutput`` is defined, which avoids
    circular-import trouble because widget modules import this module for the
    dataclass.
    """
    from ..tools.widget_calc import CalculationWidget
    from ..tools.widget_stock import StockWidget
    from ..tools.widget_weather import WeatherWidget

    return [WeatherWidget(), CalculationWidget(), StockWidget()]


class _LazyWidgetList(list):
    """List-like registry that populates itself on first use.

    This preserves the public ``WIDGETS`` contract while avoiding circular
    imports when a concrete widget imports ``WidgetOutput`` from this module.
    """

    def _ensure(self) -> None:
        if not super().__len__():
            super().extend(_build_widgets())

    def __iter__(self):  # type: ignore[override]
        self._ensure()
        return super().__iter__()

    def __len__(self) -> int:  # type: ignore[override]
        self._ensure()
        return super().__len__()

    def __getitem__(self, index):  # type: ignore[override]
        self._ensure()
        return super().__getitem__(index)


WIDGETS: List[Widget] = _LazyWidgetList()


def get_widgets() -> List[Widget]:
    """Return the canonical widget registry as a shallow copy."""
    return list(WIDGETS)


def _widget_enabled(widget: Widget, enabled_set: Set[str]) -> bool:
    """Return True when ``enabled_set`` names this widget.

    The canonical key is ``widget.type`` (``weather``, ``calculation_result``,
    ``stock``), but config/classifier code historically used ``calculation`` or
    ``calculator``. Accept those aliases to keep integration friction low.
    """
    if widget.type in enabled_set:
        return True
    aliases = {
        "calculation_result": {"calculation", "calculator"},
    }
    return bool(aliases.get(widget.type, set()) & enabled_set)


async def _safe_execute(
    widget: Widget,
    *,
    chat_history: list,
    follow_up: str,
    classification: "ClassifierOutput",
    llm: Any,
) -> Optional[WidgetOutput]:
    """Invoke a single widget with full error containment."""
    try:
        result = await widget.execute(
            chat_history=chat_history,
            follow_up=follow_up,
            classification=classification,
            llm=llm,
        )
        if result is None:
            return None
        # Defensive: enforce the type contract so misbehaving widgets can't
        # smuggle a different shape into the composer.
        if not isinstance(result, WidgetOutput):
            _log.warning(
                "widget %s returned non-WidgetOutput %r — wrapping as failure",
                widget.type,
                type(result).__name__,
            )
            return build_failure_output(widget.type, "invalid widget output shape")
        return result
    except Exception as exc:  # noqa: BLE001 — we want to catch everything
        _log.exception("widget %s raised during execute(): %s", widget.type, exc)
        return build_failure_output(widget.type, exc)


async def execute_all(
    classification: "ClassifierOutput",
    chat_history: list,
    follow_up: str,
    llm: Any,
    enabled: Set[str] | Iterable[str],
    widgets: Optional[Iterable[Widget]] = None,
) -> List[WidgetOutput]:
    """Filter + run every enabled+triggered widget concurrently.

    Args:
        classification: Classifier output (typed as ``ClassifierOutput`` when
            available; duck-typed otherwise).
        chat_history: Conversation history forwarded to each widget.
        follow_up: The latest user follow-up / query string.
        llm: LLM handle used by inner param-extractor calls. The exact shape
            is determined by the Agent Zero util-model adapter; widgets call
            ``llm`` as an awaitable returning text.
        enabled: Set/iterable of widget ``type`` strings enabled via config.
            ``WIDGETS`` is filtered to this set BEFORE ``should_execute`` runs
            so disabled widgets never see classifier output.
        widgets: Optional explicit widget list (for tests). Defaults to the
            real registry.

    Returns:
        Ordered list of ``WidgetOutput`` (one per widget that ran and
        returned non-``None``). Failures are represented by
        ``build_failure_output`` results, not exceptions.
    """
    enabled_set: Set[str] = set(enabled)
    candidates = list(widgets) if widgets is not None else get_widgets()

    # AND-gate: enabled in config AND triggered by classifier.
    selected: List[Widget] = []
    for w in candidates:
        if not _widget_enabled(w, enabled_set):
            continue
        try:
            if w.should_execute(classification):
                selected.append(w)
        except Exception as exc:  # noqa: BLE001 — predicate must never crash us
            _log.exception("widget %s.should_execute raised: %s", w.type, exc)

    if not selected:
        return []

    coros: List[Awaitable[Optional[WidgetOutput]]] = [
        _safe_execute(
            w,
            chat_history=chat_history,
            follow_up=follow_up,
            classification=classification,
            llm=llm,
        )
        for w in selected
    ]

    # ``return_exceptions=True`` is belt-and-suspenders — ``_safe_execute``
    # already catches everything, but if it ever fails to do so we still
    # surface the rest of the results.
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    out: List[WidgetOutput] = []
    for w, res in zip(selected, raw_results):
        if isinstance(res, BaseException):
            _log.exception("widget %s leaked exception past _safe_execute: %s", w.type, res)
            out.append(build_failure_output(w.type, res))
        elif res is not None:
            out.append(res)
    return out
