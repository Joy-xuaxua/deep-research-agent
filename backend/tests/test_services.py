"""Tests for service classes."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from config import Configuration, SearchAPI
from models import ResearchState, ResearchTask
from services.planner import PlanningService, TOOL_CALL_PATTERN
from services.reporter import ReportingService
from services.summarizer import SummarizationService


@pytest.fixture
def mock_agent():
    """Create a mock ToolAwareSimpleAgent."""
    agent = MagicMock()
    agent.run = MagicMock(return_value="Test response")
    agent.clear_history = MagicMock()
    agent.stream_run = MagicMock(return_value=iter(["chunk1", "chunk2"]))
    return agent


@pytest.fixture
def test_config():
    """Create a test configuration."""
    return Configuration(
        max_web_research_loops=3,
        search_api=SearchAPI.DUCKDUCKGO,
        strip_thinking_tokens=False,
        enable_notes=False
    )


@pytest.fixture
def test_state():
    """Create a test ResearchState."""
    return ResearchState(
        research_topic="2025年talking face generation在商业中的最新应用和效果"
    )


class TestPlanningService:
    """Tests for PlanningService."""

    def test_init(self, mock_agent, test_config):
        """Test PlanningService initialization."""
        service = PlanningService(mock_agent, test_config)
        assert service._agent is mock_agent
        assert service._config is test_config

    def test_plan_todo_list_with_json_response(self, mock_agent, test_state, test_config):
        """Test planning with valid JSON response."""
        mock_response = '''
        {
          "tasks": [
            {
              "title": "技术背景分析",
              "intent": "了解talking face generation的核心技术原理",
              "query": "talking face generation technology principles 2025"
            },
            {
              "title": "商业应用研究",
              "intent": "分析商业应用场景和案例",
              "query": "talking face generation business applications"
            }
          ]
        }
        '''
        mock_agent.run.return_value = mock_response

        service = PlanningService(mock_agent, test_config)
        tasks = service.plan_todo_list(test_state)

        assert len(tasks) == 2
        assert tasks[0].id == 1
        assert tasks[0].title == "技术背景分析"
        assert tasks[0].query == "talking face generation technology principles 2025"
        assert tasks[1].id == 2
        assert tasks[1].title == "商业应用研究"
        assert tasks[1].query == "talking face generation business applications"
        mock_agent.clear_history.assert_called_once()

    def test_plan_todo_list_with_array_response(self, mock_agent, test_state, test_config):
        """Test planning with array response."""
        mock_response = '''
        [
          {
            "title": "技术背景",
            "intent": "技术原理分析",
            "query": "talking face technology"
          },
          {
            "title": "商业应用",
            "intent": "商业场景分析",
            "query": "talking face business"
          }
        ]
        '''
        mock_agent.run.return_value = mock_response

        service = PlanningService(mock_agent, test_config)
        tasks = service.plan_todo_list(test_state)

        assert len(tasks) == 2
        assert tasks[0].title == "技术背景"
        assert tasks[1].title == "商业应用"

    def test_plan_todo_list_empty_response(self, mock_agent, test_state, test_config):
        """Test planning with empty response."""
        mock_agent.run.return_value = "No tasks generated"
        mock_agent.clear_history.return_value = None

        service = PlanningService(mock_agent, test_config)
        tasks = service.plan_todo_list(test_state)

        assert tasks == []

    def test_plan_todo_list_with_thinking_tokens(self, mock_agent, test_state, test_config):
        """Test planning strips thinking tokens when configured."""
        mock_response = '''
        <thinking>
        Let me think about this...
        </thinking>
        {
          "tasks": [
            {
              "title": "测试任务",
              "intent": "测试意图",
              "query": "test query"
            }
          ]
        }
        '''
        mock_agent.run.return_value = mock_response
        test_config.strip_thinking_tokens = True

        service = PlanningService(mock_agent, test_config)
        tasks = service.plan_todo_list(test_state)

        assert len(tasks) == 1
        assert tasks[0].title == "测试任务"

    def test_create_fallback_task(self, test_state):
        """Test creating a fallback task."""
        service = PlanningService(Mock(), Configuration())
        task = service.create_fallback_task(test_state)

        assert task.id == 1
        assert task.title == "基础背景梳理"
        assert "2025年talking face generation在商业中的最新应用和效果" in task.query
        assert task.intent == "收集主题的核心背景与最新动态"

    def test_create_fallback_task_empty_topic(self):
        """Test creating a fallback task with empty topic."""
        state = ResearchState(research_topic="")
        service = PlanningService(Mock(), Configuration())
        task = service.create_fallback_task(state)

        assert task.id == 1
        assert task.query == "基础背景梳理"

    def test_extract_json_payload_with_object(self, test_config):
        """Test extracting JSON object from text."""
        service = PlanningService(Mock(), test_config)
        text = "Some preamble {\"tasks\": [{\"title\": \"Task 1\"}]} some trailing text"
        result = service._extract_json_payload(text)

        assert isinstance(result, dict)
        assert "tasks" in result

    def test_extract_json_payload_with_array(self, test_config):
        """Test extracting JSON array from text."""
        service = PlanningService(Mock(), test_config)
        text = "Some preamble [{\"title\": \"Task 1\"}, {\"title\": \"Task 2\"}] trailing"
        result = service._extract_json_payload(text)

        assert isinstance(result, list)
        assert len(result) == 2

    def test_extract_json_payload_no_json(self, test_config):
        """Test extracting JSON when none present."""
        service = PlanningService(Mock(), test_config)
        text = "Just plain text with no JSON"
        result = service._extract_json_payload(text)

        assert result is None

    def test_extract_tool_payload_valid(self, test_config):
        """Test extracting tool payload from TOOL_CALL pattern."""
        service = PlanningService(Mock(), test_config)
        text = '[TOOL_CALL:note:{"action":"create","title":"Test"}]'
        result = service._extract_tool_payload(text)

        assert result is not None
        assert result["action"] == "create"
        assert result["title"] == "Test"

    def test_extract_tool_payload_key_value_format(self, test_config):
        """Test extracting tool payload in key=value format."""
        service = PlanningService(Mock(), test_config)
        text = '[TOOL_CALL:note:action="create", title="Test Task"]'
        result = service._extract_tool_payload(text)

        assert result is not None
        assert result["action"] == "create"
        assert result["title"] == "Test Task"

    def test_extract_tool_payload_no_match(self, test_config):
        """Test extracting tool payload when pattern doesn't match."""
        service = PlanningService(Mock(), test_config)
        text = "No tool call here"
        result = service._extract_tool_payload(text)

        assert result is None

    def test_tool_call_pattern(self):
        """Test the TOOL_CALL_PATTERN regex."""
        text = '[TOOL_CALL:note:{"action":"create"}]'
        match = TOOL_CALL_PATTERN.search(text)
        assert match is not None
        assert match.group("tool") == "note"
        assert match.group("body") == '{"action":"create"}'

    def test_plan_todo_sets_state(self, mock_agent, test_state, test_config):
        """Test that plan_todo_list sets the state's todo_items."""
        mock_response = '{"tasks": [{"title": "Task 1", "intent": "Intent 1", "query": "Query 1"}]}'
        mock_agent.run.return_value = mock_response

        service = PlanningService(mock_agent, test_config)
        tasks = service.plan_todo_list(test_state)

        assert test_state.todo_items is tasks
        assert len(test_state.todo_items) == 1


