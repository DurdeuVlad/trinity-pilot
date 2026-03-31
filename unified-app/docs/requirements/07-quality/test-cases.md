# Test Cases - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** QA-002  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines detailed test cases for the Orchestrator Desktop App, providing step-by-step test procedures and expected results.

---

## 2. Test Case Template

Each test case includes:
- **TC ID:** Unique identifier
- **Name:** Descriptive test name
- **Category:** Test type
- **Priority:** Critical / High / Medium / Low
- **Requirements:** Related requirements
- **Preconditions:** Setup needed
- **Steps:** Test procedure
- **Expected Result:** What should happen
- **Actual Result:** What happened (filled during execution)
- **Status:** Pass / Fail / Not Run

---

## 3. Functional Test Cases

### TC-F001: Submit Valid Task
**Category:** Functional - Task Submission  
**Priority:** Critical  
**Requirements:** FR1.1, FR1.2, FR1.4

**Preconditions:**
- Application running in mock mode
- No task currently executing

**Steps:**
1. Enter task description: "Open Google and search for Python"
2. Select domain: "Browser"
3. Click "Run Task" button
4. Observe execution

**Expected Result:**
- Submit button disables
- Cancel button enables
- Plan appears in execution plan panel
- Steps execute sequentially
- Status log shows progress
- Task completes successfully
- Submit button re-enables

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_full_loop_integration.py::test_complete_flow`

---

### TC-F002: Reject Empty Task
**Category:** Functional - Input Validation  
**Priority:** Critical  
**Requirements:** FR1.2

**Preconditions:**
- Application running

**Steps:**
1. Leave task description empty
2. Click "Run Task" button

**Expected Result:**
- Validation error displayed: "Task description cannot be empty"
- Task not submitted
- Submit button remains enabled

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_task_input_panel.py::test_empty_input`

---

### TC-F003: Cancel Running Task
**Category:** Functional - Task Cancellation  
**Priority:** High  
**Requirements:** FR1.3

**Preconditions:**
- Task is currently executing

**Steps:**
1. Submit a task
2. During execution, click "Cancel" button
3. Observe cancellation

**Expected Result:**
- Execution stops within 2 seconds
- Status log shows "Task cancelled by user"
- History records task as "cancelled"
- Submit button re-enables

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_orchestrator_core.py::test_cancel`

---

### TC-F004: Generate Execution Plan
**Category:** Functional - Planning  
**Priority:** Critical  
**Requirements:** FR2.1, FR2.2

**Preconditions:**
- Application running in mock mode

**Steps:**
1. Submit task: "Open browser"
2. Observe plan generation

**Expected Result:**
- Plan appears before execution starts
- Plan contains ≥1 numbered steps
- Each step has description
- Plan displayed in execution plan panel

**Actual Result:** ✅ Pass

**Test File:** `tests/unit/test_macro_planner.py::test_generate_plan`

---

### TC-F005: Update Step Status
**Category:** Functional - Execution Monitoring  
**Priority:** High  
**Requirements:** FR2.3

**Preconditions:**
- Task executing with multiple steps

**Steps:**
1. Submit multi-step task
2. Observe step status changes

**Expected Result:**
- Steps start as "pending" (gray)
- Current step shows "running" (blue)
- Completed steps show "completed" (green)
- Failed steps show "failed" (red)

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_orchestrator_core.py::test_step_status`

---

### TC-F006: Display Status Log
**Category:** Functional - Monitoring  
**Priority:** High  
**Requirements:** FR3.1

**Preconditions:**
- Task executing

**Steps:**
1. Submit task
2. Observe status log panel

