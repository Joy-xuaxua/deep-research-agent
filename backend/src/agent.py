"""Orchestrator coordinating the deep research workflow."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread
from typing import Any, Callable, Iterator

from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent
from hello_agents.tools import ToolRegistry
from hello_agents.tools.builtin.note_tool import NoteTool

from config import Configuration
from prompts import (
    report_writer_instructions,
    task_summarizer_instructions,
    todo_planner_system_prompt,
)
from models import SummaryState, SummaryStateOutput, TodoItem
from services.archiver import NoteArchiver
from services.planner import PlanningService
from services.reporter import ReportingService
from services.search import dispatch_search, prepare_research_context
from services.summarizer import SummarizationService
from services.tool_events import ToolCallTracker

logger = logging.getLogger(__name__)


class DeepResearchAgent:
    """Coordinator orchestrating TODO-based research workflow using HelloAgents."""

    def __init__(self, config: Configuration | None = None) -> None:
        """Initialise the coordinator with configuration and shared tools."""
        self.config = config or Configuration.from_env()
        self.llm = self._init_llm()

        self.note_tool = (
            NoteTool(workspace=self.config.notes_workspace)
            if self.config.enable_notes
            else None
        )
        self.tools_registry: ToolRegistry | None = None
        if self.note_tool:
            registry = ToolRegistry()
            registry.register_tool(self.note_tool)
            self.tools_registry = registry

        self._tool_tracker = ToolCallTracker(
            self.config.notes_workspace if self.config.enable_notes else None
        )
        self._tool_event_sink_enabled = False
        self._state_lock = Lock()

        self.todo_agent = self._create_tool_aware_agent(
            name="研究规划专家",
            system_prompt=todo_planner_system_prompt.strip(),
        )
        self.report_agent = self._create_tool_aware_agent(
            name="报告撰写专家",
            system_prompt=report_writer_instructions.strip(),
        )

        self._summarizer_factory: Callable[[], ToolAwareSimpleAgent] = lambda: self._create_tool_aware_agent(  # noqa: E501
            name="任务总结专家",
            system_prompt=task_summarizer_instructions.strip(),
        )

        self.planner = PlanningService(self.todo_agent, self.config)
        self.summarizer = SummarizationService(self._summarizer_factory, self.config)
        self.reporting = ReportingService(self.report_agent, self.config)
        self._last_search_notices: list[str] = []

        # Initialize archiver if enabled
        self.archiver: NoteArchiver | None = None
        if self.config.enable_archiving and self.config.enable_notes:
            self.archiver = NoteArchiver(
                workspace=self.config.notes_workspace,
                archives_dir=self.config.archives_dir
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def _init_llm(self) -> HelloAgentsLLM:
        """Instantiate HelloAgentsLLM following configuration preferences.

        Supports multiple providers (ollama, lmstudio, custom) with provider-specific
        base URL and API key handling.

        Returns:
            HelloAgentsLLM: Configured LLM instance for agent operations
        """
        # step 1: build base LLM configuration with model and provider
        llm_kwargs: dict[str, Any] = {"temperature": 0.0}
        model_id = self.config.llm_model_id or self.config.local_llm
        if model_id:
            llm_kwargs["model"] = model_id

        provider = (self.config.llm_provider or "").strip()
        if provider:
            llm_kwargs["provider"] = provider

        # step 2: configure provider-specific settings (base URL and API key)
        if provider == "ollama":
            llm_kwargs["base_url"] = self.config.sanitized_ollama_url()
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key
            else:
                llm_kwargs["api_key"] = "ollama"
        elif provider == "lmstudio":
            llm_kwargs["base_url"] = self.config.lmstudio_base_url
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key
        else:
            if self.config.llm_base_url:
                llm_kwargs["base_url"] = self.config.llm_base_url
            if self.config.llm_api_key:
                llm_kwargs["api_key"] = self.config.llm_api_key

        return HelloAgentsLLM(**llm_kwargs)

    def _create_tool_aware_agent(self, *, name: str, system_prompt: str) -> ToolAwareSimpleAgent:
        """Instantiate a ToolAwareSimpleAgent sharing tool registry and tracker.

        Creates specialized agents (planner, summarizer, reporter) that all share
        the same tool registry (for NoteTool access) and tool call tracker (for
        event recording).

        Args:
            name: Human-readable agent name (e.g., "研究规划专家", "报告撰写专家")
            system_prompt: The agent's system prompt defining its role and behavior

        Returns:
            ToolAwareSimpleAgent: Configured agent with shared tool infrastructure
        """
        return ToolAwareSimpleAgent(
            name=name,
            llm=self.llm,
            system_prompt=system_prompt,
            enable_tool_calling=self.tools_registry is not None,
            tool_registry=self.tools_registry,
            tool_call_listener=self._tool_tracker.record,
        )

    def _set_tool_event_sink(self, sink: Callable[[dict[str, Any]], None] | None) -> None:
        """Enable or disable immediate tool event callbacks.

        Configures a callback that receives tool events immediately, rather than
        buffering them. Used during streaming to forward NoteTool events to the SSE queue.

        Args:
            sink: Callback function(dict) to receive tool events, or None to disable
        """
        self._tool_event_sink_enabled = sink is not None
        self._tool_tracker.set_event_sink(sink)
        """Execute the research workflow and return the final report."""
        state = SummaryState(research_topic=topic)
        state.todo_items = self.planner.plan_todo_list(state)
        self._drain_tool_events(state)

        if not state.todo_items:
            logger.info("No TODO items generated; falling back to single task")
            state.todo_items = [self.planner.create_fallback_task(state)]

        for task in state.todo_items:
            self._execute_task(state, task, emit_stream=False)

        report = self.reporting.generate_report(state)
        self._drain_tool_events(state)
        state.structured_report = report
        state.running_summary = report
        self._persist_final_report(state, report)

        # Archive notes after completion
        self._archive_research_notes(state, status="completed")

        return SummaryStateOutput(
            running_summary=report,
            report_markdown=report,
            todo_items=state.todo_items,
        )

    def run_stream(self, topic: str) -> Iterator[dict[str, Any]]:
        """Execute the workflow yielding incremental progress events.

        Main streaming entry point orchestrating the research workflow with
        parallel task execution using worker threads and thread-safe event queue.

        Workflow: Planning -> Execution (parallel) -> Reporting -> Persistence -> Archiving

        Args:
            topic: The research topic/query to investigate

        Yields:
            dict[str, Any]: Progress events including status, todo_list, task_status,
                sources, task_summary_chunk, tool_call, final_report, archived, done
        """
        # step 1: initialize state and generate TODO list
        state = SummaryState(research_topic=topic)
        logger.debug("Starting streaming research: topic=%s", topic)
        yield {"type": "status", "message": "初始化研究流程"}

        state.todo_items = self.planner.plan_todo_list(state)
        for event in self._drain_tool_events(state, step=0):
            yield event

        if not state.todo_items:
            state.todo_items = [self.planner.create_fallback_task(state)]

        # step 2: build channel map for task-to-step/token routing (frontend correlation)
        channel_map: dict[int, dict[str, Any]] = {}
        for index, task in enumerate(state.todo_items, start=1):
            token = f"task_{task.id}"
            task.stream_token = token
            channel_map[task.id] = {"step": index, "token": token}

        yield {
            "type": "todo_list",
            "tasks": [self._serialize_task(t) for t in state.todo_items],
            "step": 0,
        }

        # step 3: setup event queue and enqueue function with task metadata decoration
        event_queue: Queue[dict[str, Any]] = Queue()

        def enqueue(
            event: dict[str, Any],
            *,
            task: TodoItem | None = None,
            step_override: int | None = None,
        ) -> None:
            payload = dict(event)
            target_task_id = payload.get("task_id")
            if task is not None:
                target_task_id = task.id
                payload["task_id"] = task.id

            channel = channel_map.get(target_task_id) if target_task_id is not None else None
            if channel:
                payload.setdefault("step", channel["step"])
                payload["stream_token"] = channel["token"]
            if step_override is not None:
                payload["step"] = step_override
            event_queue.put(payload)

        def tool_event_sink(event: dict[str, Any]) -> None:
            enqueue(event)

        self._set_tool_event_sink(tool_event_sink)

        # step 4: launch worker threads for parallel task execution
        threads: list[Thread] = []

        def worker(task: TodoItem, step: int) -> None:
            try:
                enqueue(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "in_progress",
                        "title": task.title,
                        "intent": task.intent,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                    },
                    task=task,
                )

                for event in self._execute_task(state, task, emit_stream=True, step=step):
                    enqueue(event, task=task)
            except Exception as exc:
                logger.exception("Task execution failed", exc_info=exc)
                enqueue(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "failed",
                        "detail": str(exc),
                        "title": task.title,
                        "intent": task.intent,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                    },
                    task=task,
                )
            finally:
                enqueue({"type": "__task_done__", "task_id": task.id})

        for task in state.todo_items:
            step = channel_map.get(task.id, {}).get("step", 0)
            thread = Thread(target=worker, args=(task, step), daemon=True)
            threads.append(thread)
            thread.start()

        # step 5: main event loop - yield events from queue until all workers complete
        active_workers = len(state.todo_items)
        finished_workers = 0

        try:
            while finished_workers < active_workers:
                event = event_queue.get()
                if event.get("type") == "__task_done__":
                    finished_workers += 1
                    continue
                yield event

            while True:
                try:
                    event = event_queue.get_nowait()
                except Empty:
                    break
                if event.get("type") != "__task_done__":
                    yield event
        finally:
            self._set_tool_event_sink(None)
            for thread in threads:
                thread.join()

        # step 6: generate final report and update state
        report = self.reporting.generate_report(state)
        final_step = len(state.todo_items) + 1
        for event in self._drain_tool_events(state, step=final_step):
            yield event
        state.structured_report = report
        state.running_summary = report

        # step 7: persist report to note workspace
        note_event = self._persist_final_report(state, report)
        if note_event:
            yield note_event

        yield {
            "type": "final_report",
            "report": report,
            "note_id": state.report_note_id,
            "note_path": state.report_note_path,
        }

        # step 8: archive research notes
        archive_event = self._archive_research_notes(state, status="completed")
        if archive_event:
            yield archive_event

        yield {"type": "done"}

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def _execute_task(
        self,
        state: SummaryState,
        task: TodoItem,
        *,
        emit_stream: bool,
        step: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Run search + summarization for a single task.

        Core research workflow: Dispatch search -> Validate results -> Prepare context
        -> Summarize -> Update task state.

        Args:
            state: The shared research state object
            task: The TODO task to execute
            emit_stream: If True, yield progress events; if False, run silently
            step: Optional step number for event correlation in streaming mode

        Yields:
            dict[str, Any]: Progress events when emit_stream=True
        """
        task.status = "in_progress"

        # step 1: dispatch search to configured backend (duckduckgo, tavily, etc.)
        search_result, notices, answer_text, backend = dispatch_search(
            task.query,
            self.config,
            state.research_loop_count,
        )
        self._last_search_notices = notices
        task.notices = notices

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
        else:
            self._drain_tool_events(state)

        if notices and emit_stream:
            for notice in notices:
                if notice:
                    yield {
                        "type": "status",
                        "message": notice,
                        "task_id": task.id,
                        "step": step,
                    }

        # step 2: handle empty search results - mark task as skipped
        if not search_result or not search_result.get("results"):
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
        else:
            if not emit_stream:
                self._drain_tool_events(state)

        # step 3: prepare research context and update shared state
        sources_summary, context = prepare_research_context(
            search_result,
            answer_text,
            self.config,
        )

        task.sources_summary = sources_summary

        with self._state_lock:
            state.web_research_results.append(context)
            state.sources_gathered.append(sources_summary)
            state.research_loop_count += 1

        summary_text: str | None = None

        # step 4: execute summarization (streaming or blocking)
        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event

            yield {
                "type": "sources",
                "task_id": task.id,
                "latest_sources": sources_summary,
                "raw_context": context,
                "step": step,
                "backend": backend,
                "note_id": task.note_id,
                "note_path": task.note_path,
            }

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
                summary_text = summary_getter()
        else:
            summary_text = self.summarizer.summarize_task(state, task, context)
            self._drain_tool_events(state)

        # step 5: update task with summary and mark completed
        task.summary = summary_text.strip() if summary_text else "暂无可用信息"
        task.status = "completed"

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "task_status",
                "task_id": task.id,
                "status": "completed",
                "summary": task.summary,
                "sources_summary": task.sources_summary,
                "note_id": task.note_id,
                "note_path": task.note_path,
                "step": step,
            }
        else:
            self._drain_tool_events(state)

    def _drain_tool_events(
        self,
        state: SummaryState,
        *,
        step: int | None = None,
    ) -> list[dict[str, Any]]:
        """Proxy to the shared tool call tracker.

        Retrieves and clears buffered tool events from the tracker. When an event
        sink is active (streaming mode), events are immediately forwarded and this
        returns an empty list.

        Args:
            state: The research state to associate with drained events
            step: Optional step number to attach to events for frontend correlation

        Returns:
            list[dict[str, Any]]: Drained tool events, or empty list if sink enabled
        """
        events = self._tool_tracker.drain(state, step=step)
        if self._tool_event_sink_enabled:
            return []
        return events

    @property
    def _tool_call_events(self) -> list[dict[str, Any]]:
        """Expose recorded tool events for legacy integrations."""
        return self._tool_tracker.as_dicts()

    def _serialize_task(self, task: TodoItem) -> dict[str, Any]:
        """Convert task dataclass to serializable dict for frontend."""
        return {
            "id": task.id,
            "title": task.title,
            "intent": task.intent,
            "query": task.query,
            "status": task.status,
            "summary": task.summary,
            "sources_summary": task.sources_summary,
            "note_id": task.note_id,
            "note_path": task.note_path,
            "stream_token": task.stream_token,
        }

    def _persist_final_report(self, state: SummaryState, report: str) -> dict[str, Any] | None:
        """Persist the final research report to the note workspace.

        Checks if a report note already exists and updates it, otherwise creates
        a new note. The report is tagged as "conclusion" type for archival.

        Args:
            state: The research state containing the topic and existing note IDs
            report: The final markdown report content to persist

        Returns:
            dict[str, Any] | None: Event payload with note metadata if successful,
                None if note_tool disabled or persistence fails
        """
        if not self.note_tool or not report or not report.strip():
            return None

        note_title = f"研究报告：{state.research_topic}".strip() or "研究报告"
        tags = ["deep_research", "report"]
        content = report.strip()

        # step 1: try to update existing report note, or create new one
        note_id = self._find_existing_report_note_id(state)
        response = ""

        if note_id:
            response = self.note_tool.run(
                {
                    "action": "update",
                    "note_id": note_id,
                    "title": note_title,
                    "note_type": "conclusion",
                    "tags": tags,
                    "content": content,
                }
            )
            if response.startswith("❌"):
                note_id = None

        if not note_id:
            response = self.note_tool.run(
                {
                    "action": "create",
                    "title": note_title,
                    "note_type": "conclusion",
                    "tags": tags,
                    "content": content,
                }
            )
            note_id = self._extract_note_id_from_text(response)

        if not note_id:
            return None

        # step 2: update state and build event payload
        state.report_note_id = note_id

        if self.config.notes_workspace:
            note_path = Path(self.config.notes_workspace) / f"{note_id}.md"
            state.report_note_path = str(note_path)
        else:
            note_path = None

        # Step 3: Build and return event payload for frontend
        payload = {
            "type": "report_note",
            "note_id": note_id,
            "title": note_title,
            "content": content,
        }
        if note_path:
            payload["note_path"] = str(note_path)

        return payload

    def _find_existing_report_note_id(self, state: SummaryState) -> str | None:
        """Search for an existing report note ID to avoid duplication.

        Searches through recorded tool events to find if a report note has already
        been created. Looks for note tool calls with "conclusion" type or titles
        starting with "研究报告" (Research Report).

        Args:
            state: The research state which may already have a report_note_id

        Returns:
            str | None: The existing note ID if found, None otherwise
        """
        if state.report_note_id:
            return state.report_note_id

        # step 1: search tool events for matching report note
        for event in reversed(self._tool_tracker.as_dicts()):
            if event.get("tool") != "note":
                continue

            parameters = event.get("parsed_parameters") or {}
            if not isinstance(parameters, dict):
                continue

            action = parameters.get("action")
            if action not in {"create", "update"}:
                continue

            # step 2: check note type or title pattern match
            note_type = parameters.get("note_type")
            if note_type != "conclusion":
                title = parameters.get("title")
                if not (isinstance(title, str) and title.startswith("研究报告")):
                    continue

            # step 3: extract and return note_id if found
            note_id = parameters.get("note_id")
            if not note_id:
                note_id = self._tool_tracker._extract_note_id(event.get("result", ""))  # type: ignore[attr-defined]

            if note_id:
                return note_id

        return None

    @staticmethod
    def _extract_note_id_from_text(response: str) -> str | None:
        if not response:
            return None

        match = re.search(r"ID:\s*([^\n]+)", response)
        if not match:
            return None

        return match.group(1).strip()

    def _archive_research_notes(
        self,
        state: SummaryState,
        status: str = "completed"
    ) -> dict[str, Any] | None:
        """Archive research notes after completion.

        Moves all research-related notes from the active workspace to the archive
        directory, organized by topic with meaningful filenames.

        Args:
            state: The research state containing all task and report info
            status: Research status (completed/failed) for archive metadata

        Returns:
            dict[str, Any] | None: Archive event payload if enabled, None otherwise
        """
        if not self.archiver:
            return None

        try:
            # step 1: collect task note IDs and titles
            task_note_ids: dict[int, str] = {}
            task_titles: dict[int, str] = {}
            for task in state.todo_items:
                if task.note_id:
                    task_note_ids[task.id] = task.note_id
                    task_titles[task.id] = task.title

            if not task_note_ids and not state.report_note_id:
                logger.info("No notes to archive")
                return None

            # step 2: perform archival through NoteArchiver service
            archive_result = self.archiver.archive_research(
                research_topic=state.research_topic,
                report_note_id=state.report_note_id,
                task_note_ids=task_note_ids,
                task_titles=task_titles,
                status=status
            )

            logger.info(
                f"Archived research '{state.research_topic}' to {archive_result['archive_dir']}"
            )

            # step 3: update state with archive paths and return event
            state.archive_dir = archive_result["archive_dir"]
            state.archive_report_path = archive_result.get("report_path")
            state.archive_task_paths = archive_result.get("task_paths", {})

            orphaned = archive_result.get("orphaned_note_paths", [])
            if orphaned:
                logger.warning(f"Found {len(orphaned)} orphaned notes during archival: {orphaned}")

            return {
                "type": "archived",
                "archive_dir": archive_result["archive_dir"],
                "report_path": archive_result.get("report_path"),
                "task_count": len(task_note_ids)
            }
        except Exception as exc:
            logger.exception("Failed to archive research notes")
            return {
                "type": "archive_failed",
                "error": str(exc)
            }


def run_deep_research(topic: str, config: Configuration | None = None) -> SummaryStateOutput:
    """Convenience function mirroring the class-based API."""
    agent = DeepResearchAgent(config=config)
    return agent.run(topic)
