# Trinity Pilot tracing

Trinity Pilot emits a unified **NDJSON** timeline for debugging E2E runs, VM evals, and orchestrator behaviour.

## Output file

Default path: `trinity-pilot/.trace/trinity-trace.jsonl`

Override with `TRINITY_TRACE_DIR` (directory only; filename is always `trinity-trace.jsonl`).

During `eval_multirun.py` runs, each scenario run writes to:

```text
<results-dir>/pytest_logs/traces/<scenario>_run<N>/trinity-trace.jsonl
```

After each task, the orchestrator also exports:

```text
<TRINITY_TRACE_DIR>/attempts-<task_id>.json
```

## Event schema

One JSON object per line:

| Field | Type | Description |
|-------|------|-------------|
| `ts` | int | Unix epoch milliseconds |
| `timestamp` | int | Same as `ts` (legacy compat) |
| `location` | string | Source file/function, e.g. `bridge.py:_run_orchestrator` |
| `message` | string | Event name, e.g. `task_started` |
| `data` | object | Structured payload |
| `span` | string | Optional grouping: `bridge`, `orchestrator`, `worker`, `signal`, `evidence` |
| `hypothesisId` | string | Optional debug tag (E2E probes) |
| `runId` | string | Optional run label (default `probe`) |

Orchestrator signals appear as `span=signal` with `message` set to the signal class name (`ObjectiveStarted`, `StepCompleted`, etc.).

Bridge log lines from the UI appear as `span=bridge`, `message=bridge_log_message`.

## Environment variables

| Variable | Effect |
|----------|--------|
| `TRINITY_TRACE=1` | Force tracing on |
| `TRINITY_TRACE=0` | Force tracing off |
| `TRINITY_TRACE_DIR` | Output directory for `trinity-trace.jsonl` and `attempts-*.json` |

### Auto-enable

Tracing turns on automatically when any of:

- `TRINITY_CONNECT_EXISTING=1` (VM eval reuses a running app)
- `DB_PATH` ends with `_trinity_test.db` (E2E `_gui_driver` launches)
- `python -m trinity_pilot --test-mode` (sets `TRINITY_TRACE=1` at startup)
- E2E driver sets `TRINITY_TRACE=1` in the child process environment


## Reading traces

Human-readable timeline:

```bash
python scripts/trace_timeline.py path/to/trinity-trace.jsonl
python scripts/trace_timeline.py path/to/trinity-trace.jsonl --tail 20
python scripts/trace_timeline.py path/to/trinity-trace.jsonl --span orchestrator
```

Raw NDJSON is also valid input for `jq`, log aggregators, or custom analysis.

## VM / multirun collection

`eval_multirun.py` sets `TRINITY_TRACE_DIR` per scenario run. Each entry in `multirun_results.json` may include:

- `trace_lines` — count of NDJSON lines
- `trace_tail` — last 5 raw lines
- `last_event` — parsed final event object
- `trace_dir` — path to the trace directory

`scripts/vm_pipeline.py` sets `TRINITY_TRACE=1` on the guest and collects:

- `pytest_logs/traces/` — per-scenario trace dirs (copied to host as `traces/`)
- `trace_default/` — `.trace/` fallback dir if present
- `attempts-*.json` — inside each trace dir

Host results land under `.ai/vm-results/<timestamp>/`.

## Implementation

- Module: `trinity_pilot/telemetry/trace.py`
- Wrappers: `trinity_pilot/_agent_debug.py`, `tests/e2e/_debug_log.py`
- Signal drain: `trinity_pilot/ui/bridge.py` (`_WorkerThread._drain_signals`)
- Attempts export: `trinity_pilot/orchestrator/engine.py` (`_finish`)
