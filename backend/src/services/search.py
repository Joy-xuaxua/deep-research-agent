"""Search dispatch helpers leveraging HelloAgents SearchTool."""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional, Tuple

import httpx
from hello_agents.tools import SearchTool

from config import Configuration
from models import SourceInfo
from services.archiver import sanitize_topic
from token_utils import truncate_to_tokens
from utils import (
    deduplicate_and_format_sources,
    format_sources,
    get_config_value,
)

logger = logging.getLogger(__name__)

MAX_TOKENS_PER_SOURCE = 5000
KEIRO_API_URL = "https://kierolabs.space/api/v2/keiro"
KEIRO_DEFAULT_MAX_RESULTS = 5
_GLOBAL_SEARCH_TOOL = SearchTool(backend="hybrid")

# Directory for persisting fetched website content
WEBSITES_INFO_DIR = Path(__file__).resolve().parent.parent.parent / "websites_info"


def _save_raw_content(source: SourceInfo, session_dir: Path) -> None:
    """Persist full_content of a source to a markdown file in session_dir.

    Args:
        source: SourceInfo with url, title, and full_content fields.
        session_dir: Per-session directory under websites_info/.
    """
    content = source.full_content or ""
    if not content:
        return

    try:
        session_dir.mkdir(parents=True, exist_ok=True)

        # Build safe filename: domain + short hash of URL
        url = source.url or "unknown"
        domain = url.split("//")[-1].split("/")[0] if "//" in url else "unknown"
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        filename = f"{domain}_{url_hash}.md"

        filepath = session_dir / filename
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = source.title or url

        file_content = (
            f"# {title}\n"
            f"- **URL**: {url}\n"
            f"- **Fetched**: {now}\n\n"
            f"{content}"
        )

        filepath.write_text(file_content, encoding="utf-8")
        logger.debug("Saved raw content to %s", filepath)
    except Exception as exc:
        logger.warning("Failed to save raw content for %s: %s", source.url or "unknown", exc)


