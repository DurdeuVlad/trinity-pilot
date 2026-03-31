# Acceptance Criteria - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** FUN-003  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines testable acceptance criteria for all functional requirements, establishing clear pass/fail conditions for verification and validation.

---

## 2. Criteria Format

Each acceptance criterion follows this structure:
- **AC ID:** Unique identifier
- **Requirement:** Related functional requirement
- **Criterion:** Testable condition
- **Test Method:** How to verify
- **Pass Condition:** What constitutes success
- **Status:** Verified / Pending

---

## 3. AC1: Task Submission Criteria

### AC1.1: Accept Valid Task Input
**Requirement:** FR1.1  
**Criterion:** System accepts task descriptions between 1-1000 characters

**Test Method:**
1. Enter task description with 1 character
2. Enter task description with 500 characters
3. Enter task description with 1000 characters
4. Click "Run Task"

**Pass Condition:**
- All inputs accepted without error
- Task submission proceeds normally

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_task_input_panel.py::test_valid_input`

---

### AC1.2: Reject Empty Input
**Requirement:** FR1.2  
**Criterion:** System rejects empty or whitespace-only task descriptions

**Test Method:**
1. Leave task input empty, click "Run Task"
2. Enter only spaces, click "Run Task"
3. Enter only tabs/newlines, click "Run Task"

**Pass Condition:**
- Validation error displayed: "Task description cannot be empty"
- Task submission does not proceed
- Submit button remains enabled for retry

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_task_input_panel.py::test_empty_input`

---

### AC1.3: Reject Oversized Input
**Requirement:** FR1.2  
**Criterion:** System rejects task descriptions exceeding 1000 characters

**Test Method:**
1. Enter task description with 1001 characters
2. Click "Run Task"

**Pass Condition:**
- Validation error displayed
- Task submission does not proceed

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_task_input_panel.py::test_oversized_input`

---

### AC1.4: Prevent Duplicate Submission
**Requirement:** FR1.2  
**Criterion:** System prevents submitting new task while one is executing

**Test Method:**
1. Submit task A
2. While task A is executing, attempt to submit task B

**Pass Condition:**
- Submit button is disabled during execution
- Warning message: "Task already in progress"
- Task B is not submitted

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_task_submission.py::test_duplicate_prevention`

---

### AC1.5: Enable Task Cancellation
**Requirement:** FR1.3  
**Criterion:** User can cancel task during execution

**Test Method:**
1. Submit task
2. During execution, click "Cancel" button
3. Observe orchestrator stops

**Pass Condition:**
- Execution stops within 2 seconds
- Status log shows "Task cancelled by user"
- History records task as "cancelled"
- UI returns to ready state

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_orchestrator_core.py::test_cancel`

---

### AC1.6: Execute Task Successfully
**Requirement:** FR1.4  
**Criterion:** System executes valid task from submission to completion

**Test Method:**
1. Submit valid task in mock mode
2. Observe execution through all steps
3. Verify completion

**Pass Condition:**
- Plan generated and displayed
- All steps execute sequentially
- Status log shows progress
- Task completes successfully
- History records success

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_full_loop_integration.py::test_complete_flow`

---

### AC1.7: Support Domain Selection
**Requirement:** FR1.5  
**Criterion:** User can select task domain and it's passed to orchestrator

**Test Method:**
1. Select "Browser" from domain dropdown
2. Submit task
3. Verify domain passed to orchestrator

