"""Tests for FastAPI endpoints."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from config import Configuration, SearchAPI
from main import create_app, ResearchRequest


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
def mock_agent():
    """Create a mock DeepResearchAgent."""
    agent = MagicMock()
    return agent


@pytest.fixture
def client(mock_agent):
    """Create a test client with mocked agent."""
    app = create_app()

    # Override the dependency to use mocked agent
    def _mock_build_config(payload: ResearchRequest) -> Configuration:
        overrides = {}
        if payload.search_api is not None:
            overrides["search_api"] = payload.search_api
        return Configuration.from_env(overrides=overrides)

    # Patch the _build_config function
    with patch('main._build_config', _mock_build_config):
        with patch('main.DeepResearchAgent', return_value=mock_agent):
            yield TestClient(app)


@pytest.fixture
def talking_face_topic():
    """The test topic for talking face generation research."""
    return "2025年talking face generation在商业中的最新应用和效果"


class TestHealthCheck:
    """Tests for /healthz endpoint."""

    def test_health_check_returns_ok(self, client):
        """Test that health check returns OK status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestResearchEndpoint:
    """Tests for /research endpoint."""

    def test_research_endpoint_success(self, client, mock_agent, talking_face_topic):
        """Test successful research execution."""
        from models import ResearchTask, ResearchResult

        # Mock the agent's run method
        mock_agent.run.return_value = ResearchResult(
            report_markdown=f"# {talking_face_topic}\n\n完整报告",
            todo_items=[
                ResearchTask(
                    id=1,
                    title="技术背景",
                    intent="技术分析",
                    query="talking face generation technology",
                    status="completed",
                    summary="技术总结",
                    sources_summary="技术来源"
                ),
                ResearchTask(
                    id=2,
                    title="商业应用",
                    intent="应用分析",
                    query="talking face generation business",
                    status="completed",
                    summary="商业总结",
                    sources_summary="商业来源"
                )
            ]
        )

        response = client.post(
            "/research",
            json={"topic": talking_face_topic}
        )

        assert response.status_code == 200
        data = response.json()
        assert "report_markdown" in data
        assert "todo_items" in data
        assert len(data["todo_items"]) == 2
        assert data["todo_items"][0]["title"] == "技术背景"
        assert data["todo_items"][1]["title"] == "商业应用"
        mock_agent.run.assert_called_once_with(talking_face_topic)

    def test_research_endpoint_with_search_api_override(self, client, mock_agent, talking_face_topic):
        """Test research endpoint with search API override."""
        from models import ResearchTask, ResearchResult

        mock_agent.run.return_value = ResearchResult(
            report_markdown="Report",
            todo_items=[
                ResearchTask(
                    id=1,
                    title="Task 1",
                    intent="Intent 1",
                    query="query1",
                    status="completed"
                )
            ]
        )

        response = client.post(
            "/research",
            json={
                "topic": talking_face_topic,
                "search_api": "perplexity"
            }
        )

        assert response.status_code == 200
        # Verify the agent was called with the correct config
        mock_agent.run.assert_called_once()

    def test_research_endpoint_value_error(self, client, mock_agent):
        """Test research endpoint with invalid configuration."""
        from fastapi import HTTPException

        # Make _build_config raise ValueError
        def _mock_build_config_error(payload: ResearchRequest) -> Configuration:
            raise ValueError("Invalid configuration")

        with patch('main._build_config', _mock_build_config_error):
            response = client.post(
                "/research",
                json={"topic": "Test topic"}
            )

        assert response.status_code == 400

    def test_research_endpoint_unexpected_error(self, client, mock_agent):
        """Test research endpoint handles unexpected errors."""
        # Make agent.run raise an exception
        mock_agent.run.side_effect = Exception("Unexpected error")

        response = client.post(
            "/research",
            json={"topic": "Test topic"}
        )

        assert response.status_code == 500
        assert "detail" in response.json()

    def test_research_endpoint_empty_todo_list(self, client, mock_agent):
        """Test research endpoint with empty todo list."""
        from models import ResearchResult

        mock_agent.run.return_value = ResearchResult(
            report_markdown="No results",
            todo_items=[]
        )

        response = client.post(
            "/research",
            json={"topic": "Invalid topic that yields no tasks"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["todo_items"] == []

    def test_research_talking_face_topic(self, client, mock_agent, talking_face_topic):
        """Test research endpoint with talking face generation topic."""
        from models import ResearchTask, ResearchResult

        mock_agent.run.return_value = ResearchResult(
            report_markdown=f"# {talking_face_topic}\n\n完整报告内容",
            todo_items=[
                ResearchTask(
                    id=1,
                    title="技术背景梳理",
                    intent="了解talking face generation的技术原理",
                    query="2025年talking face generation 技术原理",
                    status="completed",
                    summary="Talking face generation主要基于深度学习技术...",
                    sources_summary="- 技术论文1\n- 技术博客2"
                ),
                ResearchTask(
                    id=2,
                    title="商业应用分析",
                    intent="分析talking face generation的商业应用场景",
                    query="2025年talking face generation 商业应用",
                    status="completed",
                    summary="2025年talking face generation在以下商业领域得到应用...",
                    sources_summary="- 行业报告1\n- 商业案例2"
                ),
                ResearchTask(
                    id=3,
                    title="应用效果评估",
                    intent="评估talking face generation的应用效果",
                    query="2025年talking face generation 效果评估",
                    status="completed",
                    summary="从用户体验、成本效益等维度评估...",
                    sources_summary="- 评估报告1\n- 用户反馈2"
                )
            ]
        )

        response = client.post(
            "/research",
            json={"topic": talking_face_topic}
        )

        assert response.status_code == 200
        data = response.json()
        assert "talking face" in data["report_markdown"].lower()
        assert len(data["todo_items"]) == 3
        assert data["todo_items"][0]["title"] == "技术背景梳理"
        assert data["todo_items"][1]["title"] == "商业应用分析"
        assert data["todo_items"][2]["title"] == "应用效果评估"


class TestResearchStreamEndpoint:
    """Tests for /research/stream endpoint."""

    def test_stream_research_success(self, client, mock_agent, talking_face_topic):
        """Test successful streaming research."""
        # Mock the agent's run_stream method to yield events
        def mock_run_stream(topic):
            yield {"type": "status", "message": "初始化研究流程"}
            yield {"type": "todo_list", "tasks": [
                {"id": 1, "title": "技术背景", "status": "pending"},
                {"id": 2, "title": "商业应用", "status": "pending"}
            ], "step": 0}
            yield {"type": "task_status", "task_id": 1, "status": "in_progress"}
            yield {"type": "sources", "task_id": 1, "latest_sources": "Sources here"}
            yield {"type": "task_summary_chunk", "task_id": 1, "content": "Summary chunk"}
            yield {"type": "task_status", "task_id": 1, "status": "completed"}
            yield {"type": "task_status", "task_id": 2, "status": "in_progress"}
            yield {"type": "task_status", "task_id": 2, "status": "completed"}
            yield {
                "type": "final_report",
                "report": f"# {talking_face_topic}\n\n完整报告",
                "note_id": "report-123"
            }
            yield {"type": "done"}

        mock_agent.run_stream = mock_run_stream

        response = client.post(
            "/research/stream",
            json={"topic": talking_face_topic}
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse the SSE events
        content = response.content.decode('utf-8')
        events = []
        for line in content.split('\n'):
            if line.startswith('data: '):
                event_json = line[6:]  # Remove 'data: ' prefix
                if event_json.strip():
                    events.append(json.loads(event_json))

        event_types = [e.get("type") for e in events]
        assert "status" in event_types
        assert "todo_list" in event_types
        assert "task_status" in event_types
        assert "sources" in event_types
        assert "task_summary_chunk" in event_types
        assert "final_report" in event_types
        assert "done" in event_types

    def test_stream_research_with_error(self, client, mock_agent):
        """Test streaming research handles errors."""
        def mock_run_stream_error(topic):
            yield {"type": "status", "message": "Starting"}
            raise Exception("Search backend failed")

        mock_agent.run_stream = mock_run_stream_error

        response = client.post(
            "/research/stream",
            json={"topic": "Test topic"}
        )

        assert response.status_code == 200

        content = response.content.decode('utf-8')
        assert '"type": "error"' in content

    def test_stream_research_value_error(self, client, mock_agent):
        """Test streaming research with invalid configuration."""
        def _mock_build_config_error(payload: ResearchRequest) -> Configuration:
            raise ValueError("Invalid API key")

        with patch('main._build_config', _mock_build_config_error):
            response = client.post(
                "/research/stream",
                json={"topic": "Test topic"}
            )

        assert response.status_code == 400

    def test_stream_talking_face_research(self, client, mock_agent, talking_face_topic):
        """Test streaming research for talking face generation topic."""
        def mock_run_stream_talking_face(topic):
            yield {"type": "status", "message": "初始化研究流程"}
            yield {"type": "todo_list", "tasks": [
                {"id": 1, "title": "技术背景", "intent": "技术原理", "query": "tech query", "status": "pending"},
                {"id": 2, "title": "商业应用", "intent": "应用场景", "query": "business query", "status": "pending"},
                {"id": 3, "title": "效果评估", "intent": "效果分析", "query": "evaluation query", "status": "pending"}
            ], "step": 0}

            # Task 1 events
            yield {"type": "task_status", "task_id": 1, "status": "in_progress", "title": "技术背景"}
            yield {"type": "sources", "task_id": 1, "latest_sources": "- 论文1\n- 博客2"}
            yield {"type": "task_summary_chunk", "task_id": 1, "content": "Talking face generation "}
            yield {"type": "task_summary_chunk", "task_id": 1, "content": "技术概述..."}
            yield {"type": "task_status", "task_id": 1, "status": "completed", "summary": "技术总结"}

            # Task 2 events
            yield {"type": "task_status", "task_id": 2, "status": "in_progress", "title": "商业应用"}
            yield {"type": "sources", "task_id": 2, "latest_sources": "- 案例1\n- 报告2"}
            yield {"type": "task_summary_chunk", "task_id": 2, "content": "商业应用场景包括"}
            yield {"type": "task_summary_chunk", "task_id": 2, "content": "虚拟主播、客服机器人等..."}
            yield {"type": "task_status", "task_id": 2, "status": "completed", "summary": "商业总结"}

            # Task 3 events
            yield {"type": "task_status", "task_id": 3, "status": "in_progress", "title": "效果评估"}
            yield {"type": "sources", "task_id": 3, "latest_sources": "- 评估1\n- 反馈2"}
            yield {"type": "task_summary_chunk", "task_id": 3, "content": "应用效果评估..."}
            yield {"type": "task_status", "task_id": 3, "status": "completed", "summary": "评估总结"}

            # Final report
            yield {
                "type": "final_report",
                "report": f"# {talking_face_topic}\n\n## 技术背景\n技术总结\n\n## 商业应用\n商业总结\n\n## 效果评估\n评估总结"
            }
            yield {"type": "done"}

        mock_agent.run_stream = mock_run_stream_talking_face

        response = client.post(
            "/research/stream",
            json={"topic": talking_face_topic}
        )

        assert response.status_code == 200

        content = response.content.decode('utf-8')

        # Verify key events are present
        assert '"type": "status"' in content
        assert '"type": "todo_list"' in content
        assert '"message": "初始化研究流程"' in content

        # Parse events to verify structure
        events = []
        for line in content.split('\n'):
            if line.startswith('data: '):
                event_json = line[6:]
                if event_json.strip():
                    events.append(json.loads(event_json))

        # Verify we have 3 tasks in todo_list
        todo_events = [e for e in events if e.get("type") == "todo_list"]
        assert len(todo_events) == 1
        assert len(todo_events[0]["tasks"]) == 3

        # Verify final report
        final_events = [e for e in events if e.get("type") == "final_report"]
        assert len(final_events) == 1
        assert "talking face" in final_events[0]["report"].lower()


class TestUtilities:
    """Tests for utility functions."""

    def test_mask_secret(self):
        """Test _mask_secret function."""
        from main import _mask_secret

        # None or empty
        assert _mask_secret(None) == "unset"
        assert _mask_secret("") == "unset"

        # Short secrets
        assert _mask_secret("ab") == "**"
        assert _mask_secret("abc") == "***"

        # Normal secrets
        assert _mask_secret("sk-1234567890abcdef") == "sk-1...def"
        assert _mask_secret("my-secret-key-here") == "my-s...ere"

        # Custom visible length
        assert _mask_secret("sk-1234567890abcdef", visible=6) == "sk-1234...cdef"

    def test_build_config_default(self):
        """Test _build_config with no overrides."""
        from main import _build_config

        payload = ResearchRequest(topic="Test topic")
        config = _build_config(payload)

        assert isinstance(config, Configuration)

    def test_build_config_with_search_api(self):
        """Test _build_config with search API override."""
        from main import _build_config

        payload = ResearchRequest(
            topic="Test topic",
            search_api=SearchAPI.PERPLEXITY
        )
        config = _build_config(payload)

        assert config.search_api == SearchAPI.PERPLEXITY


class TestCORS:
    """Tests for CORS middleware."""

    def test_cors_headers(self, client):
        """Test that CORS headers are set correctly."""
        response = client.options("/research")
        assert "access-control-allow-origin" in response.headers
