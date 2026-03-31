# Edge Cases - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** FUN-004  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document catalogs edge cases, boundary conditions, and exceptional scenarios for the Orchestrator Desktop App, ensuring robust handling of unusual or extreme situations.

---

## 2. Edge Case Format

Each edge case includes:
- **EC ID:** Unique identifier
- **Category:** Feature area
- **Scenario:** Description of edge case
- **Expected Behavior:** How system should handle it
- **Actual Behavior:** Current implementation
- **Risk Level:** Low / Medium / High
- **Status:** Handled / Partial / Not Handled

---

## 3. EC1: Input Validation Edge Cases

### EC1.1: Empty Task Description
**Category:** Task Submission  
**Scenario:** User submits task with empty or whitespace-only description

**Expected Behavior:**
- Validation error displayed
- Submission blocked
- Clear error message

**Actual Behavior:**
- ✅ Validation catches empty input
- ✅ Shows "Task description cannot be empty"
- ✅ Submit button remains enabled for retry

**Risk Level:** Low  
**Status:** ✅ Handled

**Implementation:** `ui/panels/task_input_panel.py::_validate_input()`

---

### EC1.2: Maximum Length Input
**Category:** Task Submission  
**Scenario:** User enters exactly 1000 characters (boundary)

**Expected Behavior:**
- Input accepted
- No truncation
- Submission proceeds

**Actual Behavior:**
- ✅ Accepts 1000 characters
- ✅ No validation error
- ✅ Full text preserved

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC1.3: Oversized Input
**Category:** Task Submission  
**Scenario:** User enters 1001+ characters

**Expected Behavior:**
- Validation error
- Submission blocked
- Suggest shortening

**Actual Behavior:**
- ✅ Validation catches oversized input
- ✅ Error message displayed
- ✅ Submission blocked

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC1.4: Special Characters in Task
**Category:** Task Submission  
**Scenario:** Task contains emojis, unicode, special symbols

**Expected Behavior:**
- Accept all UTF-8 characters
- Display correctly in UI
- Pass to orchestrator without corruption

**Actual Behavior:**
- ✅ UTF-8 fully supported
- ✅ Displays correctly
- ✅ No character corruption

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC1.5: SQL Injection Attempt
**Category:** Task Submission / History  
**Scenario:** Task description contains SQL injection patterns

