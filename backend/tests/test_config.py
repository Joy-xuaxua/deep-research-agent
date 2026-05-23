"""Tests for Configuration model."""

import os

import pytest

from config import Configuration, SearchAPI


class TestConfiguration:
    """Tests for Configuration class."""

    def test_default_configuration(self):
        """Test creating a Configuration with default values."""
        config = Configuration()
        assert config.max_web_research_loops == 3
        assert config.local_llm == "llama3.2"
        assert config.llm_provider == "ollama"
        assert config.search_api == SearchAPI.DUCKDUCKGO
        assert config.enable_notes is True
        assert config.notes_workspace == "./notes"
        assert config.fetch_full_page is True
        assert config.ollama_base_url == "http://localhost:11434"
        assert config.lmstudio_base_url == "http://localhost:1234/v1"
        assert config.strip_thinking_tokens is True
        assert config.use_tool_calling is False
        assert config.llm_api_key is None
        assert config.llm_base_url is None
        assert config.llm_model_id is None
        assert config.enable_archiving is True
        assert config.archives_dir == "./archives"

    def test_configuration_with_custom_values(self):
        """Test creating a Configuration with custom values."""
        config = Configuration(
            max_web_research_loops=5,
            local_llm="qwen2.5",
            llm_provider="custom",
            search_api=SearchAPI.PERPLEXITY,
            enable_notes=False,
            notes_workspace="./custom_notes",
            fetch_full_page=False,
            llm_api_key="test-key",
            llm_base_url="http://custom-api:8080",
            llm_model_id="custom-model"
        )
        assert config.max_web_research_loops == 5
        assert config.local_llm == "qwen2.5"
        assert config.llm_provider == "custom"
        assert config.search_api == SearchAPI.PERPLEXITY
        assert config.enable_notes is False
        assert config.notes_workspace == "./custom_notes"
        assert config.fetch_full_page is False
        assert config.llm_api_key == "test-key"
        assert config.llm_base_url == "http://custom-api:8080"
        assert config.llm_model_id == "custom-model"

    def test_from_env_with_environment_variables(self, monkeypatch):
        """Test Configuration.from_env() with environment variables."""
        monkeypatch.setenv("LLM_PROVIDER", "custom")
        monkeypatch.setenv("LLM_MODEL_ID", "gpt-4")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
        monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("SEARCH_API", "tavily")
        monkeypatch.setenv("MAX_WEB_RESEARCH_LOOPS", "5")
        monkeypatch.setenv("FETCH_FULL_PAGE", "False")
        monkeypatch.setenv("ENABLE_NOTES", "False")
        monkeypatch.setenv("ENABLE_ARCHIVING", "False")

        config = Configuration.from_env()
        assert config.llm_provider == "custom"
        assert config.llm_model_id == "gpt-4"
        assert config.llm_api_key == "sk-test-key"
        assert config.llm_base_url == "https://api.openai.com/v1"
        assert config.search_api == SearchAPI.TAVILY
        assert config.max_web_research_loops == 5
        assert config.fetch_full_page is False
        assert config.enable_notes is False
        assert config.enable_archiving is False

    def test_from_env_with_overrides(self, monkeypatch):
        """Test Configuration.from_env() with override dictionary."""
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("LOCAL_LLM", "llama3.2")
        monkeypatch.setenv("SEARCH_API", "duckduckgo")

        config = Configuration.from_env(overrides={
            "llm_provider": "custom",
            "search_api": SearchAPI.PERPLEXITY,
            "max_web_research_loops": 7
        })
        assert config.llm_provider == "custom"
        assert config.search_api == SearchAPI.PERPLEXITY
        assert config.max_web_research_loops == 7
        # Local LLM should remain from environment
        assert config.local_llm == "llama3.2"

    def test_sanitized_ollama_url(self):
        """Test sanitized_ollama_url() method."""
        config = Configuration(ollama_base_url="http://localhost:11434")
        assert config.sanitized_ollama_url() == "http://localhost:11434/v1"

        config = Configuration(ollama_base_url="http://localhost:11434/")
        assert config.sanitized_ollama_url() == "http://localhost:11434/v1"

        config = Configuration(ollama_base_url="http://localhost:11434/v1")
        assert config.sanitized_ollama_url() == "http://localhost:11434/v1"

    def test_resolved_model_with_llm_model_id(self):
        """Test resolved_model() returns llm_model_id when set."""
        config = Configuration(
            llm_model_id="gpt-4",
            local_llm="llama3.2"
        )
        assert config.resolved_model() == "gpt-4"

    def test_resolved_model_fallback_to_local_llm(self):
        """Test resolved_model() falls back to local_llm."""
        config = Configuration(
            llm_model_id=None,
            local_llm="qwen2.5"
        )
        assert config.resolved_model() == "qwen2.5"

    def test_resolved_model_returns_none_when_both_unset(self):
        """Test resolved_model() returns None when both are unset."""
        config = Configuration(
            llm_model_id=None,
            local_llm=None
        )
        assert config.resolved_model() is None

    def test_search_api_enum_values(self):
        """Test SearchAPI enum values."""
        assert SearchAPI.PERPLEXITY.value == "perplexity"
        assert SearchAPI.TAVILY.value == "tavily"
        assert SearchAPI.DUCKDUCKGO.value == "duckduckgo"
        assert SearchAPI.SEARXNG.value == "searxng"
        assert SearchAPI.ADVANCED.value == "advanced"

    def test_configuration_for_talking_face_research(self):
        """Test Configuration for talking face generation research."""
        config = Configuration(
            max_web_research_loops=4,
            search_api=SearchAPI.DUCKDUCKGO,
            fetch_full_page=True,
            enable_notes=True,
            enable_archiving=True
        )
        assert config.max_web_research_loops == 4
        assert config.search_api == SearchAPI.DUCKDUCKGO
        assert config.fetch_full_page is True
        assert config.enable_notes is True
        assert config.enable_archiving is True

    def test_archiving_configuration(self, monkeypatch):
        """Test archiving-related configuration."""
        config = Configuration(
            enable_archiving=True,
            archives_dir="./test_archives"
        )
        assert config.enable_archiving is True
        assert config.archives_dir == "./test_archives"

        monkeypatch.setenv("ENABLE_ARCHIVING", "False")
        monkeypatch.setenv("ARCHIVES_DIR", "./custom_archives")
        config_from_env = Configuration.from_env()
        assert config_from_env.enable_archiving is False
        assert config_from_env.archives_dir == "./custom_archives"
