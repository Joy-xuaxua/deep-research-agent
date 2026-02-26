"""Search dispatch helpers leveraging HelloAgents SearchTool."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional, Tuple

import httpx
from hello_agents.tools import SearchTool

from config import Configuration
from utils import (
    deduplicate_and_format_sources,
    format_sources,
    get_config_value,
)

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_SOURCE = 2000
CHARS_PER_TOKEN = 4
_GLOBAL_SEARCH_TOOL = SearchTool(backend="hybrid")


def dispatch_search(
    query: str,
    config: Configuration,
    loop_count: int,
    fetch_full_page: bool | None = None,
) -> Tuple[dict[str, Any] | None, list[str], Optional[str], str]:
    """Execute configured search backend and normalise response payload.

    Args:
        query: The search query string
        config: Configuration object with search settings
        loop_count: Current research loop iteration count
        fetch_full_page: If None, use config.fetch_full_page;
                        If explicitly specified, overrides global config
                        (used for two-stage search optimization)

    Returns:
        Tuple of (search_result_payload, notices_list, answer_text, backend_label)
    """

    search_api = get_config_value(config.search_api)

    # Use explicit parameter or fall back to config
    should_fetch_full = (
        fetch_full_page if fetch_full_page is not None
        else config.fetch_full_page
    )

    try:
        raw_response = _GLOBAL_SEARCH_TOOL.run(
            {
                "input": query,
                "backend": search_api,
                "mode": "structured",
                "fetch_full_page": should_fetch_full,
                "max_results": 5,
                "max_tokens_per_source": MAX_TOKENS_PER_SOURCE,
                "loop_count": loop_count,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Search backend %s failed: %s", search_api, exc)
        raise

    if isinstance(raw_response, str):
        notices = [raw_response]
        logger.warning("Search backend %s returned text notice: %s", search_api, raw_response)
        payload: dict[str, Any] = {
            "results": [],
            "backend": search_api,
            "answer": None,
            "notices": notices,
        }
    else:
        payload = raw_response
        notices = list(payload.get("notices") or [])

    backend_label = str(payload.get("backend") or search_api)
    answer_text = payload.get("answer")
    results = payload.get("results", [])

    if notices:
        for notice in notices:
            logger.info("Search notice (%s): %s", backend_label, notice)

    logger.info(
        "Search backend=%s resolved_backend=%s answer=%s results=%s",
        search_api,
        backend_label,
        bool(answer_text),
        len(results),
    )

    return payload, notices, answer_text, backend_label


def prepare_research_context(
    search_result: dict[str, Any] | None,
    answer_text: Optional[str],
    config: Configuration,
) -> tuple[str, str]:
    """Build structured context and source summary for downstream agents."""

    sources_summary = format_sources(search_result)
    context = deduplicate_and_format_sources(
        search_result or {"results": []},
        max_tokens_per_source=MAX_TOKENS_PER_SOURCE,
        fetch_full_page=config.fetch_full_page,
    )

    if answer_text:
        context = f"AI直接答案：\n{answer_text}\n\n{context}"

    return sources_summary, context


def fetch_full_content_for_sources(
    sources: list[dict],
    config: Configuration,
) -> list[dict]:
    """Fetch full page content for validated sources.

    This is the second stage of two-stage search: only fetch full content
    for sources that passed validation, saving bandwidth and time.

    P0: Supports Tavily and Perplexity
    P1: DuckDuckGo and Searxng (uses fallback httpx approach)

    Args:
        sources: List of source dictionaries with url field
        config: Configuration object with API keys

    Returns:
        List of sources with added raw_content field
    """
    search_api = get_config_value(config.search_api)

    # P0: Tavily
    if search_api == "tavily":
        return _fetch_tavily_content(sources, config)

    # P0: Perplexity
    if search_api == "perplexity":
        return _fetch_perplexity_content(sources, config)

    # P1: Fallback for other backends
    logger.warning(
        f"Full content fetch not yet supported for {search_api}, using lightweight sources only"
    )
    return sources


def _fetch_tavily_content(sources: list[dict], config: Configuration) -> list[dict]:
    """Fetch full content using Tavily Extract API.

    Tavily has a dedicated /extract endpoint for fetching full page content.
    See: https://docs.tavily.com/docs/tavily-api/rest/endpoints/extract

    Args:
        sources: List of source dictionaries with url field
        config: Configuration object with Tavily API key

    Returns:
        List of sources with added raw_content field
    """
    api_key = config.tavily_api_key if hasattr(config, 'tavily_api_key') else os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("TAVILY_API_KEY not set, skipping full content fetch")
        return sources

    headers = {"Authorization": f"Bearer {api_key}"}

    for source in sources:
        try:
            response = httpx.post(
                "https://api.tavily.com/extract",
                json={"urls": [source["url"]]},
                headers=headers,
                timeout=30,
            )
            result = response.json()
            if result.get("results"):
                source["raw_content"] = result["results"][0].get("content", "")
        except Exception as e:
            logger.warning("Tavily extract failed for %s: %s", source.get('url', 'unknown'), e)

    return sources


def _fetch_perplexity_content(sources: list[dict], config: Configuration) -> list[dict]:
    """Fetch full content using Perplexity Online API.

    Perplexity may not have a dedicated extract endpoint, so we use a
    fallback approach with httpx for now.

    TODO: Research Perplexity API documentation for native extract support.

    Args:
        sources: List of source dictionaries with url field
        config: Configuration object

    Returns:
        List of sources with added raw_content field
    """
    # Fallback to generic httpx approach
    return _fetch_with_httpx(sources, config)


def _fetch_with_httpx(sources: list[dict], config: Configuration) -> list[dict]:
    """Fetch full content using httpx directly (generic fallback).

    This is a P1 implementation for backends without dedicated extract APIs.
    Uses basic HTTP fetching with text extraction.

    Args:
        sources: List of source dictionaries with url field
        config: Configuration object

    Returns:
        List of sources with added raw_content field
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DeepResearch/1.0)"}

    for source in sources:
        try:
            response = httpx.get(source["url"], headers=headers, timeout=10)
            # Simple text extraction (could be enhanced with BeautifulSoup)
            text = response.text
            # Limit content size
            max_chars = MAX_TOKENS_PER_SOURCE * CHARS_PER_TOKEN
            source["raw_content"] = text[:max_chars]
        except Exception as e:
            logger.warning("HTTP fetch failed for %s: %s", source.get('url', 'unknown'), e)
            source["raw_content"] = ""

    return sources