class TestSummarizationService:
    """Tests for SummarizationService."""

    def test_init(self, mock_agent, test_config):
        """Test SummarizationService initialization."""
        factory = lambda: mock_agent
        service = SummarizationService(factory, test_config)
        assert service._agent_factory is factory
        assert service._config is test_config

    def test_summarize_task(self, mock_agent, test_config):
        """Test synchronous task summarization."""
        factory = lambda: mock_agent
        service = SummarizationService(factory, test_config)

        state = ResearchState(research_topic="Talking Face Generation")
        task = ResearchTask(
            id=1,
            title="技术分析",
            intent="分析技术原理",
            query="talking face technology"
        )
        context = "Research context here"

        mock_agent.run.return_value = "Summary of the research findings."

        result = service.summarize_task(state, task, context)

        assert result == "Summary of the research findings."
        mock_agent.run.assert_called_once()
        mock_agent.clear_history.assert_called_once()

    def test_summarize_task_with_thinking_tokens(self, mock_agent, test_config):
        """Test summarization strips thinking tokens."""
        test_config.strip_thinking_tokens = True
        factory = lambda: mock_agent
        service = SummarizationService(factory, test_config)

        state = ResearchState(research_topic="Test Topic")
        task = ResearchTask(id=1, title="Test", intent="Test", query="test")
        context = "Context"

        mock_agent.run.return_value = "<thinking>Process</thinking>Actual summary"

        result = service.summarize_task(state, task, context)

        assert "Actual summary" in result
        assert "<thinking>" not in result

    def test_summarize_task_empty_response(self, mock_agent, test_config):
        """Test summarization with empty response returns fallback."""
        factory = lambda: mock_agent
        service = SummarizationService(factory, test_config)

        state = ResearchState(research_topic="Test Topic")
        task = ResearchTask(id=1, title="Test", intent="Test", query="test")
        context = "Context"

        mock_agent.run.return_value = "   "

        result = service.summarize_task(state, task, context)

        assert result == "暂无可用信息"

    def test_stream_task_summary(self, mock_agent, test_config):
        """Test streaming task summarization."""
        factory = lambda: mock_agent
        service = SummarizationService(factory, test_config)

        state = ResearchState(research_topic="Talking Face Generation")
        task = ResearchTask(
            id=1,
            title="技术分析",
            intent="分析技术原理",
            query="talking face technology"
        )
        context = "Research context"

        mock_agent.stream_run.return_value = iter(["Summary ", "of ", "research"])

        stream, getter = service.stream_task_summary(state, task, context)

        chunks = list(stream)
        assert "".join(chunks) == "Summary of research"

        final_summary = getter()
        assert final_summary == "Summary of research"
        mock_agent.clear_history.assert_called_once()

    def test_build_prompt(self, mock_agent, test_config):
        """Test _build_prompt method."""
        factory = lambda: mock_agent
        service = SummarizationService(factory, test_config)

        state = ResearchState(research_topic="Talking Face Generation")
        task = ResearchTask(
            id=1,
            title="技术分析",
            intent="分析技术原理",
            query="talking face technology"
        )
        context = "Research context"

        prompt = service._build_prompt(state, task, context)

        assert "Talking Face Generation" in prompt
        assert "技术分析" in prompt
        assert "分析技术原理" in prompt
        assert "talking face technology" in prompt
        assert "Research context" in prompt


