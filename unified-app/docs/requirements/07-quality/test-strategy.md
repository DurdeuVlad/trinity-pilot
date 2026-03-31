# Test Strategy - Orchestrator Desktop App

**Document ID:** TEST-STRAT-001  
**Version:** 2.0  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines how `unified-app` is verified today. It focuses on the
current suite structure, required quality gates, and the acceptance areas from
`docs/requirements.md`.

---

## 2. Testing Goals

1. Keep the core orchestration workflow stable.
2. Preserve mock/live startup behavior and clear failure messaging.
3. Keep history/settings persistence reliable.
4. Maintain `>= 85%` coverage across the orchestrator and UI surfaces named in
   the top-level requirements.
5. Ensure user-facing docs and packaging surfaces stay aligned with the code.

---

## 3. Test Layers

### 3.1 Isolated Component Coverage

**Purpose:** Validate focused backend and startup contracts quickly.

**Primary paths:**
- `tests/orchestrator/`
- `tests/test_frame_analyzer.py`
- `tests/test_trinity_bridge.py`
- `tests/test_startup_runtime.py`

**Key modules exercised:**
- `orchestrator/orchestrator_core.py`
- `orchestrator/execution_runner.py`
- `orchestrator/macro_planner.py`
- `orchestrator/screenshot_watcher.py`
- `orchestrator/frame_analyzer.py`
- `orchestrator/database/manager.py`
- `orchestrator/settings_manager.py`
- `main.py` startup-mode helpers

**Command:**

```bash
pytest unified-app/tests/orchestrator/ unified-app/tests/test_frame_analyzer.py unified-app/tests/test_trinity_bridge.py unified-app/tests/test_startup_runtime.py -v
```

### 3.2 UI Component Coverage

**Purpose:** Verify widget behavior without needing a packaged executable.

**Primary path:** `tests/ui/`

**Covered components:**
- `TaskInputPanel`
- `ExecutionPlanPanel`
- `GlassBoxPanel`
- `StatusLogPanel`
- `HistoryView`
- `SettingsView`

**Command:**

```bash
pytest unified-app/tests/ui/ -v
```

### 3.3 Integration Coverage

**Purpose:** Verify the assembled in-process workflow across orchestrator,
storage, events, and Gemini startup/runtime seams.

**Primary path:** `tests/integration/`

**Command:**

```bash
pytest unified-app/tests/integration/ -v
```

### 3.4 Production-style E2E Coverage

**Purpose:** Exercise higher-level app-session workflows and production-facing
contracts.

**Primary path:** `tests/e2e/`

**Command:**

```bash
pytest unified-app/tests/e2e/ -v
```

### 3.5 Performance Coverage

**Purpose:** Catch lightweight runtime-cost regressions.

**Primary path:** `tests/performance/`

**Command:**

```bash
pytest unified-app/tests/performance/ -v
```

---

## 4. Coverage Measurement

Coverage is verified from the repo root.

```bash
pytest unified-app/tests/ -v --cov=unified-app/orchestrator --cov=unified-app/ui --cov-report=term-missing
```

**Gate:** Do not close work if orchestrator/UI coverage drops below `85%`.

---

## 5. Requirements Alignment

| Requirements area | Evidence surface |
|------------------|------------------|
| FR1-FR3 task execution, planning, monitoring | `tests/orchestrator/`, `tests/ui/`, `tests/integration/test_full_loop_integration.py` |
| FR4 history persistence and browsing | `tests/orchestrator/test_history_manager.py`, `tests/ui/test_history_view.py` |
| FR5 settings management | `tests/orchestrator/test_settings_manager.py`, `tests/ui/test_settings_view.py` |
| FR6 startup modes and readiness | `tests/test_startup_runtime.py`, integration smoke/acceptance tests |
| AC3 testing gate | Full suite + coverage command |
| AC4 documentation gate | Requirements docs + `docs/USER_MANUAL.md` + `docs/QUICK_START.md` + `docs/FAQ.md` |
| AC5 packaging gate | Packaging artifacts and build docs, plus smoke validation when packaging work changes |

---

## 6. Non-Functional Focus

| Area | Strategy |
|------|----------|
| Reliability | Prefer deterministic isolated tests for startup, persistence, and cleanup contracts |
| Maintainability | Add focused seam tests when refactoring legacy orchestration paths |
| Usability | Cover stable object names, widget wiring, and history/settings behavior in `tests/ui/` |
| Performance | Keep lightweight regression checks in `tests/performance/`; use deeper profiling only when a change justifies it |

---

## 7. Standard Execution Sequence

1. Run the smallest relevant layer first.
2. Run the full suite if multiple seams were touched.
3. Run coverage when orchestrator or UI code changed.
4. Run repo quality gates:

```bash
python ai-quality-checker/check_code.py
python ai-quality-checker/check_docs.py
python .ai/scripts/validate.py
```

5. Fix findings before updating changelog/build docs.

---

## 8. Out of Scope

- Hard-coded historical pass counts
- Claims about live API verification without a fresh live run
- CI/CD assertions not backed by this repository

This strategy should describe the current repo truth, not historical sprint
snapshots.
