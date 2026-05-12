"""Block/event stream abstraction for incremental Fauxplexica responses.

This module is intentionally transport-agnostic. API/WebUI layers can consume
``BlockStream.events`` or ``BlockStream.queue`` and serialize each event as
Vane-like NDJSON/SSE, but no socket or HTTP behavior lives here.

Wire-protocol parity (per RECON_DIFF cycle 1 fixes 5.1 and 5.2):

- ``block`` events are emitted as ``{"type": "block", "block": {...}, "data": {"block": {...}}}``
  so both Vane upstream consumers (top-level ``block`` field) and existing
  A0_Fauxplexica WebUI/test consumers (``data.block``) keep working.
- ``updateBlock`` events are emitted with both upstream-compatible
  ``blockId``/``patch`` keys and legacy ``data.id``/``data.ops`` keys.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, ClassVar
from uuid import uuid4

__all__ = ["Block", "BlockStream"]


@dataclass
class Block:
    """A renderable response block maintained by :class:`BlockStream`.

    Attributes:
        id: Stable block identifier used by subsequent ``updateBlock`` events.
        type: WebUI block type, e.g. ``reasoning``, ``source``, or ``text``.
        data: JSON-serializable payload owned by the block renderer.
    """

    id: str
    type: str
    data: dict[str, Any]


class BlockStream:
    """In-memory event/block recorder for Fauxplexica streaming.

    The stream keeps both a chronological event list and an ``asyncio.Queue`` so
    later API code can either snapshot all generated events or consume them as
    they arrive. Event envelopes are plain dictionaries and use the event names
    expected by the Vane-like NDJSON protocol.
    """

    BLOCK_TYPES: ClassVar[set[str]] = {
        "reasoning",
        "searching",
        "search_results",
        "reading",
        "upload_searching",
        "upload_search_results",
        "source",
        "widget",
        "text",
    }
    EVENT_TYPES: ClassVar[set[str]] = {
        "init",
        "block",
        "updateBlock",
        "researchComplete",
        "response",
        "messageEnd",
        "done",
        "error",
    }

    def __init__(self) -> None:
        """Create an empty stream with in-memory storage and an event queue."""
        self.events: list[dict[str, Any]] = []
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.blocks: list[Block] = []
        self._blocks_by_id: dict[str, Block] = {}
        self.closed = False

    def all_blocks(self) -> list[dict[str, Any]]:
        """Return all known blocks as JSON-serializable dictionaries."""
        return [asdict(block) for block in self.blocks]

    async def emit(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Record and enqueue a generic protocol event envelope.

        Args:
            event_type: One of the supported protocol envelope names.
            data: JSON-serializable event payload (placed under ``data``).

        Returns:
            The emitted event dictionary.
        """
        if event_type not in self.EVENT_TYPES:
            raise ValueError(f"unsupported event type: {event_type}")
        event = {"type": event_type, "data": deepcopy(data)}
        self.events.append(event)
        await self.queue.put(event)
        return event

    async def emit_block(self, block_type: str, data: dict[str, Any]) -> Block:
        """Create a block and emit a Vane-compatible ``block`` event."""
        if block_type not in self.BLOCK_TYPES:
            raise ValueError(f"unsupported block type: {block_type}")
        block = Block(id=uuid4().hex, type=block_type, data=deepcopy(data))
        self.blocks.append(block)
        self._blocks_by_id[block.id] = block
        envelope = {
            "type": "block",
            "block": asdict(block),
            "data": {"block": asdict(block)},
        }
        self.events.append(envelope)
        await self.queue.put(envelope)
        return block

    async def update_block(self, block_id: str, patch_ops: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply minimal JSON-Patch updates and emit ``updateBlock``.

        Supported mutation semantics are deliberately small for Phase 1: only
        ``replace`` operations whose path starts with ``/data/`` are applied to
        the in-memory block. Raw patch operations are preserved in the emitted
        event so API/WebUI clients can apply the same patch independently.
        """
        block = self._blocks_by_id.get(block_id)
        if block is None:
            raise KeyError(f"unknown block id: {block_id}")

        for op in patch_ops:
            if op.get("op") != "replace":
                continue
            path = str(op.get("path") or "")
            if not path.startswith("/data/"):
                continue
            self._replace_data_path(block.data, path[len("/data/") :], op.get("value"))

        envelope = {
            "type": "updateBlock",
            "blockId": block_id,
            "patch": deepcopy(patch_ops),
            "data": {"id": block_id, "ops": deepcopy(patch_ops)},
        }
        self.events.append(envelope)
        await self.queue.put(envelope)
        return envelope

    async def close(self) -> None:
        """Mark the stream closed and emit the terminal ``done`` event once."""
        if self.closed:
            return
        self.closed = True
        await self.emit("done", {})

    @staticmethod
    def _replace_data_path(data: dict[str, Any], raw_path: str, value: Any) -> None:
        """Apply a JSON-Pointer-style replacement under a block's ``data`` key."""
        parts = [part.replace("~1", "/").replace("~0", "~") for part in raw_path.split("/") if part]
        if not parts:
            return
        cursor: Any = data
        for part in parts[:-1]:
            if isinstance(cursor, dict):
                cursor = cursor.setdefault(part, {})
            elif isinstance(cursor, list) and part.isdigit():
                cursor = cursor[int(part)]
            else:
                return
        last = parts[-1]
        if isinstance(cursor, dict):
            cursor[last] = value
        elif isinstance(cursor, list) and last.isdigit():
            index = int(last)
            if 0 <= index < len(cursor):
                cursor[index] = value