**Expected Behavior:**
- Input accepted (it's just text)
- Parameterized queries prevent injection
- No database corruption

**Actual Behavior:**
- ✅ SQLite parameterized queries used
- ✅ No SQL injection possible
- ✅ Text stored safely

**Risk Level:** Low  
**Status:** ✅ Handled

**Implementation:** `ui/views/history_manager.py` uses parameterized queries

---

## 4. EC2: Execution Edge Cases

### EC2.1: Rapid Task Submission
**Category:** Task Execution  
**Scenario:** User clicks "Run Task" multiple times rapidly

**Expected Behavior:**
- Only first click processed
- Subsequent clicks ignored
- No duplicate submissions

**Actual Behavior:**
- ✅ Submit button disabled after first click
- ✅ Duplicate submissions prevented
- ✅ Warning message if attempted

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC2.2: Task Cancellation During Planning
**Category:** Task Execution  
**Scenario:** User cancels while plan is being generated

**Expected Behavior:**
- Planning stops
- No execution starts
- Clean state recovery

**Actual Behavior:**
- ✅ Cancellation signal honored
- ✅ Planning aborted
- ✅ UI returns to ready state

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC2.3: Empty Execution Plan
**Category:** Execution Planning  
**Scenario:** MacroPlanner returns empty plan

**Expected Behavior:**
- Error logged
- Execution does not start
- User notified

**Actual Behavior:**
- ✅ Empty plan detected
- ✅ Error message: "Could not generate plan"
- ✅ Task marked as failed

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC2.4: Plan with Single Step
**Category:** Execution Planning  
**Scenario:** Plan contains only 1 step

**Expected Behavior:**
- Accept single-step plan
- Execute normally
- Complete successfully

**Actual Behavior:**
- ✅ Single-step plans work
- ✅ UI displays correctly
- ✅ Execution completes

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC2.5: Plan with 100+ Steps
**Category:** Execution Planning  
**Scenario:** Plan contains very large number of steps

**Expected Behavior:**
- Accept large plans
- UI remains responsive
- Execution proceeds (may be slow)

**Actual Behavior:**
- ✅ Large plans accepted
- ✅ UI scrollable
- ⚠️ Long execution time (expected)

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC2.6: Step Execution Timeout
**Category:** Task Execution  
**Scenario:** Single step takes longer than timeout

**Expected Behavior:**
- Step marked as failed
- Timeout error logged
- Execution stops

**Actual Behavior:**
- ✅ Timeout detected
- ✅ Step fails gracefully
- ✅ Clear error message

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC2.7: Network Interruption During Execution
**Category:** Task Execution  
**Scenario:** Network drops while task is running

**Expected Behavior:**
- Retry step (up to retry count)
- If retries exhausted, fail gracefully
- Log network error

**Actual Behavior:**
- ✅ Retry logic implemented
- ✅ Fails after max retries
- ✅ Network errors logged

**Risk Level:** High  
**Status:** ✅ Handled

---

## 5. EC3: API and Mock Mode Edge Cases

### EC3.1: API Key Invalid Format
**Category:** Startup / Settings  
**Scenario:** User enters malformed API key

**Expected Behavior:**
- Accept any string (validation on use)
- Preflight check catches invalid key
- Block submission with clear message

**Actual Behavior:**
- ✅ Any string accepted in settings
- ✅ Preflight validates key
- ✅ Clear error: "invalid API key"

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC3.2: API Quota Exhausted
**Category:** Startup / Execution  
**Scenario:** Gemini API quota reached

**Expected Behavior:**
- Preflight detects quota error
- Block submission
- Suggest mock mode

**Actual Behavior:**
- ✅ Quota error detected
- ✅ Message: "quota or rate limit reached"
- ✅ Suggests switching to mock mode

**Risk Level:** High  
**Status:** ✅ Handled

---

### EC3.3: API Rate Limit
**Category:** Execution  
**Scenario:** Too many API requests in short time

**Expected Behavior:**
- Retry with exponential backoff
- If persistent, fail gracefully
- Log rate limit error

**Actual Behavior:**
- ✅ Retry logic with backoff
- ✅ Fails after max retries
- ✅ Rate limit logged

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC3.4: Mock Mode with API Key Set
**Category:** Startup  
**Scenario:** Both GEMINI_MOCK=1 and API key present

**Expected Behavior:**
- Mock mode takes precedence
- No API calls made
- Clear indication of mock mode

**Actual Behavior:**
- ✅ Mock mode activated
- ✅ API key ignored
- ✅ Status: "mock fallback ready"

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC3.5: Preflight Timeout
**Category:** Startup  
**Scenario:** Preflight checks take >8 seconds

**Expected Behavior:**
- Timeout after 8 seconds
- Block submission
- Suggest checking network or mock mode

**Actual Behavior:**
- ✅ Timeout enforced
- ✅ Submission blocked
- ✅ Message: "startup preflight timed out"

**Risk Level:** Medium  
**Status:** ✅ Handled

---

## 6. EC4: UI and Display Edge Cases

### EC4.1: Very Long Task Description
**Category:** UI Display  
**Scenario:** Task description is 1000 characters

**Expected Behavior:**
- Display in input field (scrollable)
- Truncate in history table
- Show full in details dialog

**Actual Behavior:**
- ✅ Input field scrollable
- ✅ Table truncates with "..."
- ✅ Full text in details

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC4.2: Very Long Step Description
**Category:** UI Display  
**Scenario:** Plan step description is very long

**Expected Behavior:**
- Display in execution plan panel
- Wrap or truncate as needed
- Readable without horizontal scroll

**Actual Behavior:**
- ✅ Text wraps in panel
- ✅ No horizontal scroll
- ✅ Readable formatting

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC4.3: Rapid Status Log Updates
**Category:** UI Performance  
**Scenario:** Many status messages in short time

**Expected Behavior:**
- UI remains responsive
- All messages logged
- Auto-scroll works correctly

**Actual Behavior:**
- ✅ Async updates prevent blocking
- ✅ All messages appear
- ✅ Auto-scroll smooth

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC4.4: Window Resize During Execution
**Category:** UI Layout  
**Scenario:** User resizes window while task running

**Expected Behavior:**
- Layout adjusts dynamically
- No content clipped
- Execution continues

**Actual Behavior:**
- ✅ Responsive layout
- ✅ Content reflows
- ✅ Execution unaffected

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC4.5: Tab Switch During Execution
**Category:** UI Navigation  
**Scenario:** User switches tabs while task executing

**Expected Behavior:**
- Tab switch allowed
- Execution continues in background
- Can return to Run tab anytime

**Actual Behavior:**
- ✅ Tabs switchable
- ✅ Execution continues
- ✅ State preserved

**Risk Level:** Low  
**Status:** ✅ Handled

---

## 7. EC5: Screenshot and Frame Edge Cases

### EC5.1: No Screenshots Generated
**Category:** Glass Box View  
**Scenario:** Backend doesn't generate any screenshots

**Expected Behavior:**
- Show placeholder message
- No errors or crashes
- Metadata shows "No frame available"

**Actual Behavior:**
- ✅ Placeholder displayed
- ✅ No errors
- ✅ Graceful handling

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC5.2: Corrupted Screenshot File
**Category:** Glass Box View  
**Scenario:** Screenshot file is corrupted or invalid

**Expected Behavior:**
- Detect load failure
- Show error placeholder
- Log warning
- Continue execution

**Actual Behavior:**
- ✅ Load error caught
- ✅ Error placeholder shown
- ✅ Warning logged
- ✅ Execution continues

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC5.3: Very Large Screenshot
**Category:** Glass Box View  
**Scenario:** Screenshot is 4K or larger

**Expected Behavior:**
- Load successfully
- Scale to fit panel
- Maintain aspect ratio
- No memory issues

**Actual Behavior:**
- ✅ Large images load
- ✅ Scaled correctly
- ✅ Aspect ratio preserved
- ✅ Memory managed

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC5.4: Rapid Screenshot Updates
**Category:** Glass Box View  
**Scenario:** Screenshots generated very rapidly (>30 FPS)

**Expected Behavior:**
- Throttle updates to prevent UI lag
- Display latest frame
- Calculate FPS correctly

**Actual Behavior:**
- ✅ Updates throttled
- ✅ Latest frame shown
- ✅ FPS accurate

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC5.5: Screenshot Directory Missing
**Category:** Glass Box View  
**Scenario:** `_runtime/screenshots/` doesn't exist

**Expected Behavior:**
- Create directory automatically
- Continue monitoring
- No errors

**Actual Behavior:**
- ✅ Directory created
- ✅ Monitoring starts
- ✅ No errors

**Risk Level:** Low  
**Status:** ✅ Handled

---

## 8. EC6: History and Database Edge Cases

### EC6.1: Empty History
**Category:** Task History  
**Scenario:** No tasks have been executed yet

**Expected Behavior:**
- Show "No tasks in history" message
- No errors
- UI remains functional

**Actual Behavior:**
- ✅ Empty state message
- ✅ No errors
- ✅ Search/filter still work

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC6.2: Very Large History (1000+ Tasks)
**Category:** Task History  
**Scenario:** Database contains 1000+ task records

**Expected Behavior:**
- Load within 1 second
- UI remains responsive
- Search works efficiently

**Actual Behavior:**
- ✅ Loads in <1s for 1000 tasks
- ✅ UI responsive
- ✅ Search fast (indexed)

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC6.3: Database File Locked
**Category:** Task History  
**Scenario:** Another process has database locked

**Expected Behavior:**
- Retry with backoff
- Show error if persistent
- Don't lose current task data

**Actual Behavior:**
- ✅ Retry logic implemented
- ✅ Error shown after retries
- ✅ Data queued for retry

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC6.4: Database Corrupted
**Category:** Task History  
**Scenario:** SQLite database file is corrupted

**Expected Behavior:**
- Detect corruption
- Attempt recovery
- Create new database if unrecoverable
- Log error

**Actual Behavior:**
- ✅ Corruption detected
- ✅ Recovery attempted
- ✅ New DB created if needed
- ✅ Error logged

**Risk Level:** High  
**Status:** ✅ Handled

---

### EC6.5: Concurrent Database Access
**Category:** Task History  
**Scenario:** Multiple operations try to write simultaneously

**Expected Behavior:**
- SQLite handles locking
- Operations serialized
- No data corruption

**Actual Behavior:**
- ✅ SQLite locking works
- ✅ Atomic transactions
- ✅ No corruption

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC6.6: Search with No Results
**Category:** Task History  
**Scenario:** Search term matches no tasks

**Expected Behavior:**
- Show "No matching tasks" message
- Clear search returns to full list
- No errors

**Actual Behavior:**
- ✅ Empty result message
- ✅ Clear works correctly
- ✅ No errors

**Risk Level:** Low  
**Status:** ✅ Handled

---

## 9. EC7: Settings Edge Cases

### EC7.1: Negative Timeout Value
**Category:** Settings  
**Scenario:** User enters negative timeout

**Expected Behavior:**
- Validation error
- Setting not saved
- Clear error message

**Actual Behavior:**
- ✅ Validation catches negative
- ✅ Error: "Timeout must be positive"
- ✅ Save blocked

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC7.2: Timeout Exceeds Maximum
**Category:** Settings  
**Scenario:** User enters timeout >300 seconds

**Expected Behavior:**
- Validation error
- Suggest maximum value
- Save blocked

**Actual Behavior:**
- ✅ Validation catches excess
- ✅ Error: "Maximum timeout is 300 seconds"
- ✅ Save blocked

**Risk Level:** Low  
**Status:** ✅ Handled

---

### EC7.3: Settings File Corrupted
**Category:** Settings  
**Scenario:** QSettings file is corrupted

**Expected Behavior:**
- Detect corruption
- Use default values
- Log warning
- Create new settings file

**Actual Behavior:**
- ✅ Corruption handled
- ✅ Defaults used
- ✅ Warning logged
- ✅ New file created

**Risk Level:** Medium  
**Status:** ✅ Handled

---

### EC7.4: Cancel Without Saving
**Category:** Settings  
**Scenario:** User modifies settings but switches tabs without saving

**Expected Behavior:**
- Changes discarded
- Settings revert to saved values
- No confirmation needed

**Actual Behavior:**
- ✅ Changes discarded
- ✅ Saved values retained
- ✅ Silent revert

**Risk Level:** Low  
**Status:** ✅ Handled

---

## 10. EC8: Application Lifecycle Edge Cases

### EC8.1: Close During Execution
**Category:** Application Lifecycle  
**Scenario:** User closes app while task is running

**Expected Behavior:**
- Prompt to confirm close
- Stop execution gracefully
- Save task to history
- Clean up resources

**Actual Behavior:**
- ✅ Close event intercepted
- ✅ Orchestrator shutdown called
- ✅ Task saved
- ✅ Resources cleaned

**Risk Level:** High  
**Status:** ✅ Handled

**Implementation:** `main.py::MainWindow.closeEvent()`

---

### EC8.2: Crash During Execution
**Category:** Application Lifecycle  
**Scenario:** Application crashes unexpectedly

**Expected Behavior:**
- Task data saved before crash (if possible)
- Database not corrupted
- Can recover on restart

**Actual Behavior:**
- ✅ Atomic transactions protect DB
- ✅ No corruption on crash
- ✅ Clean restart possible

**Risk Level:** High  
**Status:** ✅ Handled

---

### EC8.3: Multiple Instances
**Category:** Application Lifecycle  
**Scenario:** User launches app twice

**Expected Behavior:**
- Both instances run independently
- Separate database connections
- No conflicts

**Actual Behavior:**
- ✅ Multiple instances work
- ✅ SQLite handles concurrent access
- ⚠️ Shared database (by design)

**Risk Level:** Low  
**Status:** ✅ Handled (acceptable behavior)

---

### EC8.4: Low Disk Space
**Category:** Application Lifecycle  
**Scenario:** Disk space nearly full

**Expected Behavior:**
- Detect low space
- Warn user
- Prevent screenshot accumulation
- Continue core functionality

**Actual Behavior:**
- ⚠️ No explicit low-space detection
- ✅ Frame limits prevent unbounded growth
- ✅ Database writes fail gracefully

**Risk Level:** Medium  
**Status:** ⚠️ Partial (frame limits mitigate)

---

### EC8.5: Missing Dependencies
**Category:** Application Lifecycle  
**Scenario:** Required Python packages not installed

**Expected Behavior:**
- Clear error on startup
- List missing packages
- Suggest pip install

**Actual Behavior:**
- ✅ Import errors caught
- ✅ Clear error messages
- ✅ Requirements.txt provided

**Risk Level:** High  
**Status:** ✅ Handled

---

## 11. Edge Case Summary

| Category | Total Cases | Handled | Partial | Not Handled |
|----------|-------------|---------|---------|-------------|
| EC1: Input Validation | 5 | 5 | 0 | 0 |
| EC2: Execution | 7 | 7 | 0 | 0 |
| EC3: API and Mock Mode | 5 | 5 | 0 | 0 |
| EC4: UI and Display | 5 | 5 | 0 | 0 |
| EC5: Screenshots | 5 | 5 | 0 | 0 |
| EC6: History and Database | 6 | 6 | 0 | 0 |
| EC7: Settings | 4 | 4 | 0 | 0 |
| EC8: Application Lifecycle | 5 | 4 | 1 | 0 |
| **Total** | **42** | **41** | **1** | **0** |

**Coverage:** 98% (41/42 fully handled, 1 partial)

---

## 12. Risk Assessment

### High Risk Edge Cases (All Handled)
- EC2.7: Network interruption during execution ✅
- EC3.2: API quota exhausted ✅
- EC6.4: Database corrupted ✅
- EC8.1: Close during execution ✅
- EC8.2: Crash during execution ✅
- EC8.5: Missing dependencies ✅

### Medium Risk Edge Cases (All Handled)
- EC2.1: Rapid task submission ✅
- EC2.2: Cancellation during planning ✅
- EC2.3: Empty execution plan ✅
- EC2.6: Step execution timeout ✅
- EC3.1: Invalid API key ✅
- EC3.3: API rate limit ✅
- EC3.5: Preflight timeout ✅
- EC6.2: Large history ✅
- EC6.3: Database locked ✅
- EC6.5: Concurrent database access ✅
- EC7.3: Settings file corrupted ✅
- EC8.4: Low disk space ⚠️ (partial)

### Low Risk Edge Cases (All Handled)
- All remaining cases ✅

---

## References

- Functional Requirements: `functional-requirements.md`
- Feature Specifications: `feature-specifications.md`
- Acceptance Criteria: `acceptance-criteria.md`
- Test Cases: `../07-quality/test-cases.md`
