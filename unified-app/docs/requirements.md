# Unified-App Requirements

**Module:** unified-app  
**Purpose:** Desktop orchestration UI layer on top of Trinity Core  
**Status:** Existing implementation - requirements extracted for rebuild validation  
**Last Updated:** 2026-03-14

---

## Functional Requirements

### FR1: Task Submission and Execution
- **FR1.1** User can submit natural language task descriptions via GUI
- **FR1.2** System validates task input before submission (non-empty, reasonable length)
- **FR1.3** System prevents duplicate submissions while task is executing
- **FR1.4** User can cancel running tasks
- **FR1.5** System supports domain auto-detection or manual domain selection

### FR2: Execution Planning
- **FR2.1** System generates execution plan from task description using MacroPlanner
- **FR2.2** System displays execution plan with numbered steps before execution
- **FR2.3** System updates step status in real-time (pending → running → completed/failed)
- **FR2.4** System falls back to deterministic local planning when Gemini API unavailable

### FR3: Real-Time Monitoring
- **FR3.1** System displays real-time status log with timestamps and severity levels
- **FR3.2** System captures and displays screenshots from backend execution (glass box view)
- **FR3.3** System displays frame metadata (width, height, size, FPS)
- **FR3.4** System updates UI state to reflect execution progress (busy/idle)

### FR4: Task History
- **FR4.1** System persists all task executions to SQLite database
- **FR4.2** User can view task history in dedicated History tab
- **FR4.3** User can search/filter history entries
- **FR4.4** User can view detailed task information (task description, plan, outcome, timestamps)
- **FR4.5** System displays task status (success/failure) in history view

### FR5: Settings Management
- **FR5.1** User can configure Gemini API key via Settings tab
- **FR5.2** User can configure timeout settings
- **FR5.3** User can configure retry settings
- **FR5.4** User can set domain defaults
- **FR5.5** System persists settings across sessions
- **FR5.6** User can configure frame capture limits

### FR6: Startup Modes
- **FR6.1** System supports live Gemini mode with API key validation
- **FR6.2** System supports mock mode for offline/demo usage (GEMINI_MOCK=1)
- **FR6.3** System runs startup preflight checks for live mode (8s timeout)
- **FR6.4** System blocks task submission if startup checks fail in live mode
- **FR6.5** System displays clear startup status messages to user
- **FR6.6** System loads configuration from module-local .env file

---

## Non-Functional Requirements

### NFR1: Performance
- **NFR1.1** UI remains responsive during task execution (async orchestration)
- **NFR1.2** Screenshot display updates within 100ms of frame capture
- **NFR1.3** History view loads within 1 second for <1000 entries
- **NFR1.4** Startup preflight completes within 8 seconds

### NFR2: Reliability
- **NFR2.1** System handles orchestrator failures gracefully (error messages, no crashes)
- **NFR2.2** System persists task history even if execution fails
- **NFR2.3** System cleans up resources on application close
- **NFR2.4** System validates all user inputs before processing

### NFR3: Usability
- **NFR3.1** UI uses tabbed interface (Run, History, Settings)
- **NFR3.2** All panels have clear labels and intuitive layout
- **NFR3.3** Error messages are actionable (tell user what to do)
- **NFR3.4** Settings have sensible defaults
- **NFR3.5** Application window is resizable (min 1000x720)

### NFR4: Maintainability
- **NFR4.1** Code coverage ≥85% for orchestrator and UI modules
- **NFR4.2** All public APIs have type hints
- **NFR4.3** Event-driven architecture using EventBus for loose coupling
- **NFR4.4** Clear separation: UI (PyQt6) / Orchestrator (business logic) / Adapters (backends)

### NFR5: Testability
- **NFR5.1** Unit tests for all core orchestrator logic
- **NFR5.2** Integration tests for full orchestration workflow
- **NFR5.3** UI tests for critical user flows
- **NFR5.4** Mock mode enables testing without live API dependencies
- **NFR5.5** All tests run via pytest with clear pass/fail reporting

---

## Technical Requirements

### TR1: Framework and Dependencies
- **TR1.1** Python 3.10+
- **TR1.2** PyQt6 for GUI framework
- **TR1.3** SQLite for task history persistence
- **TR1.4** Async/await for non-blocking orchestration
- **TR1.5** python-dotenv for environment configuration
- **TR1.6** Gemini API integration via google-generativeai
- **TR1.7** testing/gemini_mock for offline testing

### TR2: Architecture
- **TR2.1** Event bus pattern for component communication
- **TR2.2** OrchestratorCore manages execution lifecycle
- **TR2.3** MacroPlanner generates execution plans
- **TR2.4** FrameAnalyzer extracts screenshot metadata
- **TR2.5** ScreenshotWatcher monitors _runtime/screenshots directory
- **TR2.6** TrinityBridge integrates with Trinity Core adapters

### TR3: File Structure
- **TR3.1** Entry point: main.py
- **TR3.2** Orchestrator logic: orchestrator/
- **TR3.3** UI components: ui/panels/ and ui/views/
- **TR3.4** Tests: tests/ (unit, integration, UI)
- **TR3.5** Documentation: docs/
- **TR3.6** Runtime data: _runtime/ (screenshots, sessions, history.db)

### TR4: Packaging
- **TR4.1** PyInstaller spec files for standalone executable
- **TR4.2** NSIS installer configuration
- **TR4.3** Build script (build.ps1) for Windows
- **TR4.4** All dependencies bundled in executable

---

## Acceptance Criteria

### AC1: Core Workflow
- User can submit task → see plan → watch execution → view result in history
- All steps complete without crashes or hangs
- Status log shows clear progression

### AC2: Error Handling
- Invalid API key shows actionable error message
- Missing API key falls back to mock mode gracefully
- Network failures don't crash the app
- User sees clear error messages for all failure modes

### AC3: Testing
- `pytest tests/ -v` passes all tests
- Coverage report shows ≥85% for orchestrator and ui modules
- Integration tests verify full orchestration loop
- Live acceptance tests pass with real Gemini API (when available)

### AC4: Documentation
- USER_MANUAL.md covers all user-facing features
- QUICK_START.md enables new users to run app in <5 minutes
- FAQ.md addresses common issues
- Code has docstrings for all public functions/classes

### AC5: Packaging
- `build.ps1` produces working standalone executable
- Executable runs on clean Windows machine without Python installed
- Installer creates Start Menu shortcuts
- Uninstaller removes all traces

---

## Out of Scope

- Browser adapter integration (deferred to future epic)
- Desktop adapter integration (deferred to future epic)
- Multi-user support
- Cloud synchronization
- Plugin system
- Custom themes
- Mobile/web versions
- Real-time collaboration

---

## References

- Architecture: `docs/plans/orchestrator_desktop_app/README.md`
- Sprint reports: `docs/SPRINT_*_COMPLETION_REPORT.md`
- User manual: `docs/USER_MANUAL.md`
- Context: `.ai/CONTEXT.md`
