"""Utility for collecting and exposing tool call events."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional

from models import SummaryState, TodoItem

logger = logging.getLogger(__name__)


@dataclass
class ToolCallEvent:
    """Internal representation of a tool call event."""

    id: int
    agent: str
    tool: str
    raw_parameters: str
    parsed_parameters: dict[str, Any]
    result: str
    task_id: Optional[int]
    note_id: Optional[str]


class ToolCallTracker:
    """Collects tool call events and converts them to SSE payloads."""

    def __init__(self, notes_workspace: Optional[str]) -> None:
        self._notes_workspace = notes_workspace
        self._events: list[ToolCallEvent] = []
        self._cursor = 0
        self._lock = Lock()
        self._event_sink: Optional[Callable[[dict[str, Any]], None]] = None

    def record(self, payload: dict[str, Any]) -> None:
        """记录模型工具调用情况，便于日志与前端展示。"""

        agent_name = str(payload.get("agent_name") or "unknown")
        tool_name = str(payload.get("tool_name") or "unknown")
        raw_parameters = str(payload.get("raw_parameters") or "")
        parsed_parameters = payload.get("parsed_parameters") or {}
        result_text = str(payload.get("result") or "")

        if not isinstance(parsed_parameters, dict):
            parsed_parameters = {}

        task_id = self._infer_task_id(parsed_parameters)
        note_id: Optional[str] = None

        if tool_name == "note":
            note_id = parsed_parameters.get("note_id")
            if note_id is None:
                note_id = self._extract_note_id(result_text)

        event = ToolCallEvent(
            id=len(self._events) + 1,
            agent=agent_name,
            tool=tool_name,
            raw_parameters=raw_parameters,
            parsed_parameters=parsed_parameters,
            result=result_text,
            task_id=task_id,
            note_id=note_id,
        )

        with self._lock:
            self._events.append(event)

        logger.info(
            "Tool call recorded: agent=%s tool=%s task_id=%s note_id=%s parsed_parameters=%s",
            agent_name,
            tool_name,
            task_id,
            note_id,
            parsed_parameters,
        )

        sink = self._event_sink
        if sink:
            sink(self._build_payload(event, step=None))

    # ------------------------------------------------------------------
    # Draining helpers
    # ------------------------------------------------------------------
    def drain(self, state: SummaryState, *, step: Optional[int] = None) -> list[dict[str, Any]]:
        """提取尚未消费的工具调用事件，并同步任务的 note_id。

        这是一个消费者模式的生产者-消费者实现：
        - record() 是生产者，不断向 _events 添加事件
        - drain() 是消费者，提取并清空已消费的事件

        Args:
            state: 研究状态对象，包含 todo_items 用于关联 note_id
            step: 可选的步骤号，用于前端事件关联

        Returns:
            SSE payload 列表，每个 payload 是一个可序列化的 dict
        """

        # ====================================================================
        # Step 1: 获取线程锁，保证原子性操作
        # 目的: 防止在读取 _events 时，其他线程通过 record() 添加新事件
        # ====================================================================
        with self._lock:

            # ====================================================================
            # Step 2: 检查是否有新事件需要消费
            # 目的: 避免不必要的处理，如果 cursor 已经到达末尾，直接返回空列表
            #
            # _cursor 的语义: "已消费到哪个位置"
            # - 初始值: 0
            # - 每次 drain: 更新到 len(_events)
            # - 如果 cursor >= len: 说明所有事件都已消费
            # ====================================================================
            if self._cursor >= len(self._events):
                return []  # 无新事件，提前返回

            # ====================================================================
            # Step 3: 提取新事件切片（cursor 到末尾）
            # 目的: 只获取上次 drain 之后新增的事件
            #
            # 例如:
            # _events = [event1, event2, event3, event4, event5]
            # _cursor = 2
            # new_events = [event3, event4, event5]  # 只取未消费的
            # _cursor = 5  # 更新游标，标记这些事件已消费
            # ====================================================================
            new_events = self._events[self._cursor :]
            self._cursor = len(self._events)

        # ====================================================================
        # Step 4: 释放锁，继续处理（此时其他线程可以 record 新事件）
        # ====================================================================

        # ====================================================================
        # Step 5: 同步 note_id 到对应的 TodoItem
        # 目的: 当 agent 创建笔记时，将 note_id 关联到对应的 task
        #
        # 这个关联很重要，因为:
        # - TodoItem 创建时没有 note_id
        # - NoteTool 被调用时会创建笔记并返回 note_id
        # - 需要将这个 note_id 写回到 TodoItem，供后续使用（如归档）
        # ====================================================================
        if state.todo_items:
            for event in new_events:
                task_id = event.task_id
                note_id = event.note_id

                # 跳过没有 task_id 或 note_id 的事件
                if task_id is None or not note_id:
                    continue

                # 将 note_id 附加到对应的 TodoItem
                self._attach_note_to_task(state.todo_items, task_id, note_id)

        # ====================================================================
        # Step 6: 构建 SSE payload 列表
        # 目的: 将内部 ToolCallEvent 对象转换为前端可用的字典格式
        #
        # 转换内容:
        # - 添加 "type": "tool_call" 用于前端事件路由
        # - 添加 step 用于前端显示进度
        # - 添加 note_path 如果有 workspace 路径
        # ====================================================================
        payloads: list[dict[str, Any]] = []
        for event in new_events:
            payload = self._build_payload(event, step=step)
            payloads.append(payload)

        return payloads

    def reset(self) -> None:
        """Clear recorded events."""

        with self._lock:
            self._events.clear()
            self._cursor = 0

    def as_dicts(self) -> list[dict[str, Any]]:
        """Expose a snapshot of raw events for backwards compatibility."""

        with self._lock:
            return [
                {
                    "id": event.id,
                    "agent": event.agent,
                    "tool": event.tool,
                    "raw_parameters": event.raw_parameters,
                    "parsed_parameters": event.parsed_parameters,
                    "result": event.result,
                    "task_id": event.task_id,
                    "note_id": event.note_id,
                }
                for event in self._events
            ]

    def set_event_sink(self, sink: Optional[Callable[[dict[str, Any]], None]]) -> None:
        """Register a callback for immediate tool event notifications."""

        self._event_sink = sink

    def _build_payload(self, event: ToolCallEvent, step: Optional[int]) -> dict[str, Any]:
        payload = {
            "type": "tool_call",
            "event_id": event.id,
            "agent": event.agent,
            "tool": event.tool,
            "parameters": event.parsed_parameters,
            "result": event.result,
            "task_id": event.task_id,
            "note_id": event.note_id,
        }
        if event.note_id and self._notes_workspace:
            note_path = Path(self._notes_workspace) / f"{event.note_id}.md"
            payload["note_path"] = str(note_path)
        if step is not None:
            payload["step"] = step
        return payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _attach_note_to_task(self, tasks: list[TodoItem], task_id: int, note_id: str) -> None:
        """Update matching TODO item with note metadata."""

        for task in tasks:
            if task.id != task_id:
                continue

            if task.note_id != note_id:
                task.note_id = note_id
                if self._notes_workspace:
                    task.note_path = str(Path(self._notes_workspace) / f"{note_id}.md")
            elif task.note_path is None and self._notes_workspace:
                task.note_path = str(Path(self._notes_workspace) / f"{note_id}.md")
            break

    def _infer_task_id(self, parameters: dict[str, Any]) -> Optional[int]:
        """尝试从工具参数推断 task_id。"""

        if not parameters:
            return None

        if "task_id" in parameters:
            try:
                return int(parameters["task_id"])
            except (TypeError, ValueError):
                pass

        tags = parameters.get("tags")
        if isinstance(tags, list):
            for tag in tags:
                match = re.search(r"task_(\d+)", str(tag))
                if match:
                    return int(match.group(1))

        title = parameters.get("title")
        if isinstance(title, str):
            match = re.search(r"任务\s*(\d+)", title)
            if match:
                return int(match.group(1))

        return None

    def _extract_note_id(self, response: str) -> Optional[str]:
        if not response:
            return None

        match = re.search(r"ID:\s*([^\n]+)", response)
        if match:
            return match.group(1).strip()
        return None
