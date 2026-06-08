"""State models used by the deep research workflow."""

from dataclasses import dataclass, field
from typing import List, Optional


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
