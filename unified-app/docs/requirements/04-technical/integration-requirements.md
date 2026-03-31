# Integration Requirements - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** TECH-003  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines integration requirements for the Orchestrator Desktop App, specifying how it integrates with external systems, APIs, and dependencies.

---

## 2. IR1: Trinity Core Integration

### IR1.1: Trinity Bridge Interface
**Requirement:** System shall integrate with Trinity Core via TrinityBridge adapter

**Integration Point:** `orchestrator/trinity_bridge.py`

**Interface:**
```python
class TrinityBridge:
    def execute_step(self, step_description: str, domain: str) -> dict:
        """Execute single step via Trinity Core"""
        pass
```

**Data Flow:**
- Input: Step description (string), domain (string)
- Output: Result dictionary with status and data

**Dependencies:**
- Trinity Core must be importable
- Trinity adapters must be available

**Status:** ✅ Implemented

**Tests:** `tests/unit/test_trinity_bridge.py`

---

### IR1.2: Adapter Selection
**Requirement:** System shall route tasks to appropriate Trinity adapter based on domain

**Domains:**
- `browser`: Browser automation adapter
- `desktop`: Desktop automation adapter
- `auto-detect`: Automatic domain detection

**Routing Logic:**
```python
if domain == "browser":
    use browser adapter
elif domain == "desktop":
    use desktop adapter
else:
    auto-detect from task description
```

**Status:** ✅ Implemented

---

### IR1.3: Error Handling
**Requirement:** System shall handle Trinity Core errors gracefully

**Error Types:**
- Adapter not available
- Execution timeout
- Step failure

**Handling:**
- Catch exceptions from Trinity
- Log error details
- Mark step as failed
- Continue to next step or stop execution

**Status:** ✅ Implemented

---

## 3. IR2: Gemini API Integration

### IR2.1: Live API Mode
**Requirement:** System shall integrate with Gemini API for plan generation in live mode

**API:** Google Generative AI (Gemini)

**Library:** `google-generativeai`

**Authentication:** API key from environment or settings

**Endpoint:** Gemini API via google-generativeai SDK

**Request Format:**
```python
model = genai.GenerativeModel('gemini-pro')
response = model.generate_content(prompt)
plan = parse_response(response.text)
```

**Response Format:** Text response parsed into structured plan

**Status:** ✅ Implemented

**Implementation:** `orchestrator/macro_planner.py`

---

### IR2.2: API Key Management
**Requirement:** System shall securely manage Gemini API key

**Storage:**
- QSettings (platform-specific secure storage)
- Environment variable `GEMINI_API_KEY`
- Module-local `.env` file

**Priority:**
1. Shell environment (highest)
2. .env file
3. QSettings

**Security:**
- Masked in UI
- Not logged in plain text
- Stored in platform-specific secure location

**Status:** ✅ Implemented

---

### IR2.3: API Error Handling
**Requirement:** System shall handle Gemini API errors gracefully

**Error Types:**
- Invalid API key
- Quota exhausted
- Rate limit exceeded
- Network timeout
- Service unavailable

**Handling:**
- Detect error type from exception
- Show user-friendly error message
- Suggest corrective action
- Fall back to mock mode if appropriate

**Status:** ✅ Implemented

**Tests:** `tests/integration/test_api_error_handling.py`

---

### IR2.4: Preflight Validation
**Requirement:** System shall validate API connectivity on startup

**Process:**
1. Check if API key is present
2. Make test API call (8s timeout)
3. Verify response
4. Determine readiness state

**Outcomes:**
- Success: Enable live mode
- Failure: Block submission, show error
- Timeout: Block submission, suggest mock mode

**Status:** ✅ Implemented

**Implementation:** `main.py::run_live_preflight()`

---

## 4. IR3: Mock Mode Integration

### IR3.1: Mock Activation
**Requirement:** System shall activate mock mode when `GEMINI_MOCK=1`

**Activation:**
- Detect environment variable
- Import and activate `testing/gemini_mock`
- Patch `google.generativeai` module
- Use deterministic planner

**Status:** ✅ Implemented

**Implementation:** `testing/gemini_mock/activator.py`

---

### IR3.2: Mock Behavior
**Requirement:** Mock mode shall provide deterministic planning without API calls

**Behavior:**
- Generate plan from task description
- No network calls
- Deterministic output for same input
- Same interface as live mode

