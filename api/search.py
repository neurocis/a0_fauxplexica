"""Fauxplexica programmatic search API endpoint.

A0 plugin route convention exposes this file at::

    POST /api/plugins/a0_fauxplexica/search

The endpoint is intentionally thin: it validates/normalises the HTTP request,
loads plugin configuration, and delegates all search work to
``helpers.orchestrator.run_fauxplexica_search``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# A0 loads plugin API files dynamically. When unit tests add the plugin root to
# sys.path, ``helpers`` can resolve to this plugin's helpers package instead of
# the framework package. Import framework API utilities with /a0 first.
_FRAMEWORK_ROOT = Path("/a0").resolve()
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_SYS_PATH = list(sys.path)
try:
    sys.path = [p for p in sys.path if Path(p or os.getcwd()).resolve() != _PLUGIN_ROOT]
    if str(_FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(_FRAMEWORK_ROOT))
    try:
        from helpers.api import ApiHandler, Request, Response
        from helpers import plugins
    except ModuleNotFoundError as exc:  # pragma: no cover - minimal test env fallback
        if exc.name != "flask":
            raise

        class Response:  # type: ignore[no-redef]
            def __init__(self, response="", status=200, mimetype="text/plain"):
                self._response = response
                self.status_code = status
                self.mimetype = mimetype

            def get_data(self, as_text=False):
                return self._response if as_text else str(self._response).encode()

        class Request:  # type: ignore[no-redef]
            pass

        class ApiHandler:  # type: ignore[no-redef]
            @classmethod
            def get_methods(cls):
                return ["POST"]

        class _PluginsFallback:
            @staticmethod
            def get_plugin_config(*_args, **_kwargs):
                return {}

        plugins = _PluginsFallback()
finally:
    sys.path = _ORIGINAL_SYS_PATH

from plugins.a0_fauxplexica.helpers.blockstream import BlockStream
from plugins.a0_fauxplexica.helpers.orchestrator import run_fauxplexica_search

PLUGIN_NAME = "a0_fauxplexica"
VALID_MODES = {"speed", "balanced", "quality"}
DEFAULT_SOURCES = {"web", "academic", "discussions"}
DEFAULT_WIDGETS = {"weather", "calculator", "calculation", "stock"}
STREAM_EVENT_MIMETYPE = "text/event-stream"


class FauxplexicaSearch(ApiHandler):
    """POST search endpoint for programmatic Fauxplexica clients."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        query = str(input.get("query") or "").strip()
        if not query:
            return _json_error("missing_query", "Request field 'query' is required.", status=400)

        ctxid = str(input.get("ctxid") or input.get("context_id") or "").strip()
        context = None
        agent = None
        if ctxid:
            context = self.use_context(ctxid, create_if_not_exists=True)
            agent = getattr(context, "agent0", None) or (
                context.get_agent() if hasattr(context, "get_agent") else None
            )

        config = _load_config(agent=agent)
        mode = _normalise_mode(input.get("mode"), config)
        enabled_sources = _normalise_enabled(
            input.get("enabled_sources"),
            config.get("sources"),
            DEFAULT_SOURCES,
        )
        enabled_widgets = _normalise_enabled(
            input.get("enabled_widgets"),
            config.get("widgets_enabled"),
            DEFAULT_WIDGETS,
        )
        try:
            chat_history = _normalise_list(input.get("chat_history"), "chat_history")
            file_ids = [str(item) for item in _normalise_list(input.get("file_ids"), "file_ids")]
        except ValueError as exc:
            return _json_error("invalid_request", str(exc), status=400)
        stream_requested = bool(input.get("stream"))

        # BYO SearxNG only: do not hardcode a URL. If source search is enabled,
        # surface the missing config clearly before the pipeline reaches Reggie.
        if enabled_sources and not str(config.get("searxng_url") or "").strip():
            return _json_error(
                "missing_searxng_url",
                "Fauxplexica requires plugin config 'searxng_url' when search sources are enabled.",
                status=400,
                details={"enabled_sources": sorted(enabled_sources)},
            )

        block_stream = BlockStream()
        try:
            result = await run_fauxplexica_search(
                query=query,
                chat_history=chat_history,
                mode=mode,
                enabled_sources=enabled_sources,
                enabled_widgets=enabled_widgets,
                file_ids=file_ids,
                config=config,
                agent_context=context,
                block_stream=block_stream,
            )
        except Exception as exc:  # noqa: BLE001 - API must return structured errors
            if stream_requested:
                payload = [
                    {"type": "error", "data": {"code": "search_failed", "message": str(exc)}},
                    {"type": "done", "data": {}},
                ]
                return Response(
                    response="".join(json.dumps(evt, ensure_ascii=False) + "\n" for evt in payload),
                    status=500,
                    mimetype=STREAM_EVENT_MIMETYPE,
                )
            return _json_error("search_failed", str(exc), status=500)

        if stream_requested:
            events = list(block_stream.events)
            if not events or events[-1].get("type") != "done":
                events.append({"type": "done", "data": {}})
            return Response(
                response="".join(json.dumps(evt, ensure_ascii=False) + "\n" for evt in events),
                status=200,
                mimetype=STREAM_EVENT_MIMETYPE,
            )

        return _response_payload(result, mode=mode)


def _load_config(*, agent: Any = None) -> dict[str, Any]:
    cfg = plugins.get_plugin_config(PLUGIN_NAME, agent=agent) or {}
    return dict(cfg) if isinstance(cfg, dict) else {}


def _normalise_mode(raw: Any, config: dict[str, Any]) -> str:
    mode = str(raw or config.get("default_mode") or "balanced").strip().lower()
    return mode if mode in VALID_MODES else "balanced"


def _normalise_enabled(raw: Any, config_section: Any, defaults: set[str]) -> set[str]:
    if raw is not None:
        if isinstance(raw, dict):
            return {str(k) for k, v in raw.items() if bool(v)}
        if isinstance(raw, (list, tuple, set)):
            return {str(v) for v in raw if str(v).strip()}
        return set()
    if isinstance(config_section, dict):
        return {str(k) for k, v in config_section.items() if bool(v)}
    if isinstance(config_section, (list, tuple, set)):
        return {str(v) for v in config_section if str(v).strip()}
    return set(defaults)


def _normalise_list(raw: Any, field: str) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    raise ValueError(f"Request field '{field}' must be an array.")


def _response_payload(result: dict[str, Any], *, mode: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {"answer": str(result)}
    return {
        "answer": result.get("answer", ""),
        "classification": result.get("classification") or {},
        "sources": result.get("sources") or [],
        "citations": result.get("citations") or [],
        "widgets": result.get("widgets") or [],
        "mode": result.get("mode") or mode,
        "blocks": result.get("blocks") or [],
    }


def _json_error(code: str, message: str, *, status: int, details: dict | None = None) -> Response:
    payload: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return Response(
        response=json.dumps(payload, ensure_ascii=False),
        status=status,
        mimetype="application/json",
    )
