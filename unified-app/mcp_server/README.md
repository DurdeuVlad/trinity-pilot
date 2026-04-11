# Orchestrator MCP Server

MCP (Model Context Protocol) server for controlling and testing the Orchestrator Desktop App.

## Features

- **Task Submission**: Submit tasks to the live orchestrator via the Qt event bus
- **Canonical Case Submission**: Submit cases directly from `trinity-pilot/docs/live-test-cases/`
- **Status Monitoring**: Query task execution status in real-time
- **Live Event Streaming**: Read incremental live run events through the app command surface
- **Execution Log**: Read the full turn-by-turn execution log (actions, reflections, replans)
- **Execution Plan**: Inspect the macro plan steps and their statuses
- **Artifact Bundles**: Resolve task details, checkpoints, flight reports, prompts, responses, and screenshots together
- **Flight Records**: Read YAML flight reports saved to disk after each CLI objective
- **History Access**: Browse task history and execution details
- **Checkpoint Inspection**: Examine checkpoints and resilience features
- **Settings Control**: Get and update orchestrator settings

Related local surfaces:
- `python -m mcp_server.app_control_cli ...` exposes a terminal-friendly command interface to the running app
- `python -m mcp_server.terminal_session_mcp` exposes a separate durable terminal/session MCP server

Repeat-run lifecycle:
- Start the desktop app through the MCP/CLI lifecycle surface before the first live iteration instead of assuming the GUI is already running.
- Before starting the next iteration of a live test batch, reset or clean up the previous run state through the app command surface so the new submission does not inherit stale sessions or task context.
- After the final repetition, shut down the desktop app instead of leaving it resident. That gives the orchestrator a deterministic chance to close spawned backend sessions and any apps launched during the run.

## Installation

```bash
cd unified-app
pip install mcp
```

## Usage

### Start the MCP Server

```bash
python -m mcp_server.orchestrator_mcp
```

### Terminal-Friendly App Control

```bash
python -m mcp_server.app_control_cli start-ui
python -m mcp_server.app_control_cli list-cases
python -m mcp_server.app_control_cli submit-case TC-BROWSER-01
python -m mcp_server.app_control_cli stream-events latest
python -m mcp_server.app_control_cli get-artifact-bundle latest
python -m mcp_server.app_control_cli reset-session
python -m mcp_server.app_control_cli shutdown-ui
```

### Dedicated Terminal Session MCP

```bash
python -m mcp_server.terminal_session_mcp
```

### Notable Additional Tools

- `list_cases`
- `submit_case`
- `get_live_events`
- `get_artifact_bundle`
- `start_ui`: launch the desktop app if needed and wait for the command surface to become ready
- `reset_session`: clear desktop-app run state between repeated live-test iterations
- `shutdown_ui`: close the desktop app after the final repetition so owned sessions are not left running

---

#### 1. submit_task
Submit a new task to the live orchestrator.  Task is dispatched via the Qt event bus to the running GUI app.

**Parameters:**
- `description` (string, required): Task description
- `domain` (string, optional): `cli` | `browser` | `desktop` | `mixed`. Default: `"mixed"`

**Example:**
```json
{
  "description": "List all Python files in the current directory",
  "domain": "cli"
}
```

**Response:**
```json
{
  "task_id": "run_abc123",
  "description": "...",
  "domain": "cli",
  "status": "submitted",
  "message": "Task submitted to orchestrator. Use get_task_status to monitor progress."
}
```

---

#### 2. get_task_status
Get the current status of a task.

**Parameters:**
- `task_id` (string, required): Task ID — or `"latest"` to query the most recent task

**Response:**
```json
{
  "task_id": "run_abc123",
  "description": "...",
  "status": "completed",
  "created_at": "2026-03-18T14:20:00Z",
  "completed_at": "2026-03-18T14:21:18Z"
}
```

---

#### 3. list_tasks
List tasks from history.

**Parameters:**
- `limit` (integer, optional): Max tasks to return. Default: 10
- `status` (string, optional): Filter by `completed` | `failed` | `running` | `cancelled`

---

#### 4. get_task_details
Get detailed information about a task including all execution steps.

**Parameters:**
- `task_id` (string, required): Task ID — or `"latest"`

**Response includes:** task metadata + step list with statuses and result summaries.

---

#### 5. get_execution_log
Read the full turn-by-turn execution log for a task: every status message, action chosen,
reflection result, and replan decision.

**Parameters:**
- `task_id` (string, required): Task ID — or `"latest"`