**Pass Condition:**
- Domain selection persists during session
- Orchestrator receives correct domain value
- Task executes with selected domain

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_task_input_panel.py::test_domain_selection`

---

## 4. AC2: Execution Planning Criteria

### AC2.1: Generate Valid Plan
**Requirement:** FR2.1  
**Criterion:** System generates execution plan with numbered steps

**Test Method:**
1. Submit task in mock mode
2. Observe plan generation

**Pass Condition:**
- Plan appears before execution starts
- Plan contains ≥1 numbered steps
- Each step has description
- Plan structure is valid

**Status:** ✅ Verified

**Test Reference:** `tests/unit/test_macro_planner.py::test_generate_plan`

---

### AC2.2: Display Plan in UI
**Requirement:** FR2.2  
**Criterion:** Execution plan displays in UI with clear formatting

**Test Method:**
1. Generate plan
2. Verify display in ExecutionPlanPanel

**Pass Condition:**
- Plan visible in UI
- Steps numbered sequentially
- Descriptions readable
- Panel updates in real-time

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_execution_plan_panel.py::test_display_plan`

---

### AC2.3: Update Step Status
**Requirement:** FR2.3  
**Criterion:** Step status updates in real-time during execution

**Test Method:**
1. Execute task with multiple steps
2. Observe status changes

**Pass Condition:**
- Steps start as "pending"
- Current step shows "running"
- Completed steps show "completed"
- Failed steps show "failed"
- Visual indicators clear

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_orchestrator_core.py::test_step_status`

---

### AC2.4: Fallback to Mock Mode
**Requirement:** FR2.4  
**Criterion:** System uses mock planner when API unavailable

**Test Method:**
1. Set `GEMINI_MOCK=1`
2. Submit task
3. Verify mock planner used

**Pass Condition:**
- Plan generated without API call
- Deterministic plan structure
- Status log indicates mock mode
- Execution proceeds normally

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_mock_mode.py::test_fallback`

---

## 5. AC3: Real-Time Monitoring Criteria

### AC3.1: Display Status Log
**Requirement:** FR3.1  
**Criterion:** Status log displays timestamped messages with severity

**Test Method:**
1. Execute task
2. Observe status log

**Pass Condition:**
- All messages appear in log
- Timestamps present and accurate
- Severity levels visible (info/warning/error)
- Auto-scrolls to latest
- Log persists during execution

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_status_log_panel.py::test_logging`

---

### AC3.2: Capture Screenshots
**Requirement:** FR3.2  
**Criterion:** System captures and detects backend screenshots

**Test Method:**
1. Execute task that generates screenshots
2. Verify screenshot detection

**Pass Condition:**
- Screenshots saved to `_runtime/screenshots/`
- ScreenshotWatcher detects new files
- `frame_captured` event emitted
- Files have correct naming pattern

**Status:** ✅ Verified

**Test Reference:** `tests/unit/test_screenshot_watcher.py::test_detection`

---

### AC3.3: Display Frame Metadata
**Requirement:** FR3.3  
**Criterion:** Screenshot metadata displayed accurately

**Test Method:**
1. Capture screenshot
2. Verify metadata extraction and display

**Pass Condition:**
- Width and height correct
- File size accurate
- FPS calculated from timestamps
- Metadata updates with new frames

**Status:** ✅ Verified

**Test Reference:** `tests/unit/test_frame_analyzer.py::test_metadata`

---

### AC3.4: Maintain UI Responsiveness
**Requirement:** FR3.4  
**Criterion:** UI remains responsive during task execution

**Test Method:**
1. Execute long-running task
2. Interact with UI during execution

**Pass Condition:**
- UI responds to clicks within 100ms
- No freezing or blocking
- Can switch tabs during execution
- Can cancel task at any time

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_ui_responsiveness.py::test_async_execution`

---

## 6. AC4: Task History Criteria

### AC4.1: Persist Task Data
**Requirement:** FR4.1  
**Criterion:** All tasks saved to database immediately after execution

**Test Method:**
1. Execute task
2. Query database
3. Verify record exists

**Pass Condition:**
- Task record in database
- All fields populated correctly
- Record survives app restart
- No data loss on crash

**Status:** ✅ Verified

**Test Reference:** `tests/unit/test_history_manager.py::test_persistence`

---

### AC4.2: Display History List
**Requirement:** FR4.2  
**Criterion:** History tab shows all tasks sorted by most recent

**Test Method:**
1. Execute 3 tasks
2. Switch to History tab
3. Verify display

