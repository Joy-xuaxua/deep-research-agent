"""Task execution logic extracted from DeepResearchAgent.

Handles the multi-stage research workflow for a single task:
  Stage 1 – Lightweight search (title + snippet only)
  Stage 2 – Validate source quality via LLM
  Stage 3 – Fetch full content for valid sources only
  Stage 4 – Summarize and update task state
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

from hello_agents.tools.builtin.note_tool import NoteTool

from config import Configuration
from models import SummaryState, TodoItem
from services.search import (
    dispatch_search,
    fetch_full_content_for_sources,
    prepare_research_context,
)
from services.summarizer import SummarizationService
from services.tool_events import ToolCallTracker

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Execute a single research task (search → validate → fetch → summarize)."""

    def __init__(
        self,
        config: Configuration,
        summarizer: SummarizationService,
        tool_tracker: ToolCallTracker,
        note_tool: NoteTool | None,
        validator: Any | None,
        state_lock: Lock,
        *,
        tool_event_sink_enabled: bool = False,
    ) -> None:
        self.config = config
        self.summarizer = summarizer
        self.tool_tracker = tool_tracker
        self.note_tool = note_tool
        self.validator = validator
        self.state_lock = state_lock
        self._tool_event_sink_enabled = tool_event_sink_enabled
        # Mutable ref shared with the agent so both sides stay in sync
        self.last_search_notices: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def execute_task(
        self,
        state: SummaryState,
        task: TodoItem,
        *,
        emit_stream: bool,
        step: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Run search + summarization for a single task with two-stage search.

        Core research workflow with source validation:
        Stage 1: Lightweight search (title + snippet only)
        Stage 2: Validate source quality using LLM
        Stage 3: Fetch full content only for valid sources
        Stage 4: Summarize and update task state

        Args:
            state: The shared research state object
            task: The TODO task to execute
            emit_stream: If True, yield progress events; if False, run silently
            step: Optional step number for event correlation in streaming mode

        Yields:
            dict[str, Any]: Progress events when emit_stream=True
        """
        task.status = "in_progress"

        # Configure search retry parameters
        max_search_rounds = self.config.max_search_retries
        min_valid_sources = self.config.min_valid_sources_threshold
        valid_sources: list[dict] = []
        search_round = 0
        search_result: dict[str, Any] | None = None
        answer_text: str | None = None
        backend = ""

        # === Two-stage search with retry loop ===
        while search_round < max_search_rounds:
            search_round += 1

            # === Stage 1: Lightweight search (fetch_full_page=False) ===
            search_result, notices, answer_text, backend = dispatch_search(
                task.query,
                self.config,
                state.research_loop_count,
                fetch_full_page=False,
                max_tokens_per_source=self.config.max_tokens_per_source,
            )
            self.last_search_notices = notices
            task.notices = notices

            # Flush buffered NoteTool events — the drain also syncs note_id back
            # onto the TodoItem as a side-effect, so we must call it regardless
            # of streaming mode.
            if emit_stream:
                for event in self._drain_tool_events(state, step=step):
                    yield event
            else:
                self._drain_tool_events(state)

            # Forward search-engine notices (e.g. "truncated results") so the
            # frontend can display them in real time.
            if notices and emit_stream:
                for notice in notices:
                    if notice:
                        yield {
                            "type": "status",
                            "message": notice,
                            "task_id": task.id,
                            "step": step,
                        }

            if not search_result or not search_result.get("results"):
                logger.info("Search round %d: No results for task %d", search_round, task.id)
                continue

            lightweight_sources = search_result.get("results", [])

            # === Stage 2: Validate source quality (based on title + snippet) ===
            if self.validator:
                valid_sources, invalid_sources = self.validator.validate_sources(
                    lightweight_sources,
                    task.intent,
                    task.query,
                )

                # Notify the frontend how many sources passed/failed validation
                # so users understand why few results may remain.
                if emit_stream and invalid_sources:
                    yield {
                        "type": "sources_filtered",
                        "task_id": task.id,
                        "filtered_count": len(invalid_sources),
                        "valid_count": len(valid_sources),
                        "round": search_round,
                        "step": step,
                    }

                if len(valid_sources) >= min_valid_sources:
                    logger.info(
                        "Search round %d: Found %d valid sources (threshold: %d)",
                        search_round, len(valid_sources), min_valid_sources,
                    )
                    break
                else:
                    logger.info(
                        "Search round %d: Only %d valid sources (threshold: %d), continuing...",
                        search_round, len(valid_sources), min_valid_sources,
                    )
            else:
                valid_sources = lightweight_sources
                break

        # === Stage 3: Fetch full content only for valid sources ===
        if self.config.fetch_full_page and valid_sources:
            valid_sources = fetch_full_content_for_sources(
                valid_sources, self.config, research_topic=state.research_topic,
                max_tokens_per_source=self.config.max_tokens_per_source,
            )

        # No sources survived validation — mark skipped so the frontend can
        # update the UI instead of showing an infinite spinner.
        if not valid_sources:
            task.status = "skipped"
            if emit_stream:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                yield {
                    "type": "task_status",
                    "task_id": task.id,
                    "status": "skipped",
                    "title": task.title,
                    "intent": task.intent,
                    "note_id": task.note_id,
                    "note_path": task.note_path,
                    "step": step,
                }
            else:
                self._drain_tool_events(state)
            return

        # Prepare research context with valid sources (now with full content)
        search_result = {"results": valid_sources, "backend": backend}
        sources_url, context = prepare_research_context(
            search_result,
            answer_text,
            self.config,
            max_tokens_per_source=self.config.max_tokens_per_source,
        )

        tasks.sources_url_collection = sources_url

        with self.state_lock:
            state.web_research_results.append(context)
            state.sources_gathered.append(sources_url)
            state.research_loop_count += 1

        summary_text: str | None = None

        # === Stage 4: Execute summarization (streaming or blocking) ===
        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event

            # Expose the curated source list before summarization begins so the
            # frontend can render citations immediately.
            yield {
                "type": "sources",
                "task_id": task.id,
                "latest_sources": sources_url,
                "raw_context": context,
                "step": step,
                "backend": backend,
                "note_id": task.note_id,
                "note_path": task.note_path,
            }

            # Stream LLM output token-by-token for a typewriter effect.
            # Drain tool events between chunks to forward any NoteTool calls
            # the agent makes mid-generation.
            summary_stream, summary_getter = self.summarizer.stream_task_summary(state, task, context)
            try:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                for chunk in summary_stream:
                    if chunk:
                        yield {
                            "type": "task_summary_chunk",
                            "task_id": task.id,
                            "content": chunk,
                            "note_id": task.note_id,
                            "step": step,
                        }
                    for event in self._drain_tool_events(state, step=step):
                        yield event
            finally:
                # Collect whatever was generated even if the stream breaks.
                summary_text = summary_getter()
        else:
            summary_text = self.summarizer.summarize_task(state, task, context)
            self._drain_tool_events(state)

        # Update task with summary and mark completed
        task.summary = summary_text.strip() if summary_text else "暂无可用信息"
        task.status = "completed"

        # Save task note programmatically (not via LLM tool call)
        self._save_task_note(state, task)

        # Emit the definitive completion signal with the full summary so the
        # frontend can render the final result without reassembling chunks.
        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "task_status",
                "task_id": task.id,
                "status": "completed",
                "summary": task.summary,
                "sources_summary": tasks.sources_url_collection,
                "note_id": task.note_id,
                "note_path": task.note_path,
                "step": step,
            }
        else:
            self._drain_tool_events(state)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _drain_tool_events(
        self,
        state: SummaryState,
        *,
        step: int | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve and clear buffered tool events from the tracker."""
        events = self.tool_tracker.drain(state, step=step)
        if self._tool_event_sink_enabled:
            return []
        return events

    def _save_task_note(self, state: SummaryState, task: TodoItem) -> None:
        """Save task summary to a note programmatically after summarization."""
        if not self.note_tool or not task.summary:
            return

        note_title = f"任务 {task.id}: {task.title}"
        tags = ["deep_research", f"task_{task.id}"]

        parts = [f"检索查询：{task.query}"]
        if tasks.sources_url_collection:
            parts.append(f"\n## 来源概览\n{tasks.sources_url_collection}")
        parts.append(f"\n## 研究总结\n{task.summary}")
        content = "\n".join(parts)

        if task.note_id:
            self.note_tool.run(
                {
                    "action": "update",
                    "note_id": task.note_id,
                    "title": note_title,
                    "note_type": "task_state",
                    "tags": tags,
                    "content": content,
                }
            )
        else:
            response = self.note_tool.run(
                {
                    "action": "create",
                    "title": note_title,
                    "note_type": "task_state",
                    "tags": tags,
                    "content": content,
                }
            )
            note_id = self._extract_note_id_from_text(response)
            if note_id:
                task.note_id = note_id
                if self.config.notes_workspace:
                    task.note_path = str(Path(self.config.notes_workspace) / f"{note_id}.md")

    @staticmethod
    def _extract_note_id_from_text(response: str) -> str | None:
        if not response:
            return None
        match = re.search(r"ID:\s*([^\n]+)", response)
        if not match:
            return None
        return match.group(1).strip()
