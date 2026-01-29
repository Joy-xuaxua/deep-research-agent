#!/usr/bin/env python3
"""Simple script to trigger the deep research agent with a specific topic."""

import json
import sys
import time
from typing import Any

import requests

# Configuration
API_BASE_URL = "http://localhost:8000"
RESEARCH_TOPIC = "2025年talking face generation在商业中的最新应用和效果"
USE_STREAMING = True  # Set to False for non-streaming mode


def print_event(event: dict[str, Any]) -> None:
    """Pretty print a research event."""
    event_type = event.get("type", "unknown")

    if event_type == "status":
        message = event.get("message", "")
        print(f"[STATUS] {message}")

    elif event_type == "todo_list":
        tasks = event.get("tasks", [])
        print(f"\n{'='*60}")
        print(f"[TODO LIST] Generated {len(tasks)} research tasks:")
        print(f"{'='*60}")
        for task in tasks:
            print(f"\n  Task {task['id']}: {task['title']}")
            print(f"  Intent: {task['intent']}")
            print(f"  Query: {task['query']}")
            print(f"  Status: {task['status']}")

    elif event_type == "task_status":
        task_id = event.get("task_id")
        status = event.get("status")
        title = event.get("title", "")
        print(f"\n[TASK {task_id}] Status: {status.upper()} - {title}")

    elif event_type == "sources":
        task_id = event.get("task_id")
        sources = event.get("latest_sources", "")
        print(f"[TASK {task_id}] Sources found:")
        for line in sources.split("\n"):
            if line.strip():
                print(f"  {line}")

    elif event_type == "task_summary_chunk":
        task_id = event.get("task_id")
        content = event.get("content", "")
        print(f"[TASK {task_id}] Summary chunk: {content[:100]}...", end="\r")

    elif event_type == "final_report":
        report = event.get("report", "")
        print(f"\n{'='*60}")
        print("[FINAL REPORT]")
        print(f"{'='*60}")
        print(report)

    elif event_type == "archived":
        archive_dir = event.get("archive_dir")
        task_count = event.get("task_count")
        print(f"\n[ARCHIVED] Research archived to: {archive_dir} ({task_count} tasks)")

    elif event_type == "error":
        detail = event.get("detail", "Unknown error")
        print(f"[ERROR] {detail}", file=sys.stderr)

    elif event_type == "done":
        print(f"\n{'='*60}")
        print("[DONE] Research completed successfully!")
        print(f"{'='*60}")


def run_research_streaming(topic: str, base_url: str = API_BASE_URL) -> None:
    """Run research using the streaming endpoint."""
    url = f"{base_url}/research/stream"
    payload = {"topic": topic}

    print(f"Starting research on: {topic}")
    print(f"API endpoint: {url}")
    print("-" * 60)

    try:
        with requests.post(url, json=payload, stream=True, timeout=300) as response:
            if response.status_code != 200:
                print(f"Error: HTTP {response.status_code}", file=sys.stderr)
                print(response.text, file=sys.stderr)
                return

            print("Connected to streaming endpoint...\n")

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix
                    try:
                        event = json.loads(data_str)
                        print_event(event)
                    except json.JSONDecodeError:
                        # Handle partial chunks in streaming
                        continue

    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {url}", file=sys.stderr)
        print("Make sure the backend server is running:", file=sys.stderr)
        print(f"  cd backend && uv run python src/main.py", file=sys.stderr)
    except requests.exceptions.Timeout:
        print("Error: Request timed out", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)


def run_research_non_streaming(topic: str, base_url: str = API_BASE_URL) -> dict[str, Any]:
    """Run research using the non-streaming endpoint."""
    url = f"{base_url}/research"
    payload = {"topic": topic}

    print(f"Starting research on: {topic}")
    print(f"API endpoint: {url}")
    print("-" * 60)

    try:
        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()

        data = response.json()

        print("\n" + "=" * 60)
        print("RESEARCH RESULTS")
        print("=" * 60)

        # Print TODO items
        todo_items = data.get("todo_items", [])
        print(f"\nGenerated {len(todo_items)} tasks:")
        for task in todo_items:
            print(f"\n  Task {task['id']}: {task['title']}")
            print(f"  Status: {task['status']}")
            if task.get('summary'):
                summary = task['summary'][:200] + "..." if len(task['summary']) > 200 else task['summary']
                print(f"  Summary: {summary}")

        # Print report
        print("\n" + "=" * 60)
        print("FINAL REPORT")
        print("=" * 60)
        print(data.get("report_markdown", "No report generated"))

        return data

    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {url}", file=sys.stderr)
        print("Make sure the backend server is running:", file=sys.stderr)
        print(f"  cd backend && uv run python src/main.py", file=sys.stderr)
        return {}
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e}", file=sys.stderr)
        print(e.response.text, file=sys.stderr)
        return {}
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return {}


def main() -> None:
    """Main entry point."""
    topic = RESEARCH_TOPIC

    if USE_STREAMING:
        run_research_streaming(topic)
    else:
        run_research_non_streaming(topic)


if __name__ == "__main__":
    main()
