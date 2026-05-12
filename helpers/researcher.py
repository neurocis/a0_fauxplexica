"""ReAct-style research loop for A0_Fauxplexica."""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from helpers.classifier import ClassifierOutput
from helpers.extractor import extract_facts
from helpers.picker import pick_results
from helpers.reranker import rerank_results
from helpers.scraper import scrape_url as scrape_page_url
from helpers.searxng_client import SearxClient
from helpers.types import SearchResult
from helpers.uploads import UploadsManager

__all__ = ["ResearchStep", "ResearchOutput", "Researcher", "research", "dedupe_search_results"]

log = logging.getLogger(__name__)
Mode = Literal["speed", "balanced", "quality"]


@dataclass
class ResearchStep:
    """Visible, non-chain-of-thought research event."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchOutput:
    """Research result consumed by Orchy/Compo/Citer."""

    findings: list[str]
    search_findings: list[SearchResult]
    steps: list[ResearchStep]


class Researcher:
    """Mode-aware ReAct-style research engine.

    The loop records concise visible summaries before tools, gathers applicable
    web/academic/discussion/upload evidence, and returns URL-deduped sources.
    """

    def __init__(self, *, query: str, classification: ClassifierOutput, chat_history: list[dict], mode: Mode,
                 enabled_sources: set[str], file_ids: list[str] | None, llm, embedder, config: dict,
                 agent_context=None, block_stream=None) -> None:
        self.query = query
        self.classification = classification
        self.chat_history = chat_history
        self.mode = mode
        self.enabled_sources = set(enabled_sources or set())
        self.file_ids = list(file_ids or [])
        self.llm = llm
        self.embedder = embedder
        self.config = config or {}
        self.agent_context = agent_context
        self.block_stream = block_stream
        self.steps: list[ResearchStep] = []
        self._all_results: list[SearchResult] = []
        self._findings: list[str] = []
        self._read_urls: set[str] = set()

    async def research(self) -> ResearchOutput:
        """Run the research loop."""
        max_iterations = self._max_iterations()
        if self.classification.routing.skip_search and not self.file_ids:
            await self._record("reasoning", {"summary": "Search skipped by classifier routing."})
            return self._output()

        for iteration in range(1, max_iterations + 1):
            actions = self._actions_for_iteration(iteration)
            if not actions:
                await self._record("reasoning", {"summary": "No applicable tool calls; implicit done.", "iteration": iteration})
                break

            await self._record("reasoning", {"summary": self._iteration_summary(iteration, actions), "iteration": iteration})
            made_progress = False
            for action in actions:
                try:
                    results = await self._run_action(action)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Research action %s failed: %s", action, exc)
                    await self._record("reasoning", {"summary": f"{action} failed and was skipped.", "error": str(exc)})
                    results = []
                if results:
                    made_progress = True
                    self._all_results.extend(results)
                    self._findings.extend(_findings_from_results(results))

            if self.mode == "speed":
                await self._record("reasoning", {"summary": "Speed-mode research complete after first action pass."})
                break
            if not made_progress:
                await self._record("reasoning", {"summary": "Tool output was empty; implicit done.", "iteration": iteration})
                break
            if iteration >= max_iterations:
                await self._record("reasoning", {"summary": f"{self.mode.title()}-mode iteration guard reached; stopping."})

        return self._output()

    def _max_iterations(self) -> int:
        if self.mode == "speed":
            return 2
        if self.mode == "balanced":
            return 6
        return max(1, int(self.config.get("quality_max_iterations", 10)))

    def _actions_for_iteration(self, iteration: int) -> list[str]:
        if iteration > 1:
            return []
        routing = self.classification.routing
        actions: list[str] = []
        if "web" in self.enabled_sources:
            actions.append("web_search")
        if routing.academic_search and "academic" in self.enabled_sources:
            actions.append("academic_search")
        if routing.discussion_search and ({"discussion", "discussions"} & self.enabled_sources):
            actions.append("discussion_search")
        if self.file_ids or (routing.personal_search and self.agent_context is not None):
            actions.append("uploads_search")
        return actions

    def _iteration_summary(self, iteration: int, actions: Sequence[str]) -> str:
        return f"Iteration {iteration}: using {', '.join(actions)} in {self.mode} mode."

    async def _run_action(self, action: str) -> list[SearchResult]:
        if action == "web_search":
            return await self._search_action(action, categories=["general"])
        if action == "academic_search":
            return await self._search_action(action, categories=["science"])
        if action == "discussion_search":
            return await self._search_action(action, categories=["social media"])
        if action == "uploads_search":
            return await self._uploads_search()
        if action == "done":
            return []
        raise ValueError(f"Unknown research action: {action}")

    async def _search_action(self, action: str, *, categories: list[str]) -> list[SearchResult]:
        await self._record("searching", {"action": action, "query": self.query, "categories": categories})
        raw_results = await self._searx_search(categories=categories)
        await self._record("search_results", {"action": action, "count": len(raw_results)})
        if self.mode in {"speed", "balanced"}:
            # Apply required URL-level content concat before embedding dedup so
            # same-URL snippets are not lost when reranker drops near-duplicates.
            raw_results = _dedupe_raw_results(raw_results)
            ranked = await rerank_results(
                self.query, raw_results, self.embedder,
                keep_threshold=float(_nested_get(self.config, ["rerank", "cosine_keep_threshold"], 0.5)),
                dedup_threshold=float(_nested_get(self.config, ["rerank", "cosine_dedup_threshold"], 0.75)),
                top_k=int(self.config.get("max_sources_per_query", 20)),
            )
            return [_to_search_result(item) for item in ranked]
        return await self._quality_search(raw_results)

    async def _searx_search(self, *, categories: list[str]) -> list[dict[str, Any]]:
        base_url = self.config.get("searxng_url") or _nested_get(self.config, ["searxng", "url"], "")
        if not base_url:
            log.warning("No searxng_url configured; returning no web results")
            return []
        pages = int(_nested_get(self.config, ["searxng", "pagination_pages"], self.config.get("pagination_pages", 1)))
        safesearch = int(_nested_get(self.config, ["searxng", "safesearch"], self.config.get("safesearch", 0)))
        time_range = self.classification.style.freshness or _nested_get(self.config, ["searxng", "time_range_default"], "any")
        async with SearxClient(base_url) as client:
            return await client.search(self.query, categories=categories, time_range=time_range, safesearch=safesearch, pages=pages)

    async def _quality_search(self, raw_results: list[dict[str, Any]]) -> list[SearchResult]:
        picked_indices = await pick_results(self.query, raw_results, self.llm, max_picks=int(self.config.get("quality_max_picks", 3)))
        if not picked_indices:
            picked_indices = list(range(min(3, len(raw_results))))
        semaphore = asyncio.Semaphore(max(1, int(self.config.get("scrape_extractor_concurrency", 3))))
        timeout = float(self.config.get("scrape_timeout", 20))
        fallback_playwright = bool(_nested_get(self.config, ["webui", "scraper_fallback_playwright"], False))

        async def read_one(idx: int) -> SearchResult | None:
            raw = dict(raw_results[idx])
            url = str(raw.get("url") or "")
            if not url or url in self._read_urls:
                return None
            self._read_urls.add(url)
            await self._record("reading", {"url": url, "title": raw.get("title", "")})
            scraped = await scrape_page_url(url, timeout=timeout, fallback_playwright=fallback_playwright)
            facts = await extract_facts(url, scraped, self.query, self.llm, semaphore=semaphore)
            raw["content"] = facts or scraped or raw.get("content", "")
            result = _to_search_result(raw)
            await self._record("source", {"url": result.url, "title": result.title})
            return result

        read = await asyncio.gather(*(read_one(i) for i in picked_indices), return_exceptions=True)
        out: list[SearchResult] = []
        for item in read:
            if isinstance(item, SearchResult):
                out.append(item)
            elif isinstance(item, Exception):
                log.warning("Quality scrape/extract failed: %s", item)
        return out

    async def _uploads_search(self) -> list[SearchResult]:
        if self.agent_context is None:
            return []
        await self._record("searching", {"action": "uploads_search", "query": self.query, "file_ids": self.file_ids})
        manager = UploadsManager(self.agent_context)
        rows = await manager.search(self.query, self.file_ids or None, k=int(self.config.get("uploads_k", 8)))
        out: list[SearchResult] = []
        for row in rows:
            if row.get("error"):
                continue
            meta = dict(row.get("metadata") or {})
            file_id = meta.get("file_id") or "upload"
            title = meta.get("filename") or f"Uploaded file {file_id}"
            url = f"file://{file_id}#chunk-{meta.get('chunk_index', len(out))}"
            out.append(SearchResult(title=str(title), url=url, content=str(row.get("content") or ""), engine="uploads", score=_safe_float(row.get("score")), category="uploads", extra={"metadata": meta}))
        await self._record("search_results", {"action": "uploads_search", "count": len(out)})
        return out

    async def _record(self, step_type: str, data: dict[str, Any]) -> None:
        self.steps.append(ResearchStep(type=step_type, data=data))
        await _emit_block(self.block_stream, step_type, data)

    def _output(self) -> ResearchOutput:
        return ResearchOutput(findings=list(self._findings), search_findings=dedupe_search_results(self._all_results), steps=list(self.steps))


async def research(*, query: str, classification: ClassifierOutput, chat_history: list[dict], mode: Mode,
                   enabled_sources: set[str], file_ids: list[str] | None, llm, embedder, config: dict,
                   agent_context=None, block_stream=None) -> ResearchOutput:
    """Convenience API for Orchy."""
    return await Researcher(query=query, classification=classification, chat_history=chat_history, mode=mode,
                            enabled_sources=enabled_sources, file_ids=file_ids, llm=llm, embedder=embedder,
                            config=config, agent_context=agent_context, block_stream=block_stream).research()


def dedupe_search_results(results: Sequence[SearchResult]) -> list[SearchResult]:
    """Stable URL-dedup left fold with content concatenation."""
    out: list[SearchResult] = []
    by_url: dict[str, SearchResult] = {}
    for result in results:
        if not result.url:
            out.append(result)
            continue
        existing = by_url.get(result.url)
        if existing is None:
            clone = SearchResult.from_dict(result.to_dict())
            out.append(clone)
            by_url[result.url] = clone
        elif result.content:
            existing.content = f"{existing.content}\n\n{result.content}" if existing.content else result.content
    return out


async def _emit_block(block_stream, block_type: str, data: dict[str, Any]) -> None:
    """Forward a research step to a block-stream-like target.

    Researcher emits Vane block types (``searching``/``search_results``/
    ``reading``/``source``), so the preferred path is
    ``BlockStream.emit_block(block_type, data)``. Falls back to legacy
    callables/writers for older test doubles. Errors never propagate so
    streaming UX problems can't break the research loop.
    """

    if block_stream is None:
        return
    try:
        emit_block = getattr(block_stream, "emit_block", None)
        if emit_block is not None:
            result = emit_block(block_type, data)
            if inspect.isawaitable(result):
                await result
            return
        if callable(block_stream):
            result = block_stream(block_type, data)
            if inspect.isawaitable(result):
                await result
            return
        write = getattr(block_stream, "write", None)
        if write is not None:
            result = write({"type": block_type, "data": data})
            if inspect.isawaitable(result):
                await result
            return
        # Last-ditch: try legacy emit(payload) form for adapters that only
        # expose a single emit(...) entrypoint.
        emit = getattr(block_stream, "emit", None)
        if emit is not None:
            result = emit({"type": block_type, "data": data})
            if inspect.isawaitable(result):
                await result
    except Exception as exc:  # noqa: BLE001 - streaming must not break research
        log.warning("research block_stream emission failed (%s): %s", block_type, exc)


def _to_search_result(raw: SearchResult | dict[str, Any]) -> SearchResult:
    return raw if isinstance(raw, SearchResult) else SearchResult.from_dict(raw)


def _dedupe_raw_results(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable URL-dedup for raw result dicts with content concatenation."""
    out: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    for raw in results:
        item = dict(raw)
        url = str(item.get("url") or "")
        if not url:
            out.append(item)
            continue
        existing = by_url.get(url)
        if existing is None:
            out.append(item)
            by_url[url] = item
        else:
            content = str(item.get("content") or "")
            if content:
                prior = str(existing.get("content") or "")
                existing["content"] = f"{prior}\n\n{content}" if prior else content
    return out

def _findings_from_results(results: Sequence[SearchResult]) -> list[str]:
    findings: list[str] = []
    for result in results:
        title = result.title or result.url or "Untitled source"
        snippet = (result.content or "").strip().replace("\n", " ")[:240]
        findings.append(f"{title}: {snippet}" if snippet else title)
    return findings


def _nested_get(mapping: dict[str, Any], path: Sequence[str], default: Any) -> Any:
    cur: Any = mapping
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _safe_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
