"""Service responsible for validating search result quality using LLM judgment.

This service implements the two-stage search optimization by validating source
relevance before full content is fetched. It follows the same design pattern as
PlanningService - wrapping an agent with domain-specific interfaces.
"""

from __future__ import annotations

import logging
from typing import Any, List, Tuple

from hello_agents import ToolAwareSimpleAgent

from config import Configuration
from prompts import source_validator_system_prompt, source_validation_user_prompt
from models import ResearchTask

logger = logging.getLogger(__name__)


class SourceValidator:
    """Uses LLM judgment to determine if sources match task intent.

    Design pattern follows PlanningService:
    - Agent is created externally and passed in
    - Service provides domain-specific validation interfaces
    - Maintains no internal state between validations
    """

    def __init__(self, validator_agent: ToolAwareSimpleAgent, config: Configuration) -> None:
        """Initialize the validator with an agent and configuration.

        Args:
            validator_agent: ToolAwareSimpleAgent for LLM-based validation
            config: Configuration object with validation settings
        """
        self._agent = validator_agent
        self._config = config

    def validate_sources(
        self,
        sources: list[dict],
        task_intent: str,
        task_query: str,
    ) -> tuple[list[dict], list[dict]]:
        """Validate information sources and return valid/invalid lists.

        Each source is evaluated individually based on title, URL, and snippet.
        The LLM determines whether the source is relevant to the task intent.

        Args:
            sources: List of search result dictionaries with title, url, content fields
            task_intent: Description of what the task aims to accomplish
            task_query: The search query used to find these sources

        Returns:
            Tuple of (valid_sources, invalid_sources) lists
        """
        valid: list[dict] = []
        invalid: list[dict] = []

        for source in sources:
            prompt = self._build_validation_prompt(source, task_intent, task_query)

            response = self._agent.run(prompt)
            self._agent.clear_history()  # Clear context after each validation

            is_valid = self._parse_validation_response(response)
            if is_valid:
                valid.append(source)
            else:
                invalid.append(source)
                logger.debug("Source filtered: %s - %s", source.get("url", "unknown"), response)

        logger.info(
            "Source validation: %d valid, %d filtered out of %d total",
            len(valid), len(invalid), len(sources)
        )
        return valid, invalid

    def _build_validation_prompt(
        self,
        source: dict,
        task_intent: str,
        task_query: str,
    ) -> str:
        """Build validation prompt for a single source.

        Args:
            source: Source dictionary with title, url, content fields
            task_intent: Task intent description
            task_query: Search query used

        Returns:
            Formatted prompt string for LLM validation
        """
        title = source.get("title", "")
        content = source.get("content", source.get("snippet", ""))
        url = source.get("url", "")

        return source_validation_user_prompt.format(
            task_intent=task_intent,
            task_query=task_query,
            title=title,
            url=url,
            content=content
        )

    def _parse_validation_response(self, response: str) -> bool:
        """Parse LLM's validation judgment from response text.

        Args:
            response: LLM response text to parse

        Returns:
            True if source is valid, False otherwise
        """
        text = response.strip().upper()
        return text.startswith("VALID")
