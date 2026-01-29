## Project Overview

This is **HelloAgents Deep Researcher** - a fully local web research and summarization assistant. It consists of a Python FastAPI backend that orchestrates multi-agent research workflows using the HelloAgents framework, and a Vue 3 frontend that provides a streaming UI for real-time research progress.

## Technology Stack

**Backend:**
- Python 3.10+ with `uv` as package manager
- FastAPI - web framework with SSE streaming support
- HelloAgents (`hello-agents>=0.2.8`) - agent orchestration framework with ToolAwareSimpleAgent
- Multiple search backends: DuckDuckGo, Tavily, Perplexity, Searxng
- NoteTool integration for persistent task notes
- Loguru for structured logging

**Frontend:**
- Vue 3 with Composition API and TypeScript
- Vite for build tooling
- Axios for HTTP requests with Server-Sent Events (SSE)
- Single-file component architecture (`App.vue`)

## Development Commands

### Backend

```bash
cd backend

# Install dependencies (uses uv)
uv sync

# Run development server with auto-reload
uv run python src/main.py
# OR with uvicorn directly
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Run linting (ruff configured in pyproject.toml)
uv run ruff check src/

# Run type checking (mypy)
uv run mypy src/
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run development server (default: http://localhost:5173)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## Architecture

### Backend Architecture

The core is the `DeepResearchAgent` class in `backend/src/agent.py` which orchestrates a multi-stage research workflow:

1. **Planning Phase** (`services/planner.py`): Generates a TODO list of research tasks using a specialized agent
2. **Execution Phase**: For each task, performs web search + summarization in parallel threads
3. **Reporting Phase** (`services/reporter.py`): Synthesizes all research into a final markdown report

**Key Components:**

- `DeepResearchAgent` - Main coordinator managing the workflow state
- `ToolAwareSimpleAgent` - HelloAgents agent with tool calling support (NoteTool)
- `PlanningService` - Generates research TODO items
- `SummarizationService` - Streams task summaries
- `ReportingService` - Generates final reports
- `ToolCallTracker` - Records all tool interactions for frontend display
- `dispatch_search()` (`services/search.py`) - Routes to configured search backend

**Configuration (`config.py`):**
- Environment-based config via `Configuration.from_env()`
- Supports multiple LLM providers: ollama, lmstudio, custom (OpenAI-compatible)
- Search API selection: duckduckgo, tavily, perplexity, searxng
- NoteTool workspace configuration
- See `backend/.env.example` for all options

### API Endpoints

- `POST /research` - Non-streaming research execution
- `POST /research/stream` - Server-Sent Events streaming endpoint
- `GET /healthz` - Health check

**Streaming Event Types:**
- `status` - General status messages
- `todo_list` - Initial task list with metadata
- `task_status` - Task state updates (pending/in_progress/completed/skipped)
- `sources` - Search results for a task
- `task_summary_chunk` - Streaming summary text
- `tool_call` - NoteTool invocations with parameters/results
- `final_report` - Complete research report
- `archived` - Notes archived to archives directory (contains archive_dir, task_count)
- `archive_failed` - Archive operation failed (contains error)
- `error` - Error events
- `done` - Stream completion

### Note Workspace & Archiving

**Workspace Structure:**
```
./notes/                          # Active workspace
├── {task_note_id}.md             # Task state notes (note_type: task_state)
└── {report_note_id}.md           # Final report (note_type: conclusion)

./archives/                       # Archived research (moved after completion)
└── {research_topic_safe}/        # One directory per research topic
    ├── report.md                 # Final report (renamed)
    └── task_{id}_{title}.md      # Task notes (renamed)
```

**Archiving Process:**
After research completes (success or failure):
1. All notes are moved from `./notes/` to `./archives/{topic}/`
2. Files are renamed meaningfully (report.md, task_1_title.md, etc.)
3. Configured via `ENABLE_ARCHIVING` and `ARCHIVES_DIR` environment variables

**Key Components:**
- `NoteArchiver` (`services/archiver.py`) - Handles note archival with safe filename generation
- Archive info is added to `SummaryState` (archive_dir, archive_report_path, archive_task_paths)

### Frontend Architecture

Single Vue 3 application (`App.vue`) with two layout states:
1. **Centered** - Initial form for research topic input
2. **Fullscreen** - Sidebar + results panel with real-time updates

**State Management:**
- Reactive refs for loading, errors, tasks, reports
- Event-driven UI updates via SSE event handlers
- Task selection and detail view

**Key Services:**
- `services/api.ts` - `runResearchStream()` handles SSE parsing with AbortController support

## Configuration

### Environment Variables (Backend)

Key variables from `backend/.env.example`:

```bash
# LLM Configuration
LLM_PROVIDER=custom          # ollama, lmstudio, or custom
LLM_MODEL_ID=your-model-name
LLM_API_KEY=your-api-key
LLM_BASE_URL=your-api-base-url

# For local models
# LLM_PROVIDER=ollama
# LOCAL_LLM=qwen_qwq-32b
# OLLAMA_BASE_URL=http://localhost:11434

# Search Configuration
SEARCH_API=duckduckgo        # duckduckgo, tavily, perplexity, searxng

# Optional: API keys for paid search services
# TAVILY_API_KEY=tvly-xxxxx
# PERPLEXITY_API_KEY=pplx-xxxxx

# Research Behavior
MAX_WEB_RESEARCH_LOOPS=3
FETCH_FULL_PAGE=True

# Note Archiving (moves notes to archives after completion)
ENABLE_ARCHIVING=True            # Enable/disable automatic note archiving
ARCHIVES_DIR=./archives          # Root directory for archived research
```

### Frontend Environment

```bash
# frontend/.env.local
VITE_API_BASE_URL=http://localhost:8000
```

## Project Structure Notes

- Backend source is in `backend/src/` using setuptools layout
- Frontend source is in `frontend/src/`
- Notes workspace (`./notes` by default) stores markdown files from NoteTool
- The app supports both streaming and non-streaming modes
- Tool calling (NoteTool) is optional via `enable_notes` config