**Response:**
```json
{
  "task_id": "run_abc123",
  "log_entries": [
    { "level": "INFO",    "message": "Decomposing task into objectives…", "timestamp": "…" },
    { "level": "SUCCESS", "message": "3 objectives identified",           "timestamp": "…" },
    { "level": "INFO",    "message": "Obj 1 | turn 1: choosing action…", "timestamp": "…" }
  ],
  "entry_count": 18
}
```

---

#### 6. get_execution_plan
Read the macro plan: step descriptions, statuses, confidence, and estimated durations.

**Parameters:**
- `task_id` (string, required): Task ID — or `"latest"`

**Response:**
```json
{
  "task_id": "run_abc123",
  "steps": [
    { "step_number": 1, "description": "List top 5 largest files…", "status": "COMPLETED" },
    { "step_number": 2, "description": "Get free disk space…",       "status": "COMPLETED" }
  ],
  "step_count": 2
}
```

---

#### 7. list_flight_records
List YAML flight report files saved to `_runtime/flight_reports/` after each CLI objective run.

**Parameters:**
- `limit` (integer, optional): Max files to return. Default: 20

**Response:**
```json
{
  "flight_records": [
    { "filename": "cli-session-20260318-142105/cli-obj-142105/report.yaml",
      "modified": "2026-03-18T14:21:16Z",
      "size_bytes": 1842 }
  ],
  "count": 3
}
```

---

#### 8. read_flight_record
Read a specific flight record YAML file by filename (relative to `_runtime/flight_reports/`).

**Parameters:**
- `filename` (string, required): Relative path returned by `list_flight_records`

---

#### 9. get_latest_flight_record
Convenience: read the most recently modified flight record without needing its filename.

**Parameters:** None

---

#### 10. list_checkpoints
List all resilience checkpoints saved for a task.

**Parameters:**
- `task_id` (string, required): Task ID

---

#### 11. get_checkpoint_details
Inspect the `ExecutionContext` snapshot stored in a checkpoint.

**Parameters:**
- `checkpoint_id` (string, required): Checkpoint ID from `list_checkpoints`

---

#### 12. get_settings
Get current orchestrator settings. API keys are redacted in the response.

**Parameters:** None

---

#### 13. update_settings
Update orchestrator settings at runtime.

**Parameters:**
- `settings` (object, required): Key-value pairs to update

**Example:**
```json
{ "settings": { "default_domain": "cli", "max_retries": 5 } }
```

---

## Architecture

```
AI Agent (Claude / Gemini / GPT)
    │
    ▼
MCP Client
    │
    ▼
MCP Server (orchestrator_mcp.py)  ← runs inside the same Python process as the Qt GUI
    │
    ├── Qt Event Bus  ──► OrchestratorCore ──► TrinityBridge ──► trinity_core backends
    │                                                              (CLI / Browser / Desktop)
    ├── HistoryManager    (SQLite: _runtime/orchestrator_history.db)
    ├── CheckpointManager (pickle files: _runtime/checkpoints/)
    ├── SettingsManager   (JSON:   _runtime/settings.json)
    └── Flight Reports    (YAML:   _runtime/flight_reports/)
```

## Frontend Layout (as of 2026-03-18)

```
┌─────────────────────────────────────────────────────────────────┐
│ Run │ History │ Settings                                [tabs]   │
├─────────────────────────────────────────────────────────────────┤
│ Task Description                                                 │
│ [task text input — compact, max 120 px]          [Run] [Cancel] │
├──────────────────────────────┬──────────────────────────────────┤
│ Execution Objectives         │ Execution Log                    │
│ and Steps                    │                                  │
│  (40% width, scrollable)     │  (60% width, monospace, no-wrap) │
│                              │                                  │
│  [Objective 1 ✓]             │  [14:20:28] [INFO] Decomposing…  │
│  [Objective 2 ✓]             │  [14:20:29] [SUCCESS] 2 obj…     │
│  [Objective 3 …]             │  [14:20:51] [SUCCESS] Obj 1 done │
│                              │                                  │
│      ◄─── drag splitter ───► │                                  │
└──────────────────────────────┴──────────────────────────────────┘
```

- Window starts **maximized**. Minimum size: 800×560.
- The vertical divider between the two panels is a **draggable QSplitter** — grab it to give more room to either side.
- Works at full screen and at half-screen (snap to half monitor).

## Testing Workflow

```
# 1. Submit a task
submit_task  description="List top 5 processes by CPU"  domain="cli"

# 2. Poll until done
get_task_status  task_id="latest"

# 3. Read the full execution narrative
get_execution_log  task_id="latest"

# 4. See the plan steps
get_execution_plan  task_id="latest"

# 5. Read the CLI flight record
get_latest_flight_record

# 6. Inspect resilience checkpoints
list_checkpoints  task_id="latest"
```
