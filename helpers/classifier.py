"""Unified query classifier — A0_Fauxplexica plugin.

Implements the contract from ``PLAN_AMENDMENTS_R1.md`` §A5: a single async
:func:`classify` call returning a :class:`~helpers.types.ClassifierOutput`
with orthogonal *routing* (which tools fire) and *style* (how to answer)
axes, plus a regex-prefilled ``detected_urls`` list and a rewritten
standalone-follow-up string.

Design highlights
-----------------
* **Single LLM call.** Structured output is requested via prompt JSON-mode
  (model-agnostic; A0's ``call_utility_model`` returns a string we parse).
* **Deterministic fast-path** for trivial inputs (pure math, lone URL,
  greetings) — short-circuits the LLM entirely and stamps a
  ``_fastpath_reason`` for observability.
* **Regex URL pre-fill.** Per Recon §4.4 the LLM cannot be trusted to spot
  URLs reliably; we extract them deterministically and pass them in as
  hints. The LLM may *refine* but not invent.
* **AND-gate against caller enables.** The classifier never asserts a
  routing flag the orchestrator hasn't actually enabled. Widget flags are
  similarly clipped to ``enabled_widgets``.
* **Safe defaults on failure.** Any LLM/JSON error returns a permissive
  ``general`` envelope and logs a warning; downstream stages keep running.

The ``llm`` parameter is intentionally typed as a simple
``Callable[[str, str], Awaitable[str]]`` so callers can pass
``agent.call_utility_model`` directly *or* a mock in tests.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Iterable, Optional

from .types import (
    ClassifierOutput,
    DepthHint,
    Freshness,
    PrimaryType,
    RoutingFlags,
    RoutingWidgets,
    StyleHints,
)

log = logging.getLogger(__name__)

# A Callable matching ``agent.call_utility_model(system, message) -> str``.
LLMCall = Callable[[str, str], Awaitable[str]]

# Recognised routing source keys accepted by ``enabled_sources``.
_KNOWN_SOURCES = frozenset({"web", "academic", "discussions"})
# Recognised widget keys accepted by ``enabled_widgets``.
_KNOWN_WIDGETS = frozenset({"weather", "stock", "calculation"})

_ALLOWED_PRIMARY: frozenset[str] = frozenset(
    {
        "general",
        "academic_research",
        "recent_news",
        "weather",
        "people",
        "coding",
        "recipe",
        "translation",
        "creative_writing",
        "science_math",
        "url_lookup",
    }
)
_ALLOWED_FRESHNESS: frozenset[str] = frozenset({"any", "week", "day"})
_ALLOWED_DEPTH: frozenset[str] = frozenset({"short", "medium", "deep"})

# --- Regex / heuristics --------------------------------------------------

# Robust-ish URL regex. We err on the side of *over*-detection because the
# LLM still sees the raw query and can refine; false-negative URLs are the
# bad failure mode (would miss url_lookup intent).
_URL_RE = re.compile(
    r"""
    \b(                            # capture full URL
      (?:https?://|www\.)          # scheme or www.
      [^\s<>"'`)\]]+               # anything not whitespace/quote/bracket
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A *bare* math expression: digits, operators, parens, decimal points,
# optional whitespace. No alphabetic chars beyond a small allow-list of
# functions/constants. Used by the fast-path to short-circuit.
_MATH_TOKEN_RE = re.compile(
    r"^[\s\d+\-*/().,%^]+$|"
    r"^[\s\d+\-*/().,%^a-zA-Z]+$"
)
_MATH_FUNC_RE = re.compile(
    r"^[\s\d+\-*/().,%^]*(?:(?:sin|cos|tan|asin|acos|atan|exp|log|ln|sqrt|abs|pi|e)\b[\s\d+\-*/().,%^]*)+$",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|yo|sup|howdy|good\s+(?:morning|afternoon|evening)|"
    r"bye|goodbye|see\s+ya|see\s+you|cheers|thanks|thank\s+you|ty|thx)"
    r"[\s!.?,]*$",
    re.IGNORECASE,
)


def _extract_urls(text: str) -> list[str]:
    """Return URLs detected in *text*, preserving order, de-duplicated.

    Trailing punctuation (``.,;:!?`)``) is stripped — common false tail in
    natural prose like ``"see https://example.com."``.
    """
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = match.group(1)
        # strip common trailing punctuation that isn't part of the URL
        url = url.rstrip(".,;:!?)>]\"'")
        # `www.` prefix without scheme → normalise to https://
        if url.lower().startswith("www."):
            url = "https://" + url
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _is_pure_math(text: str) -> bool:
    """Heuristic: does *text* look like a bare arithmetic expression?

    Accepts digits, operators, parens, and a small allow-list of math
    function names. Rejects anything with a question mark, comma-separated
    English words, or runs of letters outside the allow-list.
    """
    s = (text or "").strip()
    if not s or "?" in s:
        return False
    # need at least one operator OR a math function token, otherwise it's
    # just a number / bare word and not worth fast-pathing.
    has_op = any(c in s for c in "+-*/%^")
    if has_op and re.fullmatch(r"[\s\d+\-*/().,%^]+", s):
        return True
    if _MATH_FUNC_RE.fullmatch(s):
        return True
    return False


def _is_lone_url(text: str, urls: list[str]) -> bool:
    """True iff *text* contains exactly one URL and no other question text."""
    if len(urls) != 1:
        return False
    stripped = (text or "").strip()
    # Remove the URL from the string; if what's left is empty or trivial
    # punctuation, we treat it as a lone URL.
    residual = stripped
    for u in urls:
        # also try the raw www. form
        residual = residual.replace(u, "")
        if u.startswith("https://"):
            residual = residual.replace(u[len("https://") :], "")
    residual = re.sub(r"[\s.,;:!?()<>\[\]\"'`]+", "", residual)
    return residual == ""


def _is_greeting(text: str) -> bool:
    """True for trivial greetings/farewells with no real query content."""
    s = (text or "").strip()
    if not s or len(s) > 40:
        return False
    return bool(_GREETING_RE.match(s))


# --- LLM JSON parsing ----------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _try_parse_json(raw: str) -> Optional[dict]:
    """Best-effort JSON parse.

    LLMs sometimes wrap JSON in code fences or chatter. We:
    1. Try ``json.loads`` directly.
    2. Strip ```` ```json ... ``` ```` fences and retry.
    3. Extract the largest ``{...}`` substring and retry.
    Returns ``None`` if nothing parses to a ``dict``.
    """
    if not raw:
        return None
    s = raw.strip()
    # 1. direct
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return v
    except json.JSONDecodeError:
        pass
    # 2. code-fence strip
    if s.startswith("```"):
        fenced = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        fenced = re.sub(r"```\s*$", "", fenced)
        try:
            v = json.loads(fenced)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            pass
    # 3. substring match (largest object)
    m = _JSON_OBJECT_RE.search(s)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            pass
    return None


def _coerce_bool(v: Any) -> bool:
    """Coerce arbitrary LLM-emitted truthiness to a strict ``bool``."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1", "y"}
    if isinstance(v, (int, float)):
        return bool(v)
    return False


def _coerce_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _normalise_primary(v: Any) -> PrimaryType:
    s = _coerce_str(v).lower()
    if s in _ALLOWED_PRIMARY:
        return s  # type: ignore[return-value]
    return "general"


def _normalise_freshness(v: Any) -> Freshness:
    s = _coerce_str(v).lower()
    if s in _ALLOWED_FRESHNESS:
        return s  # type: ignore[return-value]
    return "any"


def _normalise_depth(v: Any) -> DepthHint:
    s = _coerce_str(v).lower()
    if s in _ALLOWED_DEPTH:
        return s  # type: ignore[return-value]
    return "medium"


# --- Prompt assembly -----------------------------------------------------

# Inlined prompt template — mirrors ``prompts/classifier.md``. We keep an
# in-code copy so the classifier remains importable in environments where
# the prompt file path is unavailable (e.g. unit tests). The on-disk file
# is the source of truth for human review.
_PROMPT_TEMPLATE = """\
You are the unified query classifier for the A0_Fauxplexica answering engine.
You perform TWO orthogonal classifications in a single JSON object:

1) ROUTING — which tools should fire (search backends, widgets).
2) STYLE   — how the composer should write the answer.

You also produce a self-contained rewrite of the user's question and
refine the regex-prefilled URL list.

Return STRICT JSON ONLY, no commentary, no code fences. Schema:

{{
  "routing": {{
    "skip_search": bool,
    "personal_search": bool,
    "academic_search": bool,
    "discussion_search": bool,
    "widgets": {{"weather": bool, "stock": bool, "calculation": bool}}
  }},
  "style": {{
    "primary_type": one of ["general","academic_research","recent_news","weather",
                            "people","coding","recipe","translation",
                            "creative_writing","science_math","url_lookup"],
    "freshness": one of ["any","week","day"],
    "depth_hint": one of ["short","medium","deep"]
  }},
  "standalone_followup": string,
  "detected_urls": list[string]
}}

Field rules (read carefully):
- ROUTING and STYLE are independent. Setting a widget true does NOT force
  skip_search; news-style answers may still need academic results, etc.
- skip_search=true ONLY when the answer is fully derivable from general
  knowledge / chat history / widgets, with no need to consult the web.
- academic_search=true for scholarly, peer-reviewed, scientific questions.
- discussion_search=true for opinion/community/reddit-style questions.
- widgets.weather=true ONLY when the user asks for current/forecast weather
  for a real place. widgets.stock=true ONLY for live ticker prices / charts.
  widgets.calculation=true for arithmetic / math expressions the user wants
  evaluated.
- style.primary_type drives composer template selection. Use "url_lookup"
  if the user's intent is to read/summarise a specific URL.
- style.freshness="day" or "week" for news/time-sensitive questions; else
  "any". Plumbs to SearxNG time_range.
- style.depth_hint advises composer verbosity: "short" for quick facts,
  "medium" default, "deep" for research-style answers.
- standalone_followup MUST be a question/instruction that makes sense
  WITHOUT chat history (resolve pronouns/anaphora). If the input already
  stands alone, echo it verbatim.
- detected_urls: refine the prefilled list. Keep all real URLs; drop
  obvious noise; do not invent new URLs not present in the input.
- If detected_urls is non-empty AND the user clearly wants info FROM that
  URL, prefer style.primary_type="url_lookup".

Enabled sources (caller's settings) — flags for unavailable sources will be
forced false post-hoc, but you should still respect them:
{enabled_sources}

Enabled widgets (caller's settings):
{enabled_widgets}

Regex-prefilled URLs (authoritative seed; you may add/remove but only from
URLs present in the input text):
{prefilled_urls}

Recent chat history (oldest → newest):
{chat_history}

User query:
{query}

Return the JSON object now.
"""


def _format_history(history: Iterable[dict] | None) -> str:
    """Render chat history as a compact ``role: content`` transcript.

    Accepts the A0 message shape ``{"role": "user"|"assistant", "content": str}``
    or anything dict-like with those keys. Unknown shapes are stringified.
    """
    if not history:
        return "(empty)"
    lines: list[str] = []
    for msg in history:
        if isinstance(msg, dict):
            role = str(msg.get("role", "?"))
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            lines.append(f"{role}: {content}")
        else:
            lines.append(str(msg))
    return "\n".join(lines) if lines else "(empty)"


# --- Public API ----------------------------------------------------------


def _safe_defaults(
    query: str,
    detected_urls: list[str],
    reason: Optional[str] = None,
) -> ClassifierOutput:
    """Construct a conservative ``general`` envelope.

    Used when (a) the fast-path doesn't trigger and (b) the LLM call fails
    or returns unparseable output. Search is allowed (skip_search=False)
    because suppressing it would silently break user queries.
    """
    return ClassifierOutput(
        routing=RoutingFlags(
            skip_search=False,
            personal_search=False,
            academic_search=False,
            discussion_search=False,
            widgets=RoutingWidgets(),
        ),
        style=StyleHints(
            primary_type="url_lookup" if detected_urls else "general",
            freshness="any",
            depth_hint="medium",
        ),
        standalone_followup=(query or "").strip(),
        detected_urls=list(detected_urls),
        _fastpath_reason=reason,
    )


def _apply_gates(
    out: ClassifierOutput,
    enabled_sources: set[str],
    enabled_widgets: set[str],
) -> ClassifierOutput:
    """AND-gate routing flags against caller-supplied enables.

    The classifier (or the LLM behind it) may *suggest* routing into a
    backend the orchestrator hasn't enabled; we clip those suggestions
    here so downstream stages can trust the envelope without re-checking.
    """
    if "academic" not in enabled_sources:
        out.routing.academic_search = False
    if "discussions" not in enabled_sources:
        out.routing.discussion_search = False
    # `web` is implied for any non-skip search; if web is disabled we leave
    # skip_search alone (Orchy decides whether to bail completely).
    if "weather" not in enabled_widgets:
        out.routing.widgets.weather = False
    if "stock" not in enabled_widgets:
        out.routing.widgets.stock = False
    if "calculation" not in enabled_widgets:
        out.routing.widgets.calculation = False
    return out


def _try_fastpath(
    query: str,
    detected_urls: list[str],
    enabled_widgets: set[str],
) -> Optional[ClassifierOutput]:
    """Run deterministic fast-path heuristics.

    Returns a fully-formed :class:`ClassifierOutput` when a trivial input is
    recognised, else ``None`` (LLM call needed).
    """
    q = (query or "").strip()
    if not q:
        return ClassifierOutput(
            routing=RoutingFlags(skip_search=True),
            style=StyleHints(primary_type="general"),
            standalone_followup="",
            detected_urls=[],
            _fastpath_reason="empty_query",
        )

    # Pure math expression → calculation widget, skip search.
    if _is_pure_math(q):
        return ClassifierOutput(
            routing=RoutingFlags(
                skip_search=True,
                widgets=RoutingWidgets(
                    calculation="calculation" in enabled_widgets,
                ),
            ),
            style=StyleHints(primary_type="science_math", depth_hint="short"),
            standalone_followup=q,
            detected_urls=[],
            _fastpath_reason="pure_math",
        )

    # Single URL with no surrounding question → url lookup.
    if _is_lone_url(q, detected_urls):
        return ClassifierOutput(
            routing=RoutingFlags(skip_search=False),
            style=StyleHints(primary_type="url_lookup"),
            standalone_followup=q,
            detected_urls=list(detected_urls),
            _fastpath_reason="lone_url",
        )

    # Greeting / farewell → no search, general.
    if _is_greeting(q):
        return ClassifierOutput(
            routing=RoutingFlags(skip_search=True),
            style=StyleHints(primary_type="general", depth_hint="short"),
            standalone_followup=q,
            detected_urls=[],
            _fastpath_reason="greeting",
        )
    return None


async def classify(
    query: str,
    chat_history: list[dict],
    enabled_sources: set[str],
    enabled_widgets: set[str],
    llm: LLMCall,
) -> ClassifierOutput:
    """Classify *query* into the unified routing+style schema.

    Parameters
    ----------
    query:
        The raw user message to classify.
    chat_history:
        Recent ``{"role", "content"}`` messages, oldest-first. Used by the
        LLM to rewrite anaphoric questions into a self-contained
        ``standalone_followup``.
    enabled_sources:
        Subset of ``{'web','academic','discussions'}`` from settings. The
        classifier output is AND-gated against these.
    enabled_widgets:
        Subset of ``{'weather','stock','calculation'}`` from settings.
        Output widget flags are AND-gated against these.
    llm:
        Async callable ``(system, user) -> response_text``. Use
        ``agent.call_utility_model`` in production, or a mock in tests.

    Returns
    -------
    ClassifierOutput
        See :class:`helpers.types.ClassifierOutput`. Always returns; LLM
        failures degrade to safe defaults rather than raising.
    """
    # Defensive coercion of the set-valued args; callers sometimes pass
    # lists by mistake.
    enabled_sources = set(enabled_sources or ())
    enabled_widgets = set(enabled_widgets or ())
    # Drop unknown keys quietly — guards against typos like "web_search".
    enabled_sources &= _KNOWN_SOURCES
    enabled_widgets &= _KNOWN_WIDGETS

    # 1. Deterministic URL pre-fill — always runs.
    detected_urls = _extract_urls(query)

    # 2. Fast-path heuristics.
    fast = _try_fastpath(query, detected_urls, enabled_widgets)
    if fast is not None:
        return _apply_gates(fast, enabled_sources, enabled_widgets)

    # 3. LLM-backed classification.
    system_msg = (
        "You are a strict JSON-emitting classifier. "
        "Output ONLY the JSON object specified in the user prompt. "
        "No prose, no markdown fences."
    )
    user_msg = _PROMPT_TEMPLATE.format(
        enabled_sources=sorted(enabled_sources) or ["(none)"],
        enabled_widgets=sorted(enabled_widgets) or ["(none)"],
        prefilled_urls=detected_urls or ["(none)"],
        chat_history=_format_history(chat_history),
        query=query or "",
    )

    try:
        raw = await llm(system_msg, user_msg)
    except Exception as exc:  # noqa: BLE001 - we want to swallow ALL LLM errors
        log.warning("classifier: LLM call failed: %s", exc)
        return _apply_gates(
            _safe_defaults(query, detected_urls, reason=f"llm_error:{type(exc).__name__}"),
            enabled_sources,
            enabled_widgets,
        )

    parsed = _try_parse_json(raw or "")
    if not parsed:
        log.warning("classifier: failed to parse LLM JSON; raw=%r", (raw or "")[:200])
        return _apply_gates(
            _safe_defaults(query, detected_urls, reason="json_parse_error"),
            enabled_sources,
            enabled_widgets,
        )

    # 4. Normalise + validate every field.
    routing_in = parsed.get("routing") or {}
    widgets_in = (routing_in.get("widgets") if isinstance(routing_in, dict) else {}) or {}
    style_in = parsed.get("style") or {}

    routing = RoutingFlags(
        skip_search=_coerce_bool(routing_in.get("skip_search")),
        personal_search=_coerce_bool(routing_in.get("personal_search")),
        academic_search=_coerce_bool(routing_in.get("academic_search")),
        discussion_search=_coerce_bool(routing_in.get("discussion_search")),
        widgets=RoutingWidgets(
            weather=_coerce_bool(widgets_in.get("weather")),
            stock=_coerce_bool(widgets_in.get("stock")),
            calculation=_coerce_bool(widgets_in.get("calculation")),
        ),
    )

    style = StyleHints(
        primary_type=_normalise_primary(style_in.get("primary_type")),
        freshness=_normalise_freshness(style_in.get("freshness")),
        depth_hint=_normalise_depth(style_in.get("depth_hint")),
    )

    # standalone_followup: fall back to the raw query if the LLM omitted it.
    standalone = _coerce_str(parsed.get("standalone_followup"))
    if not standalone:
        standalone = (query or "").strip()

    # detected_urls: trust regex; let the LLM REMOVE noise but not invent.
    llm_urls_raw = parsed.get("detected_urls") or []
    if isinstance(llm_urls_raw, list):
        llm_urls = {u.strip() for u in llm_urls_raw if isinstance(u, str)}
        # keep only URLs the regex saw (or close variants); preserve order
        final_urls = [u for u in detected_urls if u in llm_urls] or detected_urls
    else:
        final_urls = detected_urls

    out = ClassifierOutput(
        routing=routing,
        style=style,
        standalone_followup=standalone,
        detected_urls=list(final_urls),
        _fastpath_reason=None,
    )

    # 5. AND-gate against caller enables before returning.
    return _apply_gates(out, enabled_sources, enabled_widgets)


__all__ = ["classify", "LLMCall"]
