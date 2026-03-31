# Orchestrator Desktop App

**Status:** Sprint 0-4 complete  
**Framework Decision:** PyQt6  
**Current Focus:** Release hardening and packaging execution

## Quick Start

```powershell
pip install -r requirements.txt
pytest tests/ -v
python main.py
```

## Completed

- Sprint 0: framework decision and vertical slice
- Sprint 1: core UI, event bus, planner fallback, orchestrator workflow
- Sprint 2: glass box watcher/panel + frame metadata
- Sprint 3: history/settings/error handling + tabbed UI
- Sprint 4: release docs, packaging configs, expanded test suite

## Development

```powershell
pytest tests/ -v
```

## Documentation

- Sprint plan: `../docs/plans/sprints/2026_02_14_orchestrator_app/`
- Architecture: `../docs/plans/orchestrator_desktop_app/README.md`
- Technical decisions: `../docs/plans/orchestrator_desktop_app/technical_decisions.md`
- Sprint 0 report: `docs/SPRINT_0_COMPLETION_REPORT.md`
- Sprint 1 report: `docs/SPRINT_1_COMPLETION_REPORT.md`
- Sprint 2 report: `docs/SPRINT_2_COMPLETION_REPORT.md`
- Sprint 3 report: `docs/SPRINT_3_COMPLETION_REPORT.md`
- Sprint 4 report: `docs/SPRINT_4_COMPLETION_REPORT.md`