def dispatch_search(
    query: str,
    config: Configuration,
    loop_count: int,
    fetch_full_page: bool | None = None,
    max_tokens_per_source: int = MAX_TOKENS_PER_SOURCE,
) -> Tuple[dict[str, Any] | None, list[str], Optional[str], str]:
    """Execute configured search backend and normalise response payload.

    Args:
        query: The search query string
        config: Configuration object with search settings
        loop_count: Current research loop iteration count
        fetch_full_page: If None, use config.fetch_full_page;
                        If explicitly specified, overrides global config
                        (used for two-stage search optimization)
        max_tokens_per_source: Maximum tokens per source for content truncation

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
        # Keiro: direct API call, bypasses HelloAgents SearchTool
        if search_api == "keiro":
            payload = _search_keiro(query, config)
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
        logger.info("dispatch_search: query in vague search: %s", query)
        raw_response = _GLOBAL_SEARCH_TOOL.run(
            {
                "input": query,
                "backend": search_api,
                "mode": "structured",
                "fetch_full_page": should_fetch_full,
                "max_results": 10,
                "max_tokens_per_source": max_tokens_per_source,
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
    max_tokens_per_source: int = MAX_TOKENS_PER_SOURCE,
) -> tuple[str, str]:
    """Build structured context and source summary for downstream agents.

    Args:
        search_result: Search result payload with results list
        answer_text: Optional AI-generated answer from search engine
        config: Configuration object
        max_tokens_per_source: Maximum tokens per source for content truncation

    Returns:
        Tuple of (sources_summary, formatted_context)
    """
    sources_url = format_sources(search_result)
    context = deduplicate_and_format_sources(
        search_result or {"results": []},
        max_tokens_per_source=max_tokens_per_source,
        fetch_full_page=config.fetch_full_page,
    )

    if answer_text:
        context = f"LLM directly gives answer :\n{answer_text}\n\n{context}"

    return sources_url, context


def fetch_full_content_for_sources(
    sources: list[SourceInfo],
    config: Configuration,
    *,
    research_topic: str | None = None,
    max_tokens_per_source: int = MAX_TOKENS_PER_SOURCE,
) -> list[SourceInfo]:
    """Fetch full page content for validated sources.

    This is the second stage of two-stage search: only fetch full content
    for sources that passed validation, saving bandwidth and time.

    P0: Supports Tavily and Perplexity
    P1: DuckDuckGo and Searxng (uses fallback httpx approach)

    Args:
        sources: List of SourceInfo objects with url field
        config: Configuration object with API keys
        research_topic: Optional topic for per-session file organization
        max_tokens_per_source: Maximum tokens per source for content truncation

    Returns:
        List of SourceInfo with full_content populated
    """
    search_api = get_config_value(config.search_api)

    # P0: Tavily
    if search_api == "tavily":
        return _fetch_tavily_content(sources, config, research_topic=research_topic)

    # P0: Perplexity
    if search_api == "perplexity":
        return _fetch_perplexity_content(sources, config, max_tokens_per_source=max_tokens_per_source)

    # P1: Keiro (no dedicated extract endpoint, use httpx fallback)
    if search_api == "keiro":
        return _fetch_with_httpx(sources, config, max_tokens_per_source=max_tokens_per_source)

    # P1: Fallback for other backends
    logger.warning(
        f"Full content fetch not yet supported for {search_api}, using lightweight sources only"
    )
    return sources


def _fetch_tavily_content(
    sources: list[SourceInfo],
    config: Configuration,
    *,
    research_topic: str | None = None,
) -> list[SourceInfo]:
    """Fetch full content using Tavily Extract API.

    Tavily has a dedicated /extract endpoint for fetching full page content.
    See: https://docs.tavily.com/docs/tavily-api/rest/endpoints/extract

    When research_topic is provided, fetched content is also persisted to
    ``websites_info/{timestamp}_{topic}/`` for offline review.

    Args:
        sources: List of SourceInfo objects with url field
        config: Configuration object with Tavily API key
        research_topic: Optional topic for per-session file organization

    Returns:
        List of SourceInfo with full_content populated
    """
    api_key = config.tavily_api_key if hasattr(config, 'tavily_api_key') else os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("TAVILY_API_KEY not set, skipping full content fetch")
        return sources

    # Build per-session directory if topic is available
    session_dir: Path | None = None
    if research_topic:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = sanitize_topic(research_topic)
        session_dir = WEBSITES_INFO_DIR / f"{timestamp}_{safe_topic}"

    headers = {"Authorization": f"Bearer {api_key}"}

    for source in sources:
        try:
            response = httpx.post(
                "https://api.tavily.com/extract",
                json={"urls": [source.url]},
                headers=headers,
                timeout=30,
            )
            result = response.json()
            if result.get("results"):
                source.full_content = result["results"][0].get("content", "")
                if session_dir:
                    _save_raw_content(source, session_dir)
        except Exception as e:
            logger.warning("Tavily extract failed for %s: %s", source.url or 'unknown', e)

    return sources


def _fetch_perplexity_content(sources: list[SourceInfo], config: Configuration, max_tokens_per_source: int = MAX_TOKENS_PER_SOURCE) -> list[SourceInfo]:
    """Fetch full content using Perplexity Online API.

    Perplexity may not have a dedicated extract endpoint, so we use a
    fallback approach with httpx for now.

    TODO: Research Perplexity API documentation for native extract support.

    Args:
        sources: List of SourceInfo objects with url field
        config: Configuration object
        max_tokens_per_source: Maximum tokens per source for content truncation

    Returns:
        List of SourceInfo with full_content populated
    """
    # Fallback to generic httpx approach
    return _fetch_with_httpx(sources, config, max_tokens_per_source=max_tokens_per_source)


def _search_keiro(query: str, config: Configuration) -> dict[str, Any]:
    """Search using Keiro API (https://kierolabs.space/api/v2/keiro).

    Calls the Keiro search service directly and normalises the response
    into the standard search result payload format.

    Args:
        query: The search query string
        config: Configuration object with keiro_api_key

    Returns:
        Standardised payload dict with results, backend, answer, notices
    """
    api_key = config.keiro_api_key or os.getenv("KEIRO_API_KEY")
    if not api_key:
        raise ValueError("KEIRO_API_KEY is required for keiro search backend")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    request_payload = {
        "query": query,
        "maxResults": KEIRO_DEFAULT_MAX_RESULTS,
    }

    response = httpx.post(
        KEIRO_API_URL,
        json=request_payload,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    # Normalise keiro response to standard payload format
    # Keiro returns results in a top-level array or nested under a key;
    # handle both common patterns and map to {title, url, content}.
    raw_results = []

    # Pattern 1: {"results": [...]}
    if isinstance(data, dict) and "results" in data:
        raw_results = data["results"]
    # Pattern 2: top-level list
    elif isinstance(data, list):
        raw_results = data
    # Pattern 3: single dict wrapper with data/docs/items
    elif isinstance(data, dict):
        for key in ("data", "docs", "items", "sources"):
            if key in data and isinstance(data[key], list):
                raw_results = data[key]
                break

    normalised_results: list[dict[str, Any]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        normalised_results.append(SourceInfo.from_dict(item).to_dict())

    # Check for a direct AI-style answer in the response
    answer = None
    if isinstance(data, dict):
        answer = data.get("answer") or data.get("summary") or None

    return {
        "results": normalised_results,
        "backend": "keiro",
        "answer": answer,
        "notices": [],
    }


def _fetch_with_httpx(sources: list[SourceInfo], config: Configuration, max_tokens_per_source: int = MAX_TOKENS_PER_SOURCE) -> list[SourceInfo]:
    """Fetch full content using httpx directly (generic fallback).

    This is a P1 implementation for backends without dedicated extract APIs.
    Uses basic HTTP fetching with text extraction.

    Args:
        sources: List of SourceInfo objects with url field
        config: Configuration object
        max_tokens_per_source: Maximum tokens to keep per source

    Returns:
        List of SourceInfo with full_content populated
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DeepResearch/1.0)"}

    for source in sources:
        try:
            response = httpx.get(source.url, headers=headers, timeout=10)
            text = response.text
            source.full_content = truncate_to_tokens(text, max_tokens_per_source)
        except Exception as e:
            logger.warning("HTTP fetch failed for %s: %s", source.url or 'unknown', e)
            source.full_content = ""

    return sources
