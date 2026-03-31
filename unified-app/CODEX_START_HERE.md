# Orchestrator Desktop App - Start Here

> **Status:** Sprint 0-4 complete  
> **Next:** Package and release build execution

## Current State

- Sprint 0: complete
- Sprint 1: complete
- Sprint 2: complete
- Sprint 3: complete
- Sprint 4: complete

## Next Actions

1. Review release plan:
```powershell
..\docs\plans\sprints\2026_02_14_orchestrator_app\SPRINT_4_RELEASE.md
```

2. Run regression suite:
```powershell
pytest tests/ -v
```

3. Build package:
```powershell
.\scripts\build.ps1
```

## Core Files

- `main.py`
- `orchestrator/event_bus.py`
- `orchestrator/macro_planner.py`
- `orchestrator/orchestrator_core.py`
- `orchestrator/trinity_bridge.py`
- `orchestrator/screenshot_watcher.py`
- `orchestrator/database/models.py`
- `orchestrator/database/manager.py`
- `ui/views/history_view.py`
- `ui/views/settings_view.py`
- `ui/panels/task_input_panel.py`
- `ui/panels/execution_plan_panel.py`
- `ui/panels/status_log_panel.py`
- `ui/panels/glass_box_panel.py`

## Reports

- `docs/SPRINT_0_COMPLETION_REPORT.md`
- `docs/SPRINT_1_COMPLETION_REPORT.md`
- `docs/SPRINT_2_COMPLETION_REPORT.md`
- `docs/SPRINT_3_COMPLETION_REPORT.md`
- `docs/SPRINT_4_COMPLETION_REPORT.md`
- `docs/SPRINT_AUDIT.md`