class TestReportingService:
    """Tests for ReportingService."""

    def test_init(self, mock_agent, test_config):
        """Test ReportingService initialization."""
        service = ReportingService(mock_agent, test_config)
        assert service._agent is mock_agent
        assert service._config is test_config

    def test_generate_report(self, mock_agent, test_config):
        """Test generating a final report."""
        service = ReportingService(mock_agent, test_config)

        state = ResearchState(
            research_topic="2025年talking face generation在商业中的最新应用和效果"
        )
        state.todo_items = [
            ResearchTask(
                id=1,
                title="技术背景",
                intent="技术原理",
                query="tech query",
                status="completed",
                summary="技术总结内容",
                sources_summary="技术来源"
            ),
            ResearchTask(
                id=2,
                title="商业应用",
                intent="应用场景",
                query="business query",
                status="completed",
                summary="商业总结内容",
                sources_summary="商业来源",
                note_id="note123"
            )
        ]

        mock_agent.run.return_value = "# 研究报告\n\n报告内容..."

        result = service.generate_report(state)

        assert result == "# 研究报告\n\n报告内容..."
        mock_agent.run.assert_called_once()
        mock_agent.clear_history.assert_called_once()

    def test_generate_report_with_thinking_tokens(self, mock_agent, test_config):
        """Test report generation strips thinking tokens."""
        test_config.strip_thinking_tokens = True
        service = ReportingService(mock_agent, test_config)

        state = ResearchState(research_topic="Test Topic")
        state.todo_items = [
            ResearchTask(
                id=1,
                title="Task 1",
                intent="Intent 1",
                query="query1",
                status="completed",
                summary="Summary 1",
                sources_summary="Sources 1"
            )
        ]

        mock_agent.run.return_value = "<thinking>Process</thinking># Report\n\nContent"

        result = service.generate_report(state)

        assert "<thinking>" not in result
        assert "# Report" in result

    def test_generate_report_empty_response(self, mock_agent, test_config):
        """Test report generation with empty response."""
        service = ReportingService(mock_agent, test_config)

        state = ResearchState(research_topic="Test Topic")
        state.todo_items = [
            ResearchTask(
                id=1,
                title="Task 1",
                intent="Intent 1",
                query="query1",
                status="completed",
                summary="Summary 1",
                sources_summary="Sources 1"
            )
        ]

        mock_agent.run.return_value = "   "

        result = service.generate_report(state)

        assert result == "报告生成失败，请检查输入。"

    def test_generate_report_includes_note_references(self, mock_agent, test_config):
        """Test that report generation includes note references when available."""
        service = ReportingService(mock_agent, test_config)

        state = ResearchState(research_topic="Test Topic")
        state.todo_items = [
            ResearchTask(
                id=1,
                title="Task 1",
                intent="Intent 1",
                query="query1",
                status="completed",
                summary="Summary 1",
                sources_summary="Sources 1",
                note_id="note_001"
            ),
            ResearchTask(
                id=2,
                title="Task 2",
                intent="Intent 2",
                query="query2",
                status="completed",
                summary="Summary 2",
                sources_summary="Sources 2"
            )
        ]

        mock_agent.run.return_value = "# Report\n\nContent"

        service.generate_report(state)

        # Check that the prompt includes note references
        call_args = mock_agent.run.call_args[0][0]
        assert "note_001" in call_args
        assert "Task 1" in call_args

    def test_generate_report_talking_face_research(self, mock_agent, test_config):
        """Test generating report for talking face generation research."""
        service = ReportingService(mock_agent, test_config)

        state = ResearchState(
            research_topic="2025年talking face generation在商业中的最新应用和效果"
        )
        state.todo_items = [
            ResearchTask(
                id=1,
                title="技术原理",
                intent="了解talking face generation的技术基础",
                query="talking face generation technology",
                status="completed",
                summary="Talking face generation主要基于音频驱动的面部动画技术...",
                sources_summary="- 技术论文1\n- 技术博客2"
            ),
            ResearchTask(
                id=2,
                title="商业应用",
                intent="分析商业应用场景",
                query="talking face generation business",
                status="completed",
                summary="主要应用场景包括：1. 虚拟主播 2. 客服机器人 3. 教育培训...",
                sources_summary="- 商业案例1\n- 行业报告2"
            )
        ]

        mock_agent.run.return_value = """
# Talking Face Generation商业应用研究报告

## 背景概览
Talking face generation技术在2025年已进入商业化应用阶段...

## 核心洞见
1. 技术成熟度提升
2. 商业应用场景扩展
3. 用户体验改善

## 参考来源
- 任务1: 技术论文1, 技术博客2
- 任务2: 商业案例1, 行业报告2
"""

        result = service.generate_report(state)

        assert "Talking Face Generation" in result
        assert "商业应用" in result
        assert len(mock_agent.run.call_args) == 1