**Plan Generation:**
```python
# Deterministic plan based on task keywords
if "browser" in task.lower():
    return ["Launch browser", "Navigate to URL", "Perform action"]
else:
    return ["Open application", "Execute command"]
```

**Status:** ✅ Implemented

---

### IR3.3: Mock Testing
**Requirement:** All tests shall run in mock mode without live API

**Configuration:**
- Set `GEMINI_MOCK=1` in test environment
- No API key required for tests
- Tests are deterministic and repeatable

**Status:** ✅ Implemented

**Verification:** All tests pass with `GEMINI_MOCK=1`

---

## 5. IR4: File System Integration

### IR4.1: Screenshot Monitoring
**Requirement:** System shall monitor file system for new screenshots

**Directory:** `_runtime/screenshots/`

**Monitoring:**
- Watch directory for new files
- Detect file creation events
- Emit `frame_captured` event
- Handle directory not existing

**File Pattern:** `screenshot_{domain}-obj-{timestamp}_{stage}.jpg`

**Status:** ✅ Implemented

**Implementation:** `orchestrator/screenshot_watcher.py`

---

### IR4.2: Screenshot Loading
**Requirement:** System shall load and display screenshot images

**Process:**
1. Receive file path from watcher
2. Load image using PyQt6 QPixmap
3. Scale to fit panel
4. Display in GlassBoxPanel

**Error Handling:**
- File not found: Use previous frame
- Corrupted image: Show error placeholder
- Load failure: Log warning, continue

**Status:** ✅ Implemented

---

### IR4.3: Frame Metadata Extraction
**Requirement:** System shall extract metadata from screenshot files

**Metadata:**
- Image dimensions (width, height)
- File size (bytes)
- Timestamp (from filename)
- FPS (calculated from timestamps)

**Implementation:**
```python
from PIL import Image
img = Image.open(path)
width, height = img.size
size_bytes = os.path.getsize(path)
```

**Status:** ✅ Implemented

**Implementation:** `orchestrator/frame_analyzer.py`

---

### IR4.4: Runtime Directory Structure
**Requirement:** System shall create and maintain runtime directory structure

**Structure:**
```
_runtime/
├── screenshots/    # Backend screenshots
├── sessions/       # Session data
└── history.db      # Task history database
```

**Creation:**
- Directories created on first use
- No errors if already exist
- Writable by application

**Status:** ✅ Implemented

---

## 6. IR5: Database Integration

### IR5.1: SQLite Connection
**Requirement:** System shall connect to SQLite database for task history

**Database File:** `_runtime/history.db`

**Connection:**
```python
import sqlite3
conn = sqlite3.connect('_runtime/history.db')
```

**Configuration:**
- Auto-create database if not exists
- Create schema on first run
- Use parameterized queries
- Close connection on shutdown

**Status:** ✅ Implemented

**Implementation:** `ui/views/history_manager.py`

---

### IR5.2: Schema Management
**Requirement:** System shall create and maintain database schema

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    domain TEXT,
    plan TEXT,
    outcome TEXT,
    error TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_description ON tasks(description);
CREATE INDEX IF NOT EXISTS idx_start_time ON tasks(start_time);
```

**Migration:** No migration needed (single version)

**Status:** ✅ Implemented

---

### IR5.3: Transaction Management
**Requirement:** System shall use atomic transactions for database operations

**Pattern:**
```python
with conn:
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (...) VALUES (?)", params)
    conn.commit()
