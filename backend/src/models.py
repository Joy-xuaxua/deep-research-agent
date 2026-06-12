"""State models used by the deep research workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass(kw_only=True)
class SourceInfo:
    """A single search result source with metadata and optional full content.

    Created from search API responses via ``from_dict()`` and converted back
    to plain dicts via ``to_dict()`` for backward compatibility with dict-based
    APIs (HelloAgents SearchTool, etc.).

    Attributes:
        title: Page title from the search result. Falls back to url if empty.
        url: Canonical page URL. Used as the deduplication key across the
            research pipeline.
        abstract: Short summary text returned by the search API (1-3 sentences).
            May originate from keys named ``content``, ``snippet``, ``body``,
            ``text``, or ``description`` depending on the backend —
            ``from_dict()`` handles this normalisation.
        content: Full page text fetched after the lightweight search stage
            (two-stage search optimisation). ``None`` until a fetch backend
            populates it.
    """

    title: str
    url: str
    abstract: str = field(default="")
    content: Optional[str] = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        """Convert to the standard source dict shape for backward compatibility.

        Maps internal field names to the output dict keys:
        ``abstract`` → ``abstract``, ``content`` → ``content``.
        """
        result: dict[str, Any] = {
            "title": self.title,
            "url": self.url,
            "abstract": self.abstract,
        }
        if self.content is not None:
            result["content"] = self.content
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceInfo:
        """Construct a SourceInfo from a search API result dict.

        Handles key aliases that appear across different search backends:
        - ``name`` → ``title`` when ``title`` is absent.
        - ``link`` / ``href`` → ``url`` when ``url`` is absent.
        - ``content``, ``snippet``, ``body``, ``text``, ``description`` →
          ``abstract`` (first non-empty value wins).
        - ``raw_content`` → ``content``.
        """
        url = (
            data.get("url")
            or data.get("link")
            or data.get("href")
            or ""
        )
        title = (
            data.get("title")
            or data.get("name")
            or url
        )
        abstract = (
            data.get("content")
            or data.get("snippet")
            or data.get("body")
            or data.get("text")
            or data.get("description")
            or ""
        )
        content = data.get("raw_content")

        return cls(
            title=title,
            url=url,
            abstract=abstract,
            content=content,
        )


@dataclass(kw_only=True)
class ResearchTask:
    """A single research sub-task within a research session.

    Each task represents one aspect of the overall research topic that will be
    investigated independently through search, validation, and summarization.
    """

    id: int
    title: str
    intent: str
    query: str
    status: str = field(default="pending")
    summary: Optional[str] = field(default=None)
    sources_summary: Optional[str] = field(default=None)
    notices: list[str] = field(default_factory=list)
    note_id: Optional[str] = field(default=None)
    note_path: Optional[str] = field(default=None)
    stream_token: Optional[str] = field(default=None)


@dataclass(kw_only=True)
class ResearchState:
    """State of an active research session.

    Owns the research topic, all tasks, the final report, and
    persistence/archive metadata.
    """

    research_topic: str = field(default=None)
    todo_items: List[ResearchTask] = field(default_factory=list)
    research_loop_count: int = field(default=0)
    # Report
    report: Optional[str] = field(default=None)
    report_note_id: Optional[str] = field(default=None)
    report_note_path: Optional[str] = field(default=None)
    # Archive
    archive_dir: Optional[str] = field(default=None)


@dataclass(kw_only=True)
class ResearchResult:
    """API response for a completed research session."""

    report_markdown: Optional[str] = field(default=None)
    todo_items: List[ResearchTask] = field(default_factory=list)
