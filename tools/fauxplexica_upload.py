"""A0 tool wrapper for ingesting files into Fauxplexica upload RAG."""

from __future__ import annotations

import json
from pathlib import Path

from helpers.tool import Response, Tool
from pathlib import Path
import sys

_PLUGIN_PARENT = Path(__file__).resolve().parents[2]
if str(_PLUGIN_PARENT) not in sys.path:
    sys.path.append(str(_PLUGIN_PARENT))

from a0_fauxplexica.helpers.uploads import UploadsManager


class FauxplexicaUpload(Tool):
    """Index one local file into the current chat context's upload namespace."""

    async def execute(self, file_path: str, file_id: str | None = None) -> Response:
        manager = UploadsManager(self.agent.context)
        result = await manager.ingest_file(file_path, file_id=file_id)
        if isinstance(result, dict) and result.get("error"):
            payload = {"error": result["error"], "file_path": file_path}
            return Response(message=json.dumps(payload), break_loop=False, additional=payload)

        details = manager.last_ingest_result or {}
        payload = {
            "file_id": str(result),
            "chunks_indexed": int(details.get("chunks_indexed", 0)),
            "filename": details.get("filename") or Path(file_path).name,
        }
        return Response(message=json.dumps(payload), break_loop=False, additional=payload)
