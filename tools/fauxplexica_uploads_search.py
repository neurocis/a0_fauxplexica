"""A0 tool wrapper for querying Fauxplexica uploaded-file content."""

from __future__ import annotations

import json
from typing import Any

from helpers.tool import Response, Tool
from pathlib import Path
import sys

_PLUGIN_PARENT = Path(__file__).resolve().parents[2]
if str(_PLUGIN_PARENT) not in sys.path:
    sys.path.append(str(_PLUGIN_PARENT))

from a0_fauxplexica.helpers.uploads import UploadsManager


class FauxplexicaUploadsSearch(Tool):
    """Search uploaded-file chunks in the current chat context."""

    async def execute(
        self,
        query: str,
        file_ids: list[str] | str | None = None,
        k: int = 8,
    ) -> Response:
        parsed_file_ids = self._parse_file_ids(file_ids)
        manager = UploadsManager(self.agent.context)
        results = await manager.search(query, parsed_file_ids, k=k)
        payload: dict[str, Any] = {"query": query, "file_ids": parsed_file_ids, "results": results}
        return Response(message=json.dumps(payload), break_loop=False, additional=payload)

    @staticmethod
    def _parse_file_ids(value: list[str] | str | None) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item)]
        except Exception:
            pass
        return [part.strip() for part in text.split(",") if part.strip()]
