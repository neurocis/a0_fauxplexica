"""Fauxplexica providers/configuration discovery API endpoint.

A0 plugin route convention exposes this file at::

    GET /api/plugins/a0_fauxplexica/providers
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

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

PLUGIN_NAME = "a0_fauxplexica"


class FauxplexicaProviders(ApiHandler):
    """Read-only provider/source/widget/mode listing for Fauxplexica clients."""

    @classmethod
    def get_methods(cls) -> list[str]:
        return ["GET", "POST"]

    async def process(self, input: dict, request: Request) -> dict | Response:
        ctxid = str(input.get("ctxid") or input.get("context_id") or request.args.get("ctxid", "")).strip()
        context = None
        agent = None
        if ctxid:
            context = self.use_context(ctxid, create_if_not_exists=True)
            agent = getattr(context, "agent0", None) or (
                context.get_agent() if hasattr(context, "get_agent") else None
            )

        config = _load_config(agent=agent)
        model_registry = _load_model_registry()
        sources_cfg = config.get("sources") if isinstance(config.get("sources"), dict) else {}
        widgets_cfg = config.get("widgets_enabled") if isinstance(config.get("widgets_enabled"), dict) else {}
        searxng_url = str(config.get("searxng_url") or "").strip()

        return {
            "ok": True,
            "ctxid": ctxid or None,
            "providers": [
                {
                    "id": "searxng",
                    "type": "search",
                    "label": "SearxNG",
                    "configured": bool(searxng_url),
                    "byo": True,
                }
            ],
            "sources": [
                {"id": "web", "label": "Web", "enabled": bool(sources_cfg.get("web", True))},
                {"id": "academic", "label": "Academic", "enabled": bool(sources_cfg.get("academic", True))},
                {"id": "discussions", "label": "Social", "enabled": bool(sources_cfg.get("discussions", False))},
            ],
            "widgets": [
                {"id": "weather", "label": "Weather", "enabled": bool(widgets_cfg.get("weather", True))},
                {"id": "calculator", "label": "Calculator", "enabled": bool(widgets_cfg.get("calculator", widgets_cfg.get("calculation", True)))},
                {"id": "stock", "label": "Stock", "enabled": bool(widgets_cfg.get("stock", True))},
            ],
            "modes": [
                {"id": "speed", "label": "Speed", "default": config.get("default_mode") == "speed"},
                {"id": "balanced", "label": "Balanced", "default": config.get("default_mode", "balanced") == "balanced"},
                {"id": "quality", "label": "Quality", "default": config.get("default_mode") == "quality"},
            ],
            "model_registry": model_registry,
            "limits": {
                "max_sources_per_query": config.get("max_sources_per_query", 12),
                "context_budget_chars": config.get("context_budget_chars", 60000),
                "quality_max_iterations": config.get("quality_max_iterations", 10),
            },
        }


def _load_config(*, agent: Any = None) -> dict[str, Any]:
    cfg = plugins.get_plugin_config(PLUGIN_NAME, agent=agent) or {}
    return dict(cfg) if isinstance(cfg, dict) else {}


def _load_model_registry() -> dict[str, Any]:
    """Return _model_config registry data when available, otherwise empty lists."""
    try:
        from plugins._model_config.helpers import model_config

        return {
            "chat_providers": model_config.get_chat_providers(),
            "embedding_providers": model_config.get_embedding_providers(),
            "presets": model_config.get_presets(),
        }
    except Exception as exc:  # noqa: BLE001 - optional/lazy integration
        return {
            "chat_providers": [],
            "embedding_providers": [],
            "presets": [],
            "warning": str(exc),
        }