```

**Benefits:**
- Atomic operations
- Rollback on error
- No partial writes

**Status:** ✅ Implemented

---

### IR5.4: Concurrent Access
**Requirement:** System shall handle concurrent database access

**Mechanism:** SQLite built-in locking

**Handling:**
- Retry on database locked error
- Exponential backoff
- Timeout after max retries

**Status:** ✅ Implemented

---

## 7. IR6: Settings Integration

### IR6.1: QSettings Storage
**Requirement:** System shall use QSettings for persistent configuration

**Storage Location:**
- Windows: Registry `HKEY_CURRENT_USER\Software\{Organization}\{Application}`
- Platform-specific secure storage

**Settings:**
- API key (masked)
- Timeout (seconds)
- Retry count
- Domain default
- Frame limits

**Status:** ✅ Implemented

**Implementation:** `ui/views/settings_view.py`

---

### IR6.2: Environment Variables
**Requirement:** System shall load configuration from environment variables

**Variables:**
- `GEMINI_API_KEY`: API key for live mode
- `GEMINI_MOCK`: Enable mock mode (1 = enabled)

**Loading:**
```python
from dotenv import load_dotenv
load_dotenv('.env', override=False)
api_key = os.getenv('GEMINI_API_KEY')
mock_mode = os.getenv('GEMINI_MOCK')
```

**Priority:** Shell environment > .env file > QSettings

**Status:** ✅ Implemented

---

### IR6.3: Configuration Validation
**Requirement:** System shall validate configuration values

**Validation:**
- Timeout: 1-300 seconds
- Retry: 0-10
- Frame limits: positive integers
- API key: any string (validated on use)

**Handling:**
- Show error for invalid values
- Prevent saving invalid configuration
- Use defaults if corrupted

**Status:** ✅ Implemented

---

## 8. IR7: Event Bus Integration

### IR7.1: Signal/Slot Mechanism
**Requirement:** System shall use PyQt6 signals for event communication

**Pattern:**
```python
class EventBus(QObject):
    task_submitted = pyqtSignal(str, str)  # description, domain
    
bus = EventBus()
bus.task_submitted.connect(handler)
bus.task_submitted.emit("task", "browser")
```

**Benefits:**
- Type-safe signals
- Automatic thread safety
- Decoupled components

**Status:** ✅ Implemented

**Implementation:** `orchestrator/event_bus.py`

---

### IR7.2: Event Types
**Requirement:** System shall define typed events for all inter-component communication

**Events:**
- Task lifecycle: `task_submitted`, `execution_complete`
- Plan updates: `plan_generated`, `step_started`, `step_completed`, `step_failed`
- UI updates: `app_busy`, `status_update`
- Frame updates: `frame_captured`, `frame_rate_updated`

**Type Safety:** PyQt6 signals enforce parameter types

**Status:** ✅ Implemented

---

### IR7.3: Event Ordering
**Requirement:** Events shall be processed in order of emission

**Guarantee:** Qt event loop processes signals in FIFO order

**Handling:**
- No race conditions between events
- Predictable execution order
- Testable event sequences

**Status:** ✅ Guaranteed by Qt

---

## 9. Integration Testing

### IT1: Trinity Core Integration Tests
**Tests:**
- Bridge initialization
- Step execution
- Error handling
- Domain routing

**Status:** ✅ Implemented

**Location:** `tests/unit/test_trinity_bridge.py`

---

### IT2: Gemini API Integration Tests
**Tests:**
- Live mode plan generation
- Mock mode plan generation
- API error handling
- Preflight checks

**Status:** ✅ Implemented

**Location:** `tests/integration/test_api_integration.py`

---

### IT3: Database Integration Tests
**Tests:**
- Connection management
- CRUD operations
- Transaction handling
- Concurrent access

**Status:** ✅ Implemented

**Location:** `tests/unit/test_history_manager.py`

---

### IT4: File System Integration Tests
**Tests:**
- Screenshot detection
- Frame loading
- Metadata extraction
- Directory creation

**Status:** ✅ Implemented

**Location:** `tests/unit/test_screenshot_watcher.py`, `tests/unit/test_frame_analyzer.py`

---

### IT5: End-to-End Integration Tests
**Tests:**
- Full task submission to completion
- All components working together
- Event flow verification

**Status:** ✅ Implemented

**Location:** `tests/integration/test_full_loop_integration.py`

---

## 10. Integration Summary

| Integration Point | Status | Tests | Documentation |
|-------------------|--------|-------|---------------|
| Trinity Core | ✅ Complete | ✅ Passing | ✅ Documented |
| Gemini API | ✅ Complete | ✅ Passing | ✅ Documented |
| Mock Mode | ✅ Complete | ✅ Passing | ✅ Documented |
| File System | ✅ Complete | ✅ Passing | ✅ Documented |
| Database | ✅ Complete | ✅ Passing | ✅ Documented |
| Settings | ✅ Complete | ✅ Passing | ✅ Documented |
| Event Bus | ✅ Complete | ✅ Passing | ✅ Documented |

**Overall Integration Status:** 100% Complete

---

## References

- System Architecture: `system-architecture.md`
- Technical Constraints: `technical-constraints.md`
- Data Models: `data-models.md`
- Test Strategy: `../07-quality/test-strategy.md`