**Pass Condition:**
- All 3 tasks visible
- Sorted newest first
- Columns: description, status, timestamp
- Loads within 1 second

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_history_view.py::test_display`

---

### AC4.3: Search History
**Requirement:** FR4.3  
**Criterion:** Search filters history by description

**Test Method:**
1. Create tasks with different descriptions
2. Enter search term
3. Verify filtering

**Pass Condition:**
- Only matching tasks shown
- Search is case-insensitive
- Results update in real-time
- Clear search shows all

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_history_view.py::test_search`

---

### AC4.4: View Task Details
**Requirement:** FR4.4  
**Criterion:** Double-click shows full task details

**Test Method:**
1. Double-click task row
2. Verify details dialog

**Pass Condition:**
- Dialog displays full description
- Shows execution plan
- Shows outcome and timestamps
- Dialog is closable

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_history_view.py::test_details`

---

### AC4.5: Record Task Status
**Requirement:** FR4.5  
**Criterion:** Task status accurately reflects execution outcome

**Test Method:**
1. Execute successful task
2. Execute failed task
3. Cancel task
4. Verify status in history

**Pass Condition:**
- Success task shows "success"
- Failed task shows "failure"
- Cancelled task shows "cancelled"
- Status visible in table and details

**Status:** ✅ Verified

**Test Reference:** `tests/unit/test_history_manager.py::test_status`

---

## 7. AC5: Settings Management Criteria

### AC5.1: Configure API Key
**Requirement:** FR5.1  
**Criterion:** User can set API key via settings UI

**Test Method:**
1. Open Settings tab
2. Enter API key
3. Click Save
4. Restart app
5. Verify key persisted

**Pass Condition:**
- Key saved to QSettings
- Key persists across restarts
- Input is masked for security
- Takes effect immediately

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_settings_view.py::test_api_key`

---

### AC5.2: Configure Timeout
**Requirement:** FR5.2  
**Criterion:** User can set timeout value with validation

**Test Method:**
1. Set timeout to 60 seconds
2. Save settings
3. Attempt negative timeout
4. Attempt timeout > 300

**Pass Condition:**
- Valid timeout saved
- Negative rejected with error
- Too large rejected with error
- Setting persists

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_settings_view.py::test_timeout`

---

### AC5.3: Configure Retry Count
**Requirement:** FR5.3  
**Criterion:** User can set retry count with validation

**Test Method:**
1. Set retry to 5
2. Save settings
3. Attempt negative retry
4. Attempt retry > 10

**Pass Condition:**
- Valid retry saved
- Negative rejected
- Too large rejected
- Setting persists

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_settings_view.py::test_retry`

---

### AC5.4: Set Domain Default
**Requirement:** FR5.4  
**Criterion:** User can set default domain preference

**Test Method:**
1. Set default to "Browser"
2. Save settings
3. Submit new task
4. Verify domain pre-selected

**Pass Condition:**
- Default saved
- Pre-selected on task submission
- Can be overridden per-task
- Persists across sessions

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_settings_view.py::test_domain_default`

---

### AC5.5: Persist All Settings
**Requirement:** FR5.5  
**Criterion:** All settings persist across application restarts

**Test Method:**
1. Configure all settings
2. Save
3. Close app
4. Restart app
5. Verify all settings retained

**Pass Condition:**
- All settings loaded correctly
- No data loss
- Settings file readable
- No corruption

**Status:** ✅ Verified

**Test Reference:** `tests/test_settings_persistence.py::test_full_persistence`

---

### AC5.6: Configure Frame Limits
**Requirement:** FR5.6  
**Criterion:** User can set frame capture limits

**Test Method:**
1. Set max frames to 100
2. Set FPS limit to 30
3. Save settings

**Pass Condition:**
- Settings saved
- Validation prevents invalid values
- Limits applied during execution

**Status:** ✅ Verified

**Test Reference:** `tests/ui/test_settings_view.py::test_frame_limits`

---

## 8. AC6: Startup Mode Criteria

### AC6.1: Support Live Mode
**Requirement:** FR6.1  
**Criterion:** System operates in live mode with valid API key

**Test Method:**
1. Set valid `GEMINI_API_KEY`
2. Unset `GEMINI_MOCK`
3. Start application
4. Verify live mode active

**Pass Condition:**
- Startup message: "live Gemini ready"
- Preflight checks pass
- Task submission enabled
- Live API used for planning

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_startup_modes.py::test_live_mode`

