"""Tests for DeepResearchAgent class."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import pytest

from agent import DeepResearchAgent
from config import Configuration, SearchAPI
from models import ResearchState, ResearchTask


@pytest.fixture
def test_config():
    """Create a test configuration."""
    return Configuration(
        max_web_research_loops=2,
        search_api=SearchAPI.DUCKDUCKGO,
        enable_notes=False,
        enable_archiving=False
    )


@pytest.fixture
def mock_llm():
    """Create a mock HelloAgentsLLM."""
    llm = MagicMock()
    return llm


@pytest.fixture
def talking_face_topic():
    """The test topic for talking face generation research."""
    return "2025年talking face generation在商业中的最新应用和效果"


class TestDeepResearchAgent:
    """Tests for DeepResearchAgent."""

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_init_with_notes_disabled(self, mock_note_tool, mock_llm_class, test_config):
        """Test agent initialization with notes disabled."""
        test_config.enable_notes = False
        mock_llm_instance = MagicMock()
        mock_llm_class.return_value = mock_llm_instance

        agent = DeepResearchAgent(config=test_config)

        assert agent.config is test_config
        assert agent.llm is mock_llm_instance
        assert agent.note_tool is None
        assert agent.tools_registry is None

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_init_with_notes_enabled(self, mock_note_tool, mock_llm_class, test_config):
        """Test agent initialization with notes enabled."""
        test_config.enable_notes = True
        mock_llm_instance = MagicMock()
        mock_llm_class.return_value = mock_llm_instance
        mock_note_instance = MagicMock()
        mock_note_tool.return_value = mock_note_instance

        agent = DeepResearchAgent(config=test_config)

        assert agent.note_tool is mock_note_instance
        assert agent.tools_registry is not None

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_init_with_archiving_enabled(self, mock_note_tool, mock_llm_class, test_config):
        """Test agent initialization with archiving enabled."""
        test_config.enable_notes = True
        test_config.enable_archiving = True
        mock_llm_instance = MagicMock()
        mock_llm_class.return_value = mock_llm_instance
        mock_note_instance = MagicMock()
        mock_note_tool.return_value = mock_note_instance

        agent = DeepResearchAgent(config=test_config)

        assert agent.archiver is not None

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_init_with_archiving_disabled(self, mock_note_tool, mock_llm_class, test_config):
        """Test agent initialization with archiving disabled."""
        test_config.enable_archiving = False
        mock_llm_instance = MagicMock()
        mock_llm_class.return_value = mock_llm_instance

        agent = DeepResearchAgent(config=test_config)

        assert agent.archiver is None

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_init_creates_required_agents(self, mock_note_tool, mock_llm_class, test_config):
        """Test that initialization creates planner, reporter, and summarizer agents."""
        mock_llm_instance = MagicMock()
        mock_llm_class.return_value = mock_llm_instance

        agent = DeepResearchAgent(config=test_config)

        assert agent.todo_agent is not None
        assert agent.report_agent is not None
        assert agent.planner is not None
        assert agent.summarizer is not None
        assert agent.reporting is not None

    def test_init_llm_ollama_provider(self, test_config):
        """Test LLM initialization for Ollama provider."""
        test_config.llm_provider = "ollama"
        test_config.ollama_base_url = "http://localhost:11434"
        test_config.llm_api_key = "test-key"
        test_config.llm_model_id = "llama3.2"

        with patch('agent.HelloAgentsLLM') as mock_llm_class:
            agent = DeepResearchAgent(config=test_config)
            mock_llm_class.assert_called_once()
            call_kwargs = mock_llm_class.call_args[1]
            assert call_kwargs['provider'] == 'ollama'
            assert call_kwargs['base_url'] == 'http://localhost:11434/v1'
            assert call_kwargs['model'] == 'llama3.2'
            assert call_kwargs['api_key'] == 'test-key'

    def test_init_llm_custom_provider(self, test_config):
        """Test LLM initialization for custom provider."""
        test_config.llm_provider = "custom"
        test_config.llm_base_url = "https://api.custom.com/v1"
        test_config.llm_api_key = "custom-key"
        test_config.llm_model_id = "custom-model"

        with patch('agent.HelloAgentsLLM') as mock_llm_class:
            agent = DeepResearchAgent(config=test_config)
            call_kwargs = mock_llm_class.call_args[1]
            assert call_kwargs['provider'] == 'custom'
            assert call_kwargs['base_url'] == 'https://api.custom.com/v1'
            assert call_kwargs['model'] == 'custom-model'
            assert call_kwargs['api_key'] == 'custom-key'


class TestDeepResearchAgentRun:
    """Tests for DeepResearchAgent.run() method."""

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_run_with_empty_todo_list(self, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test run behavior when planner returns empty todo list."""
        config = Configuration(enable_notes=False, enable_archiving=False)
        mock_llm_class.return_value = MagicMock()

        agent = DeepResearchAgent(config=config)

        # Mock planner to return empty list
        agent.planner.plan_todo_list = MagicMock(return_value=[])
        agent.planner.create_fallback_task = MagicMock(
            return_value=ResearchTask(
                id=1,
                title="Fallback",
                intent="Fallback intent",
                query="fallback query"
            )
        )

        # Mock _execute_task to do nothing
        agent._execute_task = MagicMock()

        # Mock reporting
        agent.reporting.generate_report = MagicMock(return_value="# Test Report")

        result = agent.run(talking_face_topic)

        assert agent.planner.plan_todo_list.called
        assert agent.planner.create_fallback_task.called

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_run_generates_report(self, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test that run generates a final report."""
        config = Configuration(enable_notes=False, enable_archiving=False)
        mock_llm_class.return_value = MagicMock()

        agent = DeepResearchAgent(config=config)

        # Mock planner
        task = ResearchTask(
            id=1,
            title="技术分析",
            intent="分析技术",
            query="talking face tech"
        )
        agent.planner.plan_todo_list = MagicMock(return_value=[task])

        # Mock execution
        agent._execute_task = MagicMock()
        agent._drain_tool_events = MagicMock(return_value=[])

        # Mock reporting
        expected_report = f"# {talking_face_topic}\n\n研究报告内容"
        agent.reporting.generate_report = MagicMock(return_value=expected_report)

        result = agent.run(talking_face_topic)

        assert result.report_markdown == expected_report
        assert len(result.todo_items) == 1

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_run_persists_report_when_notes_enabled(self, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test that run persists report when notes are enabled."""
        config = Configuration(enable_notes=True, enable_archiving=False)
        mock_llm_class.return_value = MagicMock()
        mock_note_instance = MagicMock()
        mock_note_instance.run = MagicMock(return_value="✅ Note created with ID: test-note-123")
        mock_note_tool.return_value = mock_note_instance

        agent = DeepResearchAgent(config=config)

        task = ResearchTask(
            id=1,
            title="任务1",
            intent="意图1",
            query="query1",
            note_id="note-1"
        )
        agent.planner.plan_todo_list = MagicMock(return_value=[task])
        agent._execute_task = MagicMock()
        agent._drain_tool_events = MagicMock(return_value=[])
        agent.reporting.generate_report = MagicMock(return_value="# Report")

        result = agent.run(talking_face_topic)

        # Should have called note_tool.run
        assert mock_note_instance.run.called

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    @patch('agent.NoteArchiver')
    def test_run_archives_notes_when_enabled(self, mock_archiver_class, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test that run archives notes when archiving is enabled."""
        config = Configuration(enable_notes=True, enable_archiving=True)
        mock_llm_class.return_value = MagicMock()
        mock_note_instance = MagicMock()
        mock_note_tool.return_value = mock_note_instance
        mock_archiver_instance = MagicMock()
        mock_archiver_instance.archive_research = MagicMock(return_value={
            "archive_dir": "./archives/test_topic",
            "report_path": "./archives/test_topic/report.md",
            "task_paths": {1: "./archives/test_topic/task_1.md"}
        })
        mock_archiver_class.return_value = mock_archiver_instance

        agent = DeepResearchAgent(config=config)

        task = ResearchTask(
            id=1,
            title="任务1",
            intent="意图1",
            query="query1",
            note_id="note-1"
        )
        agent.planner.plan_todo_list = MagicMock(return_value=[task])
        agent._execute_task = MagicMock()
        agent._drain_tool_events = MagicMock(return_value=[])
        agent.reporting.generate_report = MagicMock(return_value="# Report")

        result = agent.run(talking_face_topic)

        # Should have called archive_research
        mock_archiver_instance.archive_research.assert_called_once()


class TestDeepResearchAgentRunStream:
    """Tests for DeepResearchAgent.run_stream() method."""

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_run_stream_yields_events(self, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test that run_stream yields research events."""
        config = Configuration(enable_notes=False, enable_archiving=False)
        mock_llm_class.return_value = MagicMock()

        agent = DeepResearchAgent(config=config)

        # Mock planner
        agent.planner.plan_todo_list = MagicMock(
            return_value=[
                ResearchTask(id=1, title="任务1", intent="意图1", query="query1"),
                ResearchTask(id=2, title="任务2", intent="意图2", query="query2")
            ]
        )
        agent._drain_tool_events = MagicMock(return_value=[])

        # Mock task execution to yield some events
        def mock_execute(state, task, *, emit_stream, step=None):
            yield {"type": "status", "message": f"Processing {task.title}"}
            yield {"type": "sources", "task_id": task.id, "latest_sources": "Sources"}
            yield {"type": "task_summary_chunk", "task_id": task.id, "content": "Summary"}

        agent._execute_task = mock_execute

        # Mock reporting
        agent.reporting.generate_report = MagicMock(
            return_value=f"# {talking_face_topic}\n\n完整报告"
        )

        # Collect all events
        events = list(agent.run_stream(talking_face_topic))

        # Should have initial status, todo_list, task events, final_report, and done
        event_types = [e.get("type") for e in events]
        assert "status" in event_types
        assert "todo_list" in event_types
        assert "final_report" in event_types
        assert "done" in event_types

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_run_stream_includes_todo_list(self, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test that run_stream includes todo_list event."""
        config = Configuration(enable_notes=False, enable_archiving=False)
        mock_llm_class.return_value = MagicMock()

        agent = DeepResearchAgent(config=config)

        tasks = [
            ResearchTask(id=1, title="技术背景", intent="技术分析", query="tech query"),
            ResearchTask(id=2, title="商业应用", intent="应用分析", query="business query")
        ]
        agent.planner.plan_todo_list = MagicMock(return_value=tasks)
        agent._drain_tool_events = MagicMock(return_value=[])
        agent._execute_task = MagicMock(return_value=iter([]))
        agent.reporting.generate_report = MagicMock(return_value="# Report")

        events = list(agent.run_stream(talking_face_topic))

        todo_list_events = [e for e in events if e.get("type") == "todo_list"]
        assert len(todo_list_events) == 1
        assert len(todo_list_events[0]["tasks"]) == 2
        assert todo_list_events[0]["tasks"][0]["title"] == "技术背景"
        assert todo_list_events[0]["tasks"][1]["title"] == "商业应用"


class TestDeepResearchAgentHelpers:
    """Tests for DeepResearchAgent helper methods."""

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_serialize_task(self, mock_note_tool, mock_llm_class, test_config):
        """Test _serialize_task method."""
        mock_llm_class.return_value = MagicMock()
        agent = DeepResearchAgent(config=test_config)

        task = ResearchTask(
            id=1,
            title="测试任务",
            intent="测试意图",
            query="测试查询",
            status="in_progress",
            summary="测试总结",
            sources_summary="测试来源",
            note_id="note-123",
            note_path="/path/to/note.md",
            stream_token="task_1"
        )

        result = agent._serialize_task(task)

        assert result["id"] == 1
        assert result["title"] == "测试任务"
        assert result["intent"] == "测试意图"
        assert result["query"] == "测试查询"
        assert result["status"] == "in_progress"
        assert result["summary"] == "测试总结"
        assert result["sources_summary"] == "测试来源"
        assert result["note_id"] == "note-123"
        assert result["note_path"] == "/path/to/note.md"
        assert result["stream_token"] == "task_1"

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_extract_note_id_from_text(self, mock_note_tool, mock_llm_class, test_config):
        """Test _extract_note_id_from_text static method."""
        mock_llm_class.return_value = MagicMock()
        agent = DeepResearchAgent(config=test_config)

        # Valid response
        response = "✅ Note created with ID: abc123-def456"
        result = agent._extract_note_id_from_text(response)
        assert result == "abc123-def456"

        # No ID found
        response = "Note created successfully"
        result = agent._extract_note_id_from_text(response)
        assert result is None

        # Empty response
        result = agent._extract_note_id_from_text("")
        assert result is None

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    def test_during_tool_events(self, mock_note_tool, mock_llm_class, test_config):
        """Test _drain_tool_events method."""
        mock_llm_class.return_value = MagicMock()
        agent = DeepResearchAgent(config=test_config)

        state = ResearchState(research_topic="Test")

        # Mock tracker to return some events
        agent._tool_tracker.drain = MagicMock(return_value=[
            {"tool": "note", "action": "create"},
            {"tool": "note", "action": "update"}
        ])

        events = agent._drain_tool_events(state)

        assert len(events) == 2
        assert events[0]["tool"] == "note"
        assert events[1]["tool"] == "note"


class TestDeepResearchAgentIntegration:
    """Integration-style tests for DeepResearchAgent."""

    @patch('agent.HelloAgentsLLM')
    @patch('agent.NoteTool')
    @patch('services.search.dispatch_search')
    def test_talking_face_research_workflow(self, mock_dispatch_search, mock_note_tool, mock_llm_class, talking_face_topic):
        """Test the complete workflow for talking face generation research."""
        config = Configuration(
            enable_notes=False,
            enable_archiving=False,
            max_web_research_loops=2
        )
        mock_llm_class.return_value = MagicMock()
        mock_note_tool.return_value = MagicMock()

        agent = DeepResearchAgent(config=config)

        # Mock planner to return talking face research tasks
        agent.planner.plan_todo_list = MagicMock(
            return_value=[
                ResearchTask(
                    id=1,
                    title="技术背景",
                    intent="了解talking face generation的技术原理和发展历程",
                    query="talking face generation technology principles 2025"
                ),
                ResearchTask(
                    id=2,
                    title="商业应用场景",
                    intent="分析talking face generation在商业领域的应用案例",
                    query="talking face generation business applications 2025"
                ),
                ResearchTask(
                    id=3,
                    title="效果评估",
                    intent="评估talking face generation的应用效果和用户体验",
                    query="talking face generation user experience evaluation"
                )
            ]
        )

        # Mock search dispatch
        mock_dispatch_search.return_value = (
            {"results": [{"title": "Test Result", "url": "http://example.com", "content": "Content"}]},
            [],
            "AI Answer",
            "duckduckgo"
        )

        # Mock summarizer
        agent.summarizer.summarize_task = MagicMock(
            return_value="Talking face generation技术在2025年取得了显著进展..."
        )

        # Mock reporter
        agent.reporting.generate_report = MagicMock(
            return_value=f"""# {talking_face_topic}

## 背景概览
Talking face generation技术是指通过算法生成与语音同步的人脸动画...

## 核心洞见
1. 技术成熟度提升，商业应用可行性增强
2. 虚拟主播、客服机器人等应用场景快速发展
3. 用户体验和接受度显著提高

## 应用场景
- 虚拟主播和直播
- 客服和咨询机器人
- 教育培训
- 影视娱乐

## 参考来源
- 技术研究论文
- 行业报告
"""
        )

        result = agent.run(talking_face_topic)

        assert result.report_markdown is not None
        assert "talking face" in result.report_markdown.lower()
        assert len(result.todo_items) == 3
        assert result.todo_items[0].title == "技术背景"
        assert result.todo_items[1].title == "商业应用场景"
        assert result.todo_items[2].title == "效果评估"
        assert agent.planner.plan_todo_list.called
        assert agent.reporting.generate_report.called