**Expected Result:**
- All messages appear in log
- Timestamps present and accurate
- Severity levels visible (info/warning/error)
- Auto-scrolls to latest
- Log persists during execution

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_status_log_panel.py::test_logging`

---

### TC-F007: Capture and Display Screenshot
**Category:** Functional - Glass Box View  
**Priority:** Medium  
**Requirements:** FR3.2, FR3.3

**Preconditions:**
- Task executing with screenshot generation

**Steps:**
1. Submit task that generates screenshots
2. Observe glass box panel

**Expected Result:**
- Screenshots appear in glass box panel
- Metadata shows width, height, size
- FPS calculated and displayed
- Updates with each new frame

**Actual Result:** ✅ Pass

**Test File:** `tests/unit/test_screenshot_watcher.py`, `tests/unit/test_frame_analyzer.py`

---

### TC-F008: Persist Task to History
**Category:** Functional - History  
**Priority:** Critical  
**Requirements:** FR4.1

**Preconditions:**
- Task completed

**Steps:**
1. Execute task
2. Query history database
3. Restart application
4. Check history

**Expected Result:**
- Task saved to database immediately
- Record survives app restart
- All fields populated correctly
- No data loss

**Actual Result:** ✅ Pass

**Test File:** `tests/unit/test_history_manager.py::test_persistence`

---

### TC-F009: Display Task History
**Category:** Functional - History  
**Priority:** High  
**Requirements:** FR4.2

**Preconditions:**
- Multiple tasks in history

**Steps:**
1. Switch to History tab
2. Observe task list

**Expected Result:**
- All tasks visible
- Sorted by most recent first
- Columns: description, status, timestamp
- Loads within 1 second

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_history_view.py::test_display`

---

### TC-F010: Search Task History
**Category:** Functional - History  
**Priority:** Medium  
**Requirements:** FR4.3

**Preconditions:**
- Multiple tasks in history

**Steps:**
1. Switch to History tab
2. Enter search term in search box
3. Observe filtered results

**Expected Result:**
- Only matching tasks shown
- Search is case-insensitive
- Results update in real-time
- Clear search shows all

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_history_view.py::test_search`

---

### TC-F011: View Task Details
**Category:** Functional - History  
**Priority:** Medium  
**Requirements:** FR4.4

**Preconditions:**
- Tasks in history

**Steps:**
1. Switch to History tab
2. Double-click a task row
3. Observe details dialog

**Expected Result:**
- Dialog displays full description
- Shows execution plan
- Shows outcome and timestamps
- Dialog is closable

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_history_view.py::test_details`

---

### TC-F012: Configure API Key
**Category:** Functional - Settings  
**Priority:** High  
**Requirements:** FR5.1

**Preconditions:**
- Application running

**Steps:**
1. Switch to Settings tab
2. Enter API key in masked input
3. Click "Save Settings"
4. Restart application
5. Check settings

**Expected Result:**
- Key saved to QSettings
- Key persists across restarts
- Input is masked for security
- Takes effect immediately

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_settings_view.py::test_api_key`

---

### TC-F013: Validate Timeout Setting
**Category:** Functional - Settings  
**Priority:** Medium  
**Requirements:** FR5.2

**Preconditions:**
- Settings tab open

**Steps:**
1. Set timeout to 60 seconds
2. Click "Save Settings"
3. Set timeout to -1
4. Click "Save Settings"
5. Set timeout to 500
6. Click "Save Settings"

**Expected Result:**
- Valid timeout (60) saved
- Negative timeout rejected with error
- Too large timeout (500) rejected with error
- Settings persist

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_settings_view.py::test_timeout`

---

### TC-F014: Startup in Mock Mode
**Category:** Functional - Startup  
**Priority:** Critical  
**Requirements:** FR6.2

**Preconditions:**
- GEMINI_MOCK=1 set

**Steps:**
1. Launch application
2. Observe startup message

**Expected Result:**
- Status message: "Startup mode: mock fallback ready"
- Task submission enabled
- No API calls made
- Deterministic planning

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_startup_modes.py::test_mock_mode`

---

### TC-F015: Startup Preflight Checks
**Category:** Functional - Startup  
**Priority:** High  
**Requirements:** FR6.3

**Preconditions:**
- Valid API key set
- GEMINI_MOCK not set

**Steps:**
1. Launch application
2. Observe preflight execution

**Expected Result:**
- Preflight completes within 8 seconds
- Tests MacroPlanner connectivity
- Tests CLI planner connectivity
- Results determine submission state

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_startup_modes.py::test_preflight`

---

## 4. Non-Functional Test Cases

### TC-NF001: UI Response Time
**Category:** Performance  
**Priority:** High  
**Requirements:** NFR-P1.1

**Preconditions:**
- Application running

