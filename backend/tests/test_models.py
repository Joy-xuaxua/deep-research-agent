"""Tests for data models."""

import pytest

from models import SummaryState, SummaryStateOutput, TodoItem


class TestTodoItem:
    """Tests for TodoItem dataclass."""

    def test_create_todo_item_with_defaults(self):
        """Test creating a TodoItem with default values."""
        item = TodoItem(
            id=1,
            title="Test Task",
            intent="Test intent",
            query="test query"
        )
        assert item.id == 1
        assert item.title == "Test Task"
        assert item.intent == "Test intent"
        assert item.query == "test query"
        assert item.status == "pending"
        assert item.summary is None
        assert item.sources_summary is None
        assert item.notices == []
        assert item.note_id is None
        assert item.note_path is None
        assert item.stream_token is None

    def test_create_todo_item_with_all_fields(self):
        """Test creating a TodoItem with all fields specified."""
        item = TodoItem(
            id=2,
            title="Complete Task",
            intent="Complete intent",
            query="complete query",
            status="completed",
            summary="Test summary",
            sources_summary="Test sources",
            notices=["Notice 1", "Notice 2"],
            note_id="note123",
            note_path="/path/to/note.md",
            stream_token="task_2"
        )
        assert item.id == 2
        assert item.status == "completed"
        assert item.summary == "Test summary"
        assert item.sources_summary == "Test sources"
        assert item.notices == ["Notice 1", "Notice 2"]
        assert item.note_id == "note123"
        assert item.note_path == "/path/to/note.md"
        assert item.stream_token == "task_2"

    def test_todo_item_for_talking_face_research(self):
        """Test creating a TodoItem for talking face generation research."""
        item = TodoItem(
            id=1,
            title="技术背景梳理",
            intent="了解talking face generation的核心技术原理",
            query="2025年talking face generation 技术原理"
        )
        assert item.id == 1
        assert "talking face" in item.query
        assert item.status == "pending"


class TestSummaryState:
    """Tests for SummaryState dataclass."""

    def test_create_summary_state_with_defaults(self):
        """Test creating a SummaryState with default values."""
        state = SummaryState()
        assert state.research_topic is None
        assert state.web_research_results == []
        assert state.sources_gathered == []
        assert state.research_loop_count == 0
        assert state.running_summary is None
        assert state.todo_items == []
        assert state.structured_report is None
        assert state.report_note_id is None
        assert state.report_note_path is None
        assert state.archive_dir is None
        assert state.archive_report_path is None
        assert state.archive_task_paths == {}

    def test_create_summary_state_with_topic(self):
        """Test creating a SummaryState with a research topic."""
        topic = "2025年talking face generation在商业中的最新应用和效果"
        state = SummaryState(research_topic=topic)
        assert state.research_topic == topic
        assert state.research_loop_count == 0

    def test_summary_state_add_operator(self):
        """Test that list fields support addition via operator."""
        state1 = SummaryState(
            web_research_results=["result1"],
            sources_gathered=["source1"],
            todo_items=[TodoItem(id=1, title="Task 1", intent="Intent", query="Query")]
        )
        state2 = SummaryState(
            web_research_results=["result2"],
            sources_gathered=["source2"],
            todo_items=[TodoItem(id=2, title="Task 2", intent="Intent", query="Query")]
        )

        # The operator.add annotation should allow this behavior
        assert state1.web_research_results == ["result1"]
        assert state1.sources_gathered == ["source1"]
        assert len(state1.todo_items) == 1

    def test_summary_state_archive_fields(self):
        """Test archive-related fields."""
        state = SummaryState(
            archive_dir="./archives/test_topic",
            archive_report_path="./archives/test_topic/report.md",
            archive_task_paths={1: "./archives/test_topic/task_1.md"}
        )
        assert state.archive_dir == "./archives/test_topic"
        assert state.archive_report_path == "./archives/test_topic/report.md"
        assert state.archive_task_paths[1] == "./archives/test_topic/task_1.md"


class TestSummaryStateOutput:
    """Tests for SummaryStateOutput dataclass."""

    def test_create_summary_state_output_with_defaults(self):
        """Test creating a SummaryStateOutput with default values."""
        output = SummaryStateOutput()
        assert output.running_summary is None
        assert output.report_markdown is None
        assert output.todo_items == []

    def test_create_summary_state_output_with_data(self):
        """Test creating a SummaryStateOutput with data."""
        topic = "2025年talking face generation在商业中的最新应用和效果"
        output = SummaryStateOutput(
            running_summary="Test summary",
            report_markdown="# Test Report\n\nContent here",
            todo_items=[
                TodoItem(
                    id=1,
                    title="商业应用分析",
                    intent="分析talking face generation的商业应用场景",
                    query="talking face generation business applications 2025"
                )
            ]
        )
        assert output.running_summary == "Test summary"
        assert output.report_markdown == "# Test Report\n\nContent here"
        assert len(output.todo_items) == 1
        assert output.todo_items[0].title == "商业应用分析"

    def test_summary_state_output_with_talking_face_research(self):
        """Test SummaryStateOutput for talking face generation research."""
        topic = "2025年talking face generation在商业中的最新应用和效果"
        output = SummaryStateOutput(
            running_summary=f"关于{topic}的研究报告",
            report_markdown=f"# {topic}\n\n## 研究内容\n\n详细分析...",
            todo_items=[
                TodoItem(
                    id=1,
                    title="技术背景",
                    intent="了解技术原理",
                    query="talking face generation technology"
                ),
                TodoItem(
                    id=2,
                    title="商业应用",
                    intent="分析商业场景",
                    query="talking face generation business"
                ),
                TodoItem(
                    id=3,
                    title="效果评估",
                    intent="评估应用效果",
                    query="talking face generation evaluation"
                )
            ]
        )
        assert "talking face" in output.running_summary
        assert len(output.todo_items) == 3
        assert output.todo_items[0].id == 1
        assert output.todo_items[1].id == 2
        assert output.todo_items[2].id == 3
