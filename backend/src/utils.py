"""Utility helpers shared across deep researcher services."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from models import SourceInfo
from token_utils import truncate_to_tokens

logger = logging.getLogger(__name__)


def get_config_value(value: Any) -> str:
    """Return configuration value as plain string."""

    return value if isinstance(value, str) else value.value


def strip_thinking_tokens(text: str) -> str:
    """Remove ``<think/>`` sections from model responses."""

    while "<think/>" in text and "</think/>" in text:
        start = text.find("<think/>")
        end = text.find("</think/>") + len("</think/>")
        text = text[:start] + text[end:]
    return text


def _extract_sources_list(
    search_response: Dict[str, Any] | List[SourceInfo],
) -> list[SourceInfo]:
    """Normalise a search payload or raw SourceInfo list into list[SourceInfo]."""
    if isinstance(search_response, list):
        raw = search_response
    else:
        raw = search_response.get("results", [])
    # Results may be SourceInfo objects or plain dicts (from task_executor
    # converting via to_dict(), or from HelloAgents SearchTool).
    return [s if isinstance(s, SourceInfo) else SourceInfo.from_dict(s) for s in raw]


def deduplicate_and_format_sources(
    search_response: Dict[str, Any] | List[SourceInfo],
    max_tokens_per_source: int,
    *,
    fetch_full_page: bool = False,
) -> str:
    """Format and deduplicate search results for downstream prompting."""

    sources_list = _extract_sources_list(search_response)

    unique_sources: dict[str, SourceInfo] = {}
    for source in sources_list:
        if not source.url:
            continue
        if source.url not in unique_sources:
            unique_sources[source.url] = source

    formatted_parts: List[str] = []
    for source in unique_sources.values():
        title = source.title or source.url
        formatted_parts.append(f"Title: {title}\n\n")
        formatted_parts.append(f"URL: {source.url}\n\n")
        formatted_parts.append(f"Abstract: {source.abstract}\n\n")

        if fetch_full_page:
            full = source.content
            if full is None:
                logger.debug("full_content missing for %s", source.url)
                full = ""
            full = truncate_to_tokens(full, max_tokens_per_source)
            formatted_parts.append(
                f"Content: {full}\n\n"
            )

    return "".join(formatted_parts).strip()


def format_sources(search_results: list[SourceInfo] | None) -> str:
    """Return bullet list summarising search sources."""

    if not search_results:
        return ""

    lines: list[str] = []
    for item in search_results:
        if isinstance(item, SourceInfo):
            if not item.url:
                continue
            lines.append(f"* {item.title or item.url} : {item.url}")
        else:
            url = item.get("url", "")
            if not url:
                continue
            lines.append(f"* {item.get('title', url)} : {url}")
    return "\n".join(lines)


_TRUNCATE_SUFFIX = " ... [truncated]"  # mirrors token_utils.py suffix style


def _truncate_words(text: str, max_words: int = 50) -> str:
    """Truncate ``text`` to at most ``max_words`` whitespace-separated words."""

    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + _TRUNCATE_SUFFIX


def truncate_dict_for_print(data: Any, *, max_words: int = 50) -> str:
    """Pretty-print ``data`` with long string values truncated to ``max_words`` words.

    Recurses into nested dicts, lists, and tuples; keys and non-string scalars
    are left untouched. Returns an indented JSON string suitable for logging.
    """

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            return _truncate_words(value, max_words)
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v) for v in value)
        return value

    return json.dumps(_walk(data), indent=2, ensure_ascii=False, default=str)
