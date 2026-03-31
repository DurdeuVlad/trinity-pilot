# Functional Requirements - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** FUN-001  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document specifies all functional requirements for the Orchestrator Desktop App, defining what the system must do to meet user needs and business objectives.

---

## 2. Requirements Format

Each requirement follows this structure:
- **ID:** Unique identifier (FR#.#)
- **Name:** Descriptive title
- **Description:** What the system must do
- **Rationale:** Why this is needed
- **Priority:** Must Have / Should Have / Could Have
- **Dependencies:** Other requirements this depends on
- **Acceptance Criteria:** How to verify
- **Status:** Implemented / In Progress / Pending

---

## 3. FR1: Task Submission and Execution

### FR1.1: Accept Natural Language Task Input
**Description:** System shall accept task descriptions in natural language text format

**Rationale:** Users need to describe tasks without writing code or scripts

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- Text input field accepts any UTF-8 text
- Input length validated (1-1000 characters)
- Empty input rejected with error message
- Input persists during session

**Status:** ✅ Implemented

**Implementation:** `ui/panels/task_input_panel.py` - TaskInputPanel class

**Tests:** `tests/ui/test_task_input_panel.py`

---

### FR1.2: Validate Task Input
**Description:** System shall validate task input before submission

**Rationale:** Prevent invalid or malformed tasks from entering orchestration

**Priority:** Must Have

**Dependencies:** FR1.1

**Acceptance Criteria:**
- Non-empty validation (min 1 character)
- Maximum length validation (1000 characters)
- Clear error message displayed for invalid input
- Submit button disabled until valid

**Status:** ✅ Implemented

**Implementation:** `ui/panels/task_input_panel.py` - `on_run_clicked()` validation path

**Tests:** `tests/ui/test_task_input_panel.py::test_empty_input`, `tests/ui/test_task_input_panel.py::test_oversized_input`

---

### FR1.3: Cancel Running Task
**Description:** System shall allow user to cancel task during execution

**Rationale:** Users need ability to stop incorrect or long-running tasks

**Priority:** Must Have

**Dependencies:** FR1.4

**Acceptance Criteria:**
- Cancel button available during execution
- Cancellation stops orchestrator gracefully
- Status logged as "cancelled"
- UI returns to ready state
- History records cancellation

**Status:** ✅ Implemented

**Implementation:** `orchestrator/orchestrator_core.py` - `cancel()` method

**Tests:** `tests/integration/test_orchestrator_core.py::test_cancel`

---

### FR1.4: Execute Task via Orchestrator
**Description:** System shall execute submitted tasks through orchestrator workflow

**Rationale:** Core functionality - transform user intent into automated actions

**Priority:** Must Have

**Dependencies:** FR1.1, FR1.2, FR2.1

**Acceptance Criteria:**
- Task submitted triggers orchestrator execution
- Orchestrator runs asynchronously (non-blocking UI)
- Execution follows generated plan
- Each step executes sequentially
- Errors handled gracefully
- Result recorded in history

**Status:** ✅ Implemented

**Implementation:** `orchestrator/orchestrator_core.py` - `execute_task()` method

**Tests:** `tests/integration/test_full_loop_integration.py`

---

### FR1.5: Support Domain Selection
**Description:** System shall allow user to specify task domain (browser, desktop, auto-detect)

**Rationale:** Different tasks require different adapters

**Priority:** Should Have

**Dependencies:** FR1.1

**Acceptance Criteria:**
- Domain dropdown with options: Auto-detect, Browser, Desktop
- Default is Auto-detect
- Selection passed to orchestrator
- Selection persists during session

**Status:** ✅ Implemented

**Implementation:** `ui/panels/task_input_panel.py` - domain_combo

**Tests:** `tests/ui/test_task_input_panel.py::test_domain_selection`

---

## 4. FR2: Execution Planning

### FR2.1: Generate Execution Plan
**Description:** System shall generate execution plan from task description using MacroPlanner

**Rationale:** Users need to see what will be executed before it runs

**Priority:** Must Have

**Dependencies:** FR1.4

**Acceptance Criteria:**
- Plan generated before execution starts
- Plan contains numbered steps
- Each step has clear description
- Plan displayed in UI
- Plan generation uses Gemini API or mock fallback

**Status:** ✅ Implemented

**Implementation:** `orchestrator/macro_planner.py` - `generate_plan()` method

**Tests:** `tests/unit/test_macro_planner.py`

---

### FR2.2: Display Execution Plan
**Description:** System shall display execution plan in UI before and during execution

**Rationale:** Users need visibility into planned and current steps

**Priority:** Must Have

**Dependencies:** FR2.1

**Acceptance Criteria:**
- Plan displayed as numbered list
- Each step shows description
- Current step highlighted
- Completed steps marked
- Failed steps indicated with error

**Status:** ✅ Implemented

**Implementation:** `ui/panels/execution_plan_panel.py`

**Tests:** `tests/ui/test_execution_plan_panel.py`

---

### FR2.3: Update Step Status
**Description:** System shall update step status in real-time during execution

**Rationale:** Users need to track execution progress

**Priority:** Must Have

**Dependencies:** FR2.2

**Acceptance Criteria:**
- Step status: pending → running → completed/failed
- Status updates trigger UI refresh
- Visual indicators for each status
- Status persists in history

**Status:** ✅ Implemented

**Implementation:** Event bus signals - `step_started`, `step_completed`, `step_failed`

**Tests:** `tests/integration/test_orchestrator_core.py::test_step_status`

---

### FR2.4: Fallback Planning
**Description:** System shall fall back to deterministic planning when Gemini API unavailable

**Rationale:** Application must work offline or without API key

**Priority:** Must Have

**Dependencies:** FR2.1

**Acceptance Criteria:**
- Mock mode activated when GEMINI_MOCK=1
- Deterministic plan generated without API
- Plan structure identical to live mode
- Clear indication of mock mode in logs

**Status:** ✅ Implemented

**Implementation:** `testing/gemini_mock/activator.py`

**Tests:** `tests/integration/test_mock_mode.py`

---

## 5. FR3: Real-Time Monitoring

### FR3.1: Display Status Log
**Description:** System shall display real-time status log with timestamped messages

**Rationale:** Users need to see what's happening during execution

**Priority:** Must Have

**Dependencies:** FR1.4

**Acceptance Criteria:**
- Log displays all status messages
- Each message has timestamp
- Messages have severity levels (info, warning, error)
- Auto-scrolls to latest message
- Log persists during execution

**Status:** ✅ Implemented

**Implementation:** `ui/panels/status_log_panel.py`

**Tests:** `tests/ui/test_status_log_panel.py`

---

### FR3.2: Capture Backend Screenshots
**Description:** System shall capture screenshots from backend execution

**Rationale:** Users need visual confirmation of automation actions

**Priority:** Should Have

**Dependencies:** FR1.4

**Acceptance Criteria:**
- Screenshots captured during execution
- Files saved to `_runtime/screenshots/`
- Filenames include timestamp and domain
- Screenshot watcher detects new files
- Graceful handling if no screenshots available

**Status:** ✅ Implemented

**Implementation:** `orchestrator/screenshot_watcher.py`

**Tests:** `tests/unit/test_screenshot_watcher.py`

---

### FR3.3: Display Frame Metadata
**Description:** System shall display metadata for captured screenshots

**Rationale:** Users need context about screenshot characteristics

**Priority:** Could Have

**Dependencies:** FR3.2

**Acceptance Criteria:**
- Metadata shows width, height, file size
- FPS calculated from frame timestamps
- Metadata updates with each new frame
- Handles missing or invalid frames gracefully

**Status:** ✅ Implemented

**Implementation:** `orchestrator/frame_analyzer.py`

**Tests:** `tests/unit/test_frame_analyzer.py`

---

### FR3.4: Update UI State
**Description:** System shall update UI state to reflect execution status

**Rationale:** Users need clear indication of system state

**Priority:** Must Have

**Dependencies:** FR1.4

**Acceptance Criteria:**
- Submit button disabled during execution
- Cancel button enabled during execution
- Status indicator shows busy/idle
- UI remains responsive during execution

**Status:** ✅ Implemented

**Implementation:** Event bus - `app_busy` signal

**Tests:** `tests/integration/test_ui_state.py`

---

## 6. FR4: Task History

### FR4.1: Persist Task History
**Description:** System shall persist all task executions to SQLite database

**Rationale:** Users need permanent record of executions

**Priority:** Must Have

**Dependencies:** FR1.4

**Acceptance Criteria:**
- Each task saved to database immediately after execution
- Database survives application restart
- No data loss on crashes
- Atomic transactions prevent corruption

**Status:** ✅ Implemented

**Implementation:** `ui/views/history_manager.py`

**Tests:** `tests/unit/test_history_manager.py`

---

### FR4.2: Display Task History
**Description:** System shall display list of all previous task executions

**Rationale:** Users need to review past executions

**Priority:** Must Have

**Dependencies:** FR4.1

**Acceptance Criteria:**
- History tab shows all tasks
- Table displays: description, status, timestamp
- Sorted by most recent first
- Loads within 1 second for <1000 tasks
- Updates automatically after new execution

**Status:** ✅ Implemented

**Implementation:** `ui/views/history_view.py`

**Tests:** `tests/ui/test_history_view.py`

---

### FR4.3: Search Task History
**Description:** System shall allow searching/filtering task history

**Rationale:** Users need to find specific past executions

**Priority:** Should Have

**Dependencies:** FR4.2

**Acceptance Criteria:**
- Search box filters by task description
- Results update in real-time as user types
- Clear search returns to full history
- Search is case-insensitive

**Status:** ✅ Implemented

**Implementation:** `ui/views/history_view.py` - `_filter_history()` method

**Tests:** `tests/ui/test_history_view.py::test_search`

---

### FR4.4: View Task Details
**Description:** System shall display detailed information for selected task

**Rationale:** Users need complete execution information for debugging

**Priority:** Must Have

**Dependencies:** FR4.2

**Acceptance Criteria:**
- Double-click task row shows details dialog
- Details include: full description, plan, outcome, timestamps
- Dialog is modal and closable
- Handles missing data gracefully

**Status:** ✅ Implemented

**Implementation:** `ui/views/history_view.py` - `format_task_details()` method

**Tests:** `tests/ui/test_history_view.py::test_details`

---

### FR4.5: Record Task Status
**Description:** System shall record task outcome (success/failure/cancelled)

**Rationale:** Users need to know execution results

**Priority:** Must Have

**Dependencies:** FR4.1

**Acceptance Criteria:**
- Status recorded: success, failure, cancelled
- Status visible in history table
- Status included in task details
- Status accurately reflects execution outcome

**Status:** ✅ Implemented

**Implementation:** `ui/views/history_manager.py` - status field

**Tests:** `tests/unit/test_history_manager.py::test_status`

---

## 7. FR5: Settings Management

### FR5.1: Configure API Key
**Description:** System shall allow user to configure Gemini API key via UI

**Rationale:** Users need easy way to set API credentials

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- Settings tab has API key input field
- Input is masked for security
- Save button persists to configuration
- Setting takes effect immediately
- No restart required

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py`

**Tests:** `tests/ui/test_settings_view.py`

---

### FR5.2: Configure Timeout Settings
**Description:** System shall allow user to configure timeout values

**Rationale:** Users need to adjust for network conditions

**Priority:** Should Have

**Dependencies:** None

**Acceptance Criteria:**
- Timeout setting in seconds
- Validation prevents negative values
- Default is sensible (30s)
- Setting persists across sessions

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py` - timeout_spin

**Tests:** `tests/ui/test_settings_view.py::test_timeout`

---

### FR5.3: Configure Retry Settings
**Description:** System shall allow user to configure retry count

**Rationale:** Users need to control retry behavior

**Priority:** Should Have

**Dependencies:** None

**Acceptance Criteria:**
- Retry count setting (0-10)
- Validation prevents negative values
- Default is sensible (3)
- Setting persists across sessions

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py` - retry_spin

**Tests:** `tests/ui/test_settings_view.py::test_retry`

---

### FR5.4: Set Domain Defaults
**Description:** System shall allow user to set default domain preference

**Rationale:** Users may prefer specific domain for most tasks

**Priority:** Could Have

**Dependencies:** FR1.5

**Acceptance Criteria:**
- Default domain setting
- Options: Auto-detect, Browser, Desktop
- Persists across sessions
- Can be overridden per-task

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py` - domain_default_combo

**Tests:** `tests/ui/test_settings_view.py::test_domain_default`

---

### FR5.5: Persist Settings
**Description:** System shall persist all settings across application restarts

**Rationale:** Users shouldn't reconfigure every time

**Priority:** Must Have

**Dependencies:** FR5.1, FR5.2, FR5.3, FR5.4, FR5.6

**Acceptance Criteria:**
- Settings saved to persistent storage
- Settings loaded on startup
- No data loss on crashes
- Settings file is human-readable (JSON/INI)

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py` - QSettings

**Tests:** `tests/ui/test_settings_view.py::test_persistence`

---

### FR5.6: Configure Frame Limits
**Description:** System shall allow user to configure frame capture limits

**Rationale:** Users need to control disk usage

**Priority:** Could Have

**Dependencies:** FR3.2

**Acceptance Criteria:**
- Max frames setting
- FPS limit setting
- Validation prevents invalid values
- Defaults prevent excessive storage

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py` - frame settings

**Tests:** `tests/ui/test_settings_view.py::test_frame_limits`

---

## 8. FR6: Startup and Mode Detection

### FR6.1: Support Live Gemini Mode
**Description:** System shall support live Gemini API mode with API key validation

**Rationale:** Production use requires real API integration

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- Detects GEMINI_API_KEY environment variable
- Validates API key on startup
- Uses live Gemini for planning
- Handles API failures gracefully

**Status:** ✅ Implemented

**Implementation:** `main.py` - `resolve_startup_config()`

**Tests:** `tests/integration/test_startup_modes.py::test_live_mode`

---

### FR6.2: Support Mock Mode
**Description:** System shall support offline mock mode for testing and demos

**Rationale:** Application must work without internet or API key

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- Detects GEMINI_MOCK=1 environment variable
- Activates mock mode automatically
- Deterministic planning without API
- All features work in mock mode

**Status:** ✅ Implemented

**Implementation:** `testing/gemini_mock/activator.py`

**Tests:** `tests/integration/test_startup_modes.py::test_mock_mode`

---

### FR6.3: Run Startup Preflight Checks
**Description:** System shall run preflight checks in live mode before allowing task submission

**Rationale:** Prevent wasted time on tasks that will fail

**Priority:** Should Have

**Dependencies:** FR6.1

**Acceptance Criteria:**
- Preflight checks API connectivity
- Timeout after 8 seconds
- Tests both MacroPlanner and CLI planner
- Blocks submission if checks fail

**Status:** ✅ Implemented

**Implementation:** `main.py` - `run_live_preflight()`

**Tests:** `tests/integration/test_startup_modes.py::test_preflight`

---

### FR6.4: Block Submission on Startup Failure
**Description:** System shall block task submission if startup checks fail

**Rationale:** Prevent tasks that will fail due to configuration

**Priority:** Should Have

**Dependencies:** FR6.3

**Acceptance Criteria:**
- Submit button disabled if checks fail
- Clear message explains why blocked
- User can fix configuration and retry
- Mock mode always allows submission

**Status:** ✅ Implemented

**Implementation:** `main.py` - `apply_startup_readiness()`

**Tests:** `tests/integration/test_startup_modes.py::test_blocked_submission`

---

### FR6.5: Display Startup Status
**Description:** System shall display clear startup status messages

**Rationale:** Users need to know system state immediately

**Priority:** Must Have

**Dependencies:** FR6.1, FR6.2, FR6.3

**Acceptance Criteria:**
- Status message shown in UI on startup
- Message indicates mode (live/mock)
- Message explains any blocks
- Message suggests corrective actions

**Status:** ✅ Implemented

**Implementation:** `main.py` - `StartupReadiness` dataclass

**Tests:** `tests/integration/test_startup_modes.py::test_status_messages`

---

### FR6.6: Load Configuration from .env
**Description:** System shall load configuration from module-local .env file

**Rationale:** Easy configuration without shell environment

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- Loads unified-app/.env on startup
- Does not override shell environment
- Supports GEMINI_API_KEY and GEMINI_MOCK
- Missing .env is not an error

**Status:** ✅ Implemented

**Implementation:** `main.py` - `_bootstrap_runtime_mode()`

**Tests:** `tests/integration/test_startup_modes.py::test_env_loading`

---

## 7. FR7: Automated Testing

### FR7.1: Unit Test Execution
**Description:** System shall support automated unit test execution for all core modules

**Rationale:** Enable autonomous testing of individual components in isolation

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- All unit tests executable via `pytest tests/unit/`
- Tests run without manual intervention
- Tests use mock mode (no external dependencies)
- Coverage report generated automatically
- Exit code indicates pass/fail status

**Status:** ✅ Implemented

**Implementation:** `tests/unit/` - 45 unit tests

**Tests:** Self-testing via pytest

---

### FR7.2: Integration Test Execution
**Description:** System shall support automated integration test execution for component interactions

**Rationale:** Enable autonomous testing of workflows and component integration

**Priority:** Must Have

**Dependencies:** FR7.1

**Acceptance Criteria:**
- All integration tests executable via `pytest tests/integration/`
- Tests run without manual intervention
- Tests use mock mode for external APIs
- Database tests use in-memory or temp databases
- Exit code indicates pass/fail status

**Status:** ✅ Implemented

**Implementation:** `tests/integration/` - 26 integration tests

**Tests:** Self-testing via pytest

---

### FR7.3: UI Test Execution
**Description:** System shall support automated UI component testing

**Rationale:** Enable autonomous testing of UI components without full application launch

**Priority:** Must Have

**Dependencies:** FR7.1

**Acceptance Criteria:**
- All UI tests executable via `pytest tests/ui/`
- Tests run without manual intervention
- Tests use PyQt6 test utilities
- No display server required (headless mode)
- Exit code indicates pass/fail status

**Status:** ✅ Implemented

**Implementation:** `tests/ui/` - 15 UI tests

**Tests:** Self-testing via pytest

---

### FR7.4: End-to-End Application Testing
**Description:** System shall support automated end-to-end testing with actual application launch

**Rationale:** Enable autonomous testing of complete user workflows with running UI

**Priority:** Should Have

**Dependencies:** FR7.1, FR7.2, FR7.3

**Acceptance Criteria:**
- Application can be launched programmatically
- UI interactions can be automated (button clicks, text entry)
- Application state can be verified programmatically
- Application can be closed programmatically
- Tests run in mock mode (no live API required)
- Screenshots can be captured for verification
- Exit code indicates pass/fail status

**Status:** ✅ Implemented

**Implementation:** `tests/integration/test_full_loop_integration.py`

**Tests:** Self-testing via pytest

---

### FR7.5: Test Coverage Measurement
**Description:** System shall automatically measure and report code coverage

**Rationale:** Enable autonomous verification of test completeness

**Priority:** Must Have

**Dependencies:** FR7.1, FR7.2, FR7.3

**Acceptance Criteria:**
- Coverage measured via `pytest --cov`
- HTML coverage report generated
- Terminal coverage summary displayed
- Missing lines identified
- Coverage percentage calculated
- Target threshold (85%) verified

**Status:** ✅ Implemented

**Implementation:** pytest-cov integration

**Tests:** Coverage reports generated on every test run

---

### FR7.6: Continuous Test Execution
**Description:** System shall support running all tests in a single command

**Rationale:** Enable autonomous full test suite execution

**Priority:** Must Have

**Dependencies:** FR7.1, FR7.2, FR7.3, FR7.4, FR7.5

**Acceptance Criteria:**
- Single command runs all tests: `pytest tests/ -v`
- Tests run in deterministic order
- All 86 tests execute
- Coverage report generated
- Execution completes in <5 minutes
- Exit code 0 if all pass, non-zero if any fail

**Status:** ✅ Implemented

**Implementation:** pytest configuration

**Tests:** `pytest tests/ -v --cov=orchestrator --cov=ui`

---

### FR7.7: Test Environment Setup
**Description:** System shall support automated test environment configuration

**Rationale:** Enable autonomous test execution without manual setup

**Priority:** Must Have

**Dependencies:** None

**Acceptance Criteria:**
- Mock mode activated via environment variable
- Test database created automatically (in-memory or temp)
- Temporary directories created for test files
- Environment cleaned up after tests
- No manual configuration required
- Tests isolated from production data

**Status:** ✅ Implemented

**Implementation:** pytest fixtures, `GEMINI_MOCK=1`

**Tests:** Fixture tests in conftest.py

---

### FR7.8: Test Result Reporting
**Description:** System shall generate comprehensive test result reports

**Rationale:** Enable autonomous verification of test outcomes

**Priority:** Should Have

**Dependencies:** FR7.6

**Acceptance Criteria:**
- Test results displayed in terminal
- Pass/fail status for each test
- Failure details with stack traces
- Execution time per test
- Summary statistics (total, passed, failed)
- HTML report available if needed

**Status:** ✅ Implemented

**Implementation:** pytest verbose output

**Tests:** pytest reporting

---

### FR7.9: Performance Test Execution
**Description:** System shall support automated performance testing

**Rationale:** Enable autonomous verification of performance requirements

**Priority:** Should Have

**Dependencies:** FR7.2

**Acceptance Criteria:**
- Performance tests executable via pytest
- Response times measured automatically
- Memory usage tracked
- Performance thresholds verified
- Results compared to targets
- Pass/fail based on threshold compliance

**Status:** ✅ Implemented

**Implementation:** `tests/integration/test_performance.py`

**Tests:** Performance benchmarks

---

### FR7.10: Error Handling Test Execution
**Description:** System shall support automated error scenario testing

**Rationale:** Enable autonomous verification of error handling and recovery

**Priority:** Must Have

**Dependencies:** FR7.2

**Acceptance Criteria:**
- Error scenarios tested automatically
- Network failures simulated
- Database errors simulated
- File system errors simulated
- API errors simulated
- Recovery verified programmatically

**Status:** ✅ Implemented

**Implementation:** `tests/integration/test_error_handling.py`

**Tests:** Error injection tests

---

## 9. Requirements Summary

| Category | Requirements | Implemented | In Progress | Pending |
|----------|--------------|-------------|-------------|---------|
| FR1: Task Submission | 5 | 5 | 0 | 0 |
| FR2: Execution Planning | 4 | 4 | 0 | 0 |
| FR3: Real-Time Monitoring | 4 | 4 | 0 | 0 |
| FR4: Task History | 5 | 5 | 0 | 0 |
| FR5: Settings Management | 6 | 6 | 0 | 0 |
| FR6: Startup and Mode Detection | 6 | 6 | 0 | 0 |
| FR7: Automated Testing | 10 | 10 | 0 | 0 |
| **Total** | **40** | **40** | **0** | **0** |

**Completion:** 100% (40/40 requirements implemented)

---

## 10. Traceability

### To User Stories
- FR1.* → US1.1, US1.2, US1.3
- FR2.* → US2.1, US2.2, US2.4
- FR3.* → US2.2, US2.3, US3.1
- FR4.* → US3.1, US3.2, US3.3, US3.4
- FR5.* → US4.1, US4.2, US4.3, US4.4
- FR6.* → US5.2, US5.3
- FR7.* → US6.2, US7.1

### To Use Cases
- FR1.* → UC-001, UC-006
- FR2.* → UC-001, UC-002
- FR3.* → UC-002, UC-007
- FR4.* → UC-003
- FR5.* → UC-004
- FR6.* → UC-005
- FR7.* → All use cases (testing validates all functionality)

### To Implementation
See individual requirement Implementation fields for file paths

### To Tests
See individual requirement Tests fields for test file paths

---

## References

- User Stories: `../02-user/user-stories.md`
- Use Cases: `../02-user/use-cases.md`
- Feature Specifications: `feature-specifications.md`
- Acceptance Criteria: `acceptance-criteria.md`
- Traceability Matrix: `../10-project/traceability-matrix.md`