**Steps:**
1. Click buttons
2. Enter text
3. Switch tabs
4. Measure response time

**Expected Result:**
- All interactions respond within 100ms
- No freezing or lag
- UI remains responsive

**Actual Result:** ✅ Pass (<50ms typical)

**Test File:** Manual testing

---

### TC-NF002: History Load Performance
**Category:** Performance  
**Priority:** Medium  
**Requirements:** NFR-P2.1

**Preconditions:**
- 1000 tasks in history database

**Steps:**
1. Switch to History tab
2. Measure load time

**Expected Result:**
- History loads within 1 second
- UI remains responsive
- All tasks displayed

**Actual Result:** ✅ Pass (<500ms)

**Test File:** `tests/integration/test_performance.py`

---

### TC-NF003: Memory Usage
**Category:** Performance  
**Priority:** Medium  
**Requirements:** NFR-P6.1, NFR-P6.2

**Preconditions:**
- Application running

**Steps:**
1. Launch application
2. Measure idle memory
3. Execute 10 tasks
4. Measure peak memory

**Expected Result:**
- Idle: <200MB
- Peak: <500MB
- No memory leaks

**Actual Result:** ✅ Pass (~150MB idle, ~250MB peak)

**Test File:** Manual testing with Task Manager

---

### TC-NF004: Error Recovery
**Category:** Reliability  
**Priority:** Critical  
**Requirements:** NFR-R2.4

**Preconditions:**
- Application running

**Steps:**
1. Trigger various errors (network, database, file system)
2. Observe recovery

**Expected Result:**
- Application recovers without restart
- No data loss
- Clear error messages
- UI returns to ready state

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_error_handling.py`

---

### TC-NF005: Data Integrity on Crash
**Category:** Reliability  
**Priority:** Critical  
**Requirements:** NFR-R4.1

**Preconditions:**
- Task executing

**Steps:**
1. Submit task
2. Force kill application during execution
3. Restart application
4. Check history database

**Expected Result:**
- Database not corrupted
- Previous tasks intact
- Can continue using application

**Actual Result:** ✅ Pass

**Test File:** Manual testing

---

### TC-NF006: First-Time User Experience
**Category:** Usability  
**Priority:** High  
**Requirements:** NFR-U2.1

**Preconditions:**
- Fresh installation

**Steps:**
1. Launch application
2. Submit first task
3. Measure time to completion

**Expected Result:**
- User can run first task within 5 minutes
- UI is intuitive
- No training required

**Actual Result:** ✅ Pass (~3 minutes)

**Test File:** Manual testing

---

### TC-NF007: Code Coverage
**Category:** Maintainability  
**Priority:** Critical  
**Requirements:** NFR-M1.1

**Preconditions:**
- Test suite complete

**Steps:**
1. Run pytest with coverage
2. Check coverage report

**Expected Result:**
- Overall coverage ≥85%
- orchestrator module ≥85%
- ui module ≥85%

**Actual Result:** ✅ Pass (86% overall)

**Test File:** All tests

**Command:** `pytest tests/ -v --cov=orchestrator --cov=ui`

---

## 5. Integration Test Cases

### TC-I001: Full Task Execution Flow
**Category:** Integration  
**Priority:** Critical  
**Requirements:** Multiple

**Preconditions:**
- Application running in mock mode

**Steps:**
1. Submit task
2. Observe plan generation
3. Observe step execution
4. Observe completion
5. Check history

**Expected Result:**
- Task submitted → plan generated → steps execute → completion → saved to history
- All events fire correctly
- All components communicate properly

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_full_loop_integration.py`

---

### TC-I002: Event Bus Communication
**Category:** Integration  
**Priority:** High  
**Requirements:** Event-driven architecture

**Preconditions:**
- Event bus initialized

**Steps:**
1. Emit various events
2. Verify listeners receive events
3. Check event ordering

**Expected Result:**
- All events received by listeners
- Events processed in order
- No lost events

**Actual Result:** ✅ Pass

**Test File:** `tests/unit/test_event_bus.py`

---

### TC-I003: Database Persistence
**Category:** Integration  
**Priority:** Critical  
**Requirements:** FR4.1