---

### AC6.2: Support Mock Mode
**Requirement:** FR6.2  
**Criterion:** System operates in mock mode when GEMINI_MOCK=1

**Test Method:**
1. Set `GEMINI_MOCK=1`
2. Start application
3. Submit task

**Pass Condition:**
- Startup message: "mock fallback ready"
- No API calls made
- Task submission enabled
- Deterministic planning

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_startup_modes.py::test_mock_mode`

---

### AC6.3: Run Preflight Checks
**Requirement:** FR6.3  
**Criterion:** Startup preflight validates API connectivity in live mode

**Test Method:**
1. Set valid API key
2. Start application
3. Observe preflight execution

**Pass Condition:**
- Preflight completes within 8 seconds
- Tests MacroPlanner connectivity
- Tests CLI planner connectivity
- Results determine submission state

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_startup_modes.py::test_preflight`

---

### AC6.4: Block on Startup Failure
**Requirement:** FR6.4  
**Criterion:** Task submission blocked if startup checks fail

**Test Method:**
1. Set invalid API key
2. Start application
3. Attempt task submission

**Pass Condition:**
- Submit button disabled
- Clear error message displayed
- Suggests corrective action
- Mock mode still allows submission

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_startup_modes.py::test_blocked_submission`

---

### AC6.5: Display Startup Status
**Requirement:** FR6.5  
**Criterion:** Clear startup status message shown to user

**Test Method:**
1. Start in various modes
2. Verify status messages

**Pass Condition:**
- Mock mode: "mock fallback ready"
- Live success: "live Gemini ready"
- Live blocked: Actionable error message
- Message visible in status log

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_startup_modes.py::test_status_messages`

---

### AC6.6: Load .env Configuration
**Requirement:** FR6.6  
**Criterion:** System loads module-local .env file on startup

**Test Method:**
1. Create unified-app/.env with settings
2. Start application
3. Verify settings loaded

**Pass Condition:**
- .env file read successfully
- Settings applied
- Shell environment not overridden
- Missing .env not an error

**Status:** ✅ Verified

**Test Reference:** `tests/integration/test_startup_modes.py::test_env_loading`

---

## 9. Acceptance Criteria Summary

| Category | Total Criteria | Verified | Pending |
|----------|----------------|----------|---------|
| AC1: Task Submission | 7 | 7 | 0 |
| AC2: Execution Planning | 4 | 4 | 0 |
| AC3: Real-Time Monitoring | 4 | 4 | 0 |
| AC4: Task History | 5 | 5 | 0 |
| AC5: Settings Management | 6 | 6 | 0 |
| AC6: Startup Mode | 6 | 6 | 0 |
| **Total** | **32** | **32** | **0** |

**Verification Status:** 100% (32/32 criteria verified)

---

## 10. Verification Methods

### Automated Testing
- Unit tests: 45 tests
- Integration tests: 26 tests
- UI tests: 15 tests
- **Total:** 86 tests, all passing

### Manual Testing
- Demo execution: ✅ Passed
- User acceptance: ✅ Passed
- Academic review: ✅ Passed

### Coverage
- Code coverage: 86% (target: ≥85%)
- Requirements coverage: 100% (32/32 criteria)
- Test coverage: 100% (all criteria have tests)

---

## References

- Functional Requirements: `functional-requirements.md`
- Feature Specifications: `feature-specifications.md`
- Test Strategy: `../07-quality/test-strategy.md`
- Test Cases: `../07-quality/test-cases.md`
