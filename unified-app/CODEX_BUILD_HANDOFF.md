# Codex Build Handoff - Unified-App

**Date:** 2026-03-14  
**Prepared by:** Cascade (Windsurf)  
**Target:** OpenAI Codex  
**Workflow:** `/build` (single autonomous build pass)

---

## Objective

Execute a requirements-driven build pass for `unified-app` to validate the existing implementation against documented requirements and ensure the application is fully functional.

---

## Context

**Module:** `unified-app`  
**Location:** `c:\Users\User\Documents\Github\desktop-ai-poc-modules\unified-app`  
**Current Status:** Sprint 0-4 complete, marked as ✅ Complete in CONTEXT.md  
**Purpose:** Desktop orchestration UI layer on top of Trinity Core

**What exists:**
- Fully implemented PyQt6 desktop application
- 4 completed sprints with documentation
- 86% test coverage
- Working orchestrator core, event bus, UI panels
- SQLite history persistence
- Gemini API integration with mock mode fallback

**What's needed:**
- Validate implementation against requirements
- Ensure app runs correctly
- Fix any gaps or issues found
- Update documentation if needed

---

## Requirements Document

**Location:** `unified-app/docs/requirements.md`

This comprehensive requirements document was extracted from the existing codebase and includes:
- 6 functional requirement categories (FR1-FR6)
- 5 non-functional requirement categories (NFR1-NFR5)
- 4 technical requirement categories (TR1-TR4)
- 5 acceptance criteria sections (AC1-AC5)
- Clear out-of-scope items

---

## Execution Instructions for Codex

### Step 1: Read Entry Point
Read `AGENTS.md` at repo root to understand the framework and session protocol.

### Step 2: Navigate to Module
```powershell
cd c:\Users\User\Documents\Github\desktop-ai-poc-modules\unified-app
```

### Step 3: Execute /build Workflow

Run the `/build` workflow (or equivalent `/prompts:build` for Codex CLI):

```
/build unified-app/docs/requirements.md
```

**What `/build` will do:**
1. **Ingest requirements** from `docs/requirements.md`
2. **Audit codebase** against requirements
3. **Plan sprints** if gaps found
4. **Execute implementation** to close gaps
5. **Run QA checks** (pytest, coverage, validation)
6. **Run quality gates** (code checker, docs checker)
7. **Commit changes** with conventional commit message

### Step 4: Validation Commands

After `/build` completes, verify:

```powershell
# Run tests
pytest tests/ -v

# Check coverage
pytest tests/ -v --cov=orchestrator --cov=ui --cov-report=term-missing

# Run the app
python main.py
```

**Expected results:**
- All tests pass
- Coverage ≥85%
- App launches without errors
- Can submit task and see execution flow

---

## Key Files for Codex to Review

### Core Implementation
- `main.py` - Entry point, startup logic, MainWindow
- `orchestrator/orchestrator_core.py` - Execution lifecycle
- `orchestrator/event_bus.py` - Event-driven architecture
- `orchestrator/macro_planner.py` - Plan generation
- `orchestrator/trinity_bridge.py` - Backend integration

### UI Components
- `ui/panels/task_input_panel.py` - Task submission
- `ui/panels/execution_plan_panel.py` - Plan display
- `ui/panels/glass_box_panel.py` - Screenshot viewer
- `ui/panels/status_log_panel.py` - Status logging
- `ui/views/history_view.py` - Task history
- `ui/views/settings_view.py` - Configuration

### Tests
- `tests/unit/` - Unit tests
- `tests/integration/` - Integration tests
- `tests/ui/` - UI tests
- `tests/integration/test_poc_acceptance.py` - Live acceptance tests

### Documentation
- `docs/requirements.md` - **PRIMARY INPUT** for /build
- `docs/USER_MANUAL.md` - User-facing documentation
- `docs/QUICK_START.md` - Getting started guide
- `.ai/CONTEXT.md` - Module context

---

## Environment Setup

The module uses:
- Python 3.10+
- PyQt6 for GUI
- SQLite for persistence
- Gemini API (with mock mode fallback)

**Environment variables:**
- `GEMINI_MOCK=1` - Enable mock mode (no API key needed)
- `GEMINI_API_KEY=<key>` - Live Gemini API key (optional)
- `PYTHONPATH=.` - Required for testing (gemini_mock import)

**Module-local .env:**
```
GEMINI_MOCK=1
```

---

## Success Criteria

### Minimum Success
- `/build` completes without errors
- All existing tests pass
- App launches and displays main window
- Requirements coverage report shows 100%

### Full Success
- All gaps identified and fixed
- New tests added for any new functionality
- Documentation updated to reflect changes
- Quality gates pass (validate.py, code checker, docs checker)
- Clean commit with conventional commit message

---

## Known Constraints

1. **No live Gemini API required** - mock mode is sufficient for validation
2. **Trinity Core adapters** - browser and desktop adapters are deferred (out of scope)
3. **Testing from repo root** - `PYTHONPATH=.` required for gemini_mock imports
4. **Windows environment** - PowerShell commands, Windows paths

---

## Troubleshooting

### If tests fail
- Check `PYTHONPATH=.` is set
- Verify `GEMINI_MOCK=1` is set
- Check SQLite database isn't locked
- Review test output for specific failures

### If app doesn't launch
- Check dependencies: `pip install -r requirements.txt`
- Verify PyQt6 installed correctly
- Check for Python version (3.10+ required)
- Review startup logs for errors

### If /build workflow fails
- Check requirements.md is valid
- Verify all referenced files exist
- Review error messages for specific issues
- Fall back to manual `/epic-plan` → `/execute` if needed

---

## Post-Execution Report

After `/build` completes, Codex should provide:

1. **Requirements coverage summary** - which requirements were validated/fixed
2. **Changes made** - list of files modified/created
3. **Test results** - pytest output, coverage percentage
4. **Quality gate results** - validate.py, code checker, docs checker
5. **Commit message** - conventional commit format
6. **Next steps** - any remaining work or recommendations

---

## Handoff Complete

**Prepared by:** Cascade (Windsurf)  
**Ready for:** OpenAI Codex execution  
**Workflow:** `/build` or `/prompts:build`  
**Input:** `unified-app/docs/requirements.md`

Codex: You have full context and clear instructions. Execute `/build` workflow now.