**Preconditions:**
- Database accessible

**Steps:**
1. Save task to database
2. Query database
3. Restart application
4. Query again

**Expected Result:**
- Task saved successfully
- Query returns correct data
- Data survives restart

**Actual Result:** ✅ Pass

**Test File:** `tests/unit/test_history_manager.py`

---

## 6. Edge Case Test Cases

### TC-E001: Empty Task Input
**Category:** Edge Case  
**Priority:** High  
**Requirements:** FR1.2

**Steps:**
1. Submit empty task
2. Submit whitespace-only task

**Expected Result:**
- Both rejected with validation error
- Clear error message

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_task_input_panel.py::test_empty_input`

---

### TC-E002: Maximum Length Task
**Category:** Edge Case  
**Priority:** Medium  
**Requirements:** FR1.2

**Steps:**
1. Submit task with exactly 1000 characters
2. Submit task with 1001 characters

**Expected Result:**
- 1000 chars accepted
- 1001 chars rejected

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_task_input_panel.py::test_oversized_input`

---

### TC-E003: Special Characters
**Category:** Edge Case  
**Priority:** Medium  
**Requirements:** FR1.1

**Steps:**
1. Submit task with emojis, unicode, special symbols

**Expected Result:**
- All UTF-8 characters accepted
- Display correctly
- No corruption

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_task_input_panel.py`

---

### TC-E004: Empty History
**Category:** Edge Case  
**Priority:** Low  
**Requirements:** FR4.2

**Steps:**
1. Open History tab with no tasks

**Expected Result:**
- "No tasks in history" message
- No errors
- UI functional

**Actual Result:** ✅ Pass

**Test File:** `tests/ui/test_history_view.py`

---

### TC-E005: Large History
**Category:** Edge Case  
**Priority:** Medium  
**Requirements:** NFR-P2.1

**Steps:**
1. Create 1000 tasks in database
2. Load history

**Expected Result:**
- Loads within 1 second
- UI responsive
- All tasks displayed

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_performance.py`

---

## 7. Error Handling Test Cases

### TC-ERR001: Network Failure
**Category:** Error Handling  
**Priority:** High  
**Requirements:** NFR-R3.1

**Steps:**
1. Simulate network unavailable
2. Submit task in live mode

**Expected Result:**
- Error detected
- Clear error message
- Suggest mock mode
- No crash

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_error_handling.py`

---

### TC-ERR002: Database Locked
**Category:** Error Handling  
**Priority:** Medium  
**Requirements:** NFR-R3.3

**Steps:**
1. Lock database
2. Attempt to save task

**Expected Result:**
- Retry with backoff
- Eventually succeed or show error
- No data corruption

**Actual Result:** ✅ Pass

**Test File:** `tests/unit/test_history_manager.py`

---

### TC-ERR003: Invalid API Key
**Category:** Error Handling  
**Priority:** High  
**Requirements:** NFR-R3.4

**Steps:**
1. Set invalid API key
2. Launch application

**Expected Result:**
- Preflight detects invalid key
- Block submission
- Clear error message
- Suggest fix

**Actual Result:** ✅ Pass

**Test File:** `tests/integration/test_startup_modes.py`

---

## 8. Test Case Summary

| Category | Total Cases | Passed | Failed | Not Run |
|----------|-------------|--------|--------|---------|
| Functional | 15 | 15 | 0 | 0 |
| Non-Functional | 7 | 7 | 0 | 0 |
| Integration | 3 | 3 | 0 | 0 |
| Edge Cases | 5 | 5 | 0 | 0 |
| Error Handling | 3 | 3 | 0 | 0 |
| **Total** | **33** | **33** | **0** | **0** |

**Pass Rate:** 100%

---

## 9. Test Execution Log

**Date:** 2026-03-14  
**Tester:** Automated test suite  
**Environment:** Windows 11, Python 3.10, Mock Mode  
**Results:** All tests passing

---

## References

- Test Strategy: `test-strategy.md`
- Quality Metrics: `quality-metrics.md`
- Acceptance Criteria: `../03-functional/acceptance-criteria.md`
- Edge Cases: `../03-functional/edge-cases.md`
- Test Code: `../../tests/`
