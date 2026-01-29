"""Service for archiving completed research notes."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

from loguru import logger


def extract_timestamp_from_note_id(note_id: str) -> Optional[str]:
    """Extract timestamp from note_id in format note_YYYYMMDD_HHMMSS_X.

    Args:
        note_id: The note identifier (e.g., "note_20260128_163238_0")

    Returns:
        The timestamp string (YYYYMMDD_HHMMSS), or None if not found
    """
    match = re.match(r'note_(\d{8})_(\d{6})_', note_id)
    if match:
        return f"{match.group(1)}_{match.group(2)}"
    return None


def get_research_timestamp(
    report_note_id: Optional[str],
    task_note_ids: dict[int, str]
) -> Optional[str]:
    """Get timestamp for the research from note_id(s).

    Uses the earliest timestamp from report or task notes.

    Args:
        report_note_id: Note ID of the final report
        task_note_ids: Map of task_id to note_id

    Returns:
        The timestamp string (YYYYMMDD_HHMMSS), or None if not found
    """
    timestamps = []

    if report_note_id:
        ts = extract_timestamp_from_note_id(report_note_id)
        if ts:
            timestamps.append(ts)

    for note_id in task_note_ids.values():
        ts = extract_timestamp_from_note_id(note_id)
        if ts:
            timestamps.append(ts)

    if timestamps:
        # Return the earliest (first created) timestamp
        return min(timestamps)

    return None


def sanitize_topic(topic: str) -> str:
    """Convert research topic to safe directory name."""
    # Remove or replace special characters
    safe = re.sub(r'[<>:"/\\|?*]', '', topic)
    safe = safe.strip()
    # Limit length
    if len(safe) > 100:
        safe = safe[:100]
    return safe or "untitled_research"


def sanitize_filename(name: str) -> str:
    """Convert string to safe filename."""
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    safe = safe.strip()
    # Replace multiple spaces with single underscore
    safe = re.sub(r'\s+', '_', safe)
    # Limit length
    if len(safe) > 80:
        safe = safe[:80]
    return safe or "unnamed"


class NoteArchiver:
    """Handles archiving of research notes after completion."""

    def __init__(
        self,
        workspace: str,
        archives_dir: str = "./archives"
    ) -> None:
        """Initialize archiver with workspace and archives directory.

        Args:
            workspace: Path to notes workspace (source directory)
            archives_dir: Path to archives root (destination directory)
        """
        self.workspace = Path(workspace)
        self.archives_dir = Path(archives_dir)

    def archive_research(
        self,
        research_topic: str,
        report_note_id: Optional[str],
        task_note_ids: dict[int, str],
        task_titles: dict[int, str],
        status: str = "completed"
    ) -> dict[str, str]:
        """Archive all notes for a completed research.

        Args:
            research_topic: The research topic title
            report_note_id: Note ID of the final report
            task_note_ids: Map of task_id to note_id
            task_titles: Map of task_id to task title
            status: Research status (completed/failed)

        Returns:
            Dict with archived file paths:
            {
                "archive_dir": "...",
                "report_path": "...",
                "task_paths": {task_id: "..."},
                "orphaned_note_paths": [...]  # Additional notes that were archived
            }
        """
        # Get timestamp from note_id(s)
        timestamp = get_research_timestamp(report_note_id, task_note_ids)

        # Create archive directory with timestamp prefix
        safe_topic = sanitize_topic(research_topic)
        status_suffix = "_failed" if status == "failed" else ""

        if timestamp:
            archive_name = f"{timestamp}_{safe_topic}{status_suffix}"
        else:
            archive_name = f"{safe_topic}{status_suffix}"

        archive_dir = self.archives_dir / archive_name
        archive_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created archive directory: {archive_dir}")

        result = {
            "archive_dir": str(archive_dir),
            "report_path": None,
            "task_paths": {},
            "orphaned_note_paths": []
        }

        # Track note_ids that should be archived
        tracked_note_ids = set(task_note_ids.values())
        if report_note_id:
            tracked_note_ids.add(report_note_id)

        # Archive report note - preserve note_id in filename
        if report_note_id:
            report_title = "report"
            safe_report_title = sanitize_filename(report_title)
            new_name = f"{report_note_id}_{safe_report_title}.md"

            report_path = self._archive_note(
                note_id=report_note_id,
                new_name=new_name,
                archive_dir=archive_dir
            )
            result["report_path"] = report_path
            logger.info(f"Archived report to: {report_path}")

        # Archive task notes - preserve note_id in filename
        for task_id, note_id in task_note_ids.items():
            task_title = task_titles.get(task_id, f"task_{task_id}")
            safe_title = sanitize_filename(task_title)
            new_name = f"{note_id}_{safe_title}.md"

            task_path = self._archive_note(
                note_id=note_id,
                new_name=new_name,
                archive_dir=archive_dir
            )
            result["task_paths"][task_id] = task_path
            logger.info(f"Archived task {task_id} to: {task_path}")

        # Check for orphaned notes in workspace and archive them too
        orphaned_paths = self._archive_orphaned_notes(
            archive_dir=archive_dir,
            exclude_note_ids=tracked_note_ids
        )
        result["orphaned_note_paths"] = orphaned_paths

        if orphaned_paths:
            logger.warning(f"Found and archived {len(orphaned_paths)} orphaned notes: {orphaned_paths}")

        return result

    def _archive_note(
        self,
        note_id: str,
        new_name: str,
        archive_dir: Path
    ) -> Optional[str]:
        """Move a single note file to archive with new name.

        Args:
            note_id: The note identifier
            new_name: New filename for the archived note
            archive_dir: Destination directory

        Returns:
            Path to archived file, or None if source doesn't exist
        """
        source = self.workspace / f"{note_id}.md"
        destination = archive_dir / new_name

        if not source.exists():
            logger.warning(f"Source note not found: {source}")
            return None

        # Handle name collision
        counter = 1
        base_name = destination.stem
        suffix = destination.suffix
        while destination.exists():
            destination = archive_dir / f"{base_name}_{counter}{suffix}"
            counter += 1

        shutil.move(str(source), str(destination))
        return str(destination)

    def _archive_orphaned_notes(
        self,
        archive_dir: Path,
        exclude_note_ids: set[str]
    ) -> list[str]:
        """Archive any remaining .md files in workspace that weren't explicitly tracked.

        Args:
            archive_dir: Destination directory for orphaned notes
            exclude_note_ids: Note IDs that were already archived

        Returns:
            List of paths where orphaned notes were moved
        """
        orphaned_paths = []

        for note_file in self.workspace.glob("*.md"):
            note_id = note_file.stem
            if note_id in exclude_note_ids:
                continue

            # Archive the orphaned note with its note_id as filename
            new_name = f"{note_id}_orphaned.md"
            destination = archive_dir / new_name

            # Handle name collision
            counter = 1
            base_name = destination.stem
            suffix = destination.suffix
            while destination.exists():
                destination = archive_dir / f"{base_name}_{counter}{suffix}"
                counter += 1

            try:
                shutil.move(str(note_file), str(destination))
                orphaned_paths.append(str(destination))
                logger.info(f"Archived orphaned note {note_id} to: {destination}")
            except Exception as e:
                logger.error(f"Failed to archive orphaned note {note_id}: {e}")

        return orphaned_paths

    def cleanup_workspace(
        self,
        exclude_note_ids: Optional[set[str]] = None
    ) -> list[str]:
        """Remove orphaned notes from workspace.

        Args:
            exclude_note_ids: Note IDs to keep (not delete)

        Returns:
            List of deleted file paths
        """
        if exclude_note_ids is None:
            exclude_note_ids = set()

        deleted = []
        for note_file in self.workspace.glob("*.md"):
            note_id = note_file.stem
            if note_id not in exclude_note_ids:
                try:
                    note_file.unlink()
                    deleted.append(str(note_file))
                    logger.info(f"Cleaned up workspace note: {note_file}")
                except Exception as e:
                    logger.error(f"Failed to delete {note_file}: {e}")

        return deleted

    def get_archive_info(self, research_topic: str) -> dict:
        """Get information about existing archive for a topic.

        Args:
            research_topic: The research topic

        Returns:
            Dict with archive info:
            {
                "exists": bool,
                "path": str or None,
                "file_count": int,
                "files": [...]
            }
        """
        safe_topic = sanitize_topic(research_topic)
        archive_dir = self.archives_dir / safe_topic

        if not archive_dir.exists():
            return {
                "exists": False,
                "path": None,
                "file_count": 0,
                "files": []
            }

        files = list(archive_dir.glob("*.md"))
        return {
            "exists": True,
            "path": str(archive_dir),
            "file_count": len(files),
            "files": [f.name for f in files]
        }
