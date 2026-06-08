"""Tests for data models."""

import pytest

from models import ResearchResult, ResearchState, ResearchTask


class TestResearchTask:
    """Tests for ResearchTask dataclass."""

    def test_create_task_with_defaults(self):
        """Test creating a ResearchTask with default values."""
        item = ResearchTask(
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

    def test_create_task_with_all_fields(self):
        """Test creating a ResearchTask with all fields specified."""
        item = ResearchTask(
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

    def test_create_task_for_talking_face_research(self):
        """Test creating a ResearchTask for talking face generation research."""
        item = ResearchTask(
            id=1,
            title="技术背景梳理",
            intent="了解talking face generation的核心技术原理",
            query="2025年talking face generation 技术原理"
        )
        assert item.id == 1
        assert "talking face" in item.query
        assert item.status == "pending"


class TestResearchState:
    """Tests for ResearchState dataclass."""

    def test_create_state_with_defaults(self):
        """Test creating a ResearchState with default values."""
        state = ResearchState()
        assert state.research_topic is None
        assert state.research_loop_count == 0
        assert state.todo_items == []
        assert state.report is None
        assert state.report_note_id is None
        assert state.report_note_path is None
        assert state.archive_dir is None

    def test_create_state_with_topic(self):
        """Test creating a ResearchState with a research topic."""
        topic = "2025年talking face generation在商业中的最新应用和效果"
        state = ResearchState(research_topic=topic)
        assert state.research_topic == topic
        assert state.research_loop_count == 0

    def test_state_with_tasks(self):
        """Test adding tasks to state."""
        state = ResearchState(
            todo_items=[ResearchTask(id=1, title="Task 1", intent="Intent", query="Query")]
        )
        assert len(state.todo_items) == 1
        assert state.todo_items[0].title == "Task 1"

    def test_state_archive_fields(self):
        """Test archive-related fields."""
        state = ResearchState(
            archive_dir="./archives/test_topic",
        )
        assert state.archive_dir == "./archives/test_topic"


class TestResearchResult:
    """Tests for ResearchResult dataclass."""

    def test_create_result_with_defaults(self):
        """Test creating a ResearchResult with default values."""
        output = ResearchResult()
        assert output.report_markdown is None
        assert output.todo_items == []

    def test_create_result_with_data(self):
        """Test creating a ResearchResult with data."""
        topic = "2025年talking face generation在商业中的最新应用和效果"
        output = ResearchResult(
            report_markdown="# Test Report\n\nContent here",
            todo_items=[
                ResearchTask(
                    id=1,
                    title="商业应用分析",
                    intent="分析talking face generation的商业应用场景",
                    query="talking face generation business applications 2025"
                )
            ]
        )
        assert output.report_markdown == "# Test Report\n\nContent here"
        assert len(output.todo_items) == 1
        assert output.todo_items[0].title == "商业应用分析"

    def test_result_with_talking_face_research(self):
        """Test ResearchResult for talking face generation research."""
        topic = "2025年talking face generation在商业中的最新应用和效果"
        output = ResearchResult(
            report_markdown=f"# {topic}\n\n## 研究内容\n\n详细分析...",
            todo_items=[
                ResearchTask(
                    id=1,
                    title="技术背景",
                    intent="了解技术原理",
                    query="talking face generation technology"
                ),
                ResearchTask(
                    id=2,
                    title="商业应用",
                    intent="分析商业场景",
                    query="talking face generation business"
                ),
                ResearchTask(
                    id=3,
                    title="效果评估",
                    intent="评估应用效果",
                    query="talking face generation evaluation"
                )
            ]
        )
        assert len(output.todo_items) == 3
        assert output.todo_items[0].id == 1
        assert output.todo_items[1].id == 2
        assert output.todo_items[2].id == 3
