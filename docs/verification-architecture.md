# Verification Architecture — Checklist Engine (C1) and Tiered Action Verify (C5)

Two independent mechanisms, built in the same session, sharing no files except
an additive field on `ObjectiveSpec`. Both are unit-tested and wired in; neither
has been validated against a live VM run yet — see "Status" at the bottom.

## C1 — Planner-Authored Verification Checklist

**Problem:** the reviewer's freeform LLM judgment (`_review_with_llm`) reads
the entire evidence blob and answers one wide question — "did this objective
pass?" A wide question is easier to bluff through than several narrow ones.

**Design:** the planner may attach a `verification_checklist` to an
`ObjectiveSpec` — a tuple of `ChecklistItem(instruction, sensors)`. Each item
names which evidence fields ("sensors") are relevant and states one narrow
thing to verify. At review time, `evaluate_checklist()` runs each valid item
concurrently (`asyncio.TaskGroup`), asks the reviewer LLM the *one* scoped
question per item against *only* the named evidence fields, and aggregates:
any item failing is a hard veto, same semantics as the existing
`write_file_failures`/`visible_text_probe` floors.

**Deliberately no predicate-checkable tier.** An earlier design considered
letting the planner also pick a deterministic check (e.g. `file_exists`) per
item. Dropped: a planner picking the *wrong* deterministic check for an
objective is a new mismatch-crash class, the same shape as the MIXED-domain
router crash this codebase already hit once. Every checklist item is
guided-LLM-only, scoped by `instruction` + `sensors`, never a planner-chosen
deterministic function.

**Malformed items never crash review.** `ChecklistItem.is_valid()` requires a
non-empty `instruction` and at least one `sensors` entry. Invalid items are
silently dropped and counted in the result notes (`"N malformed checklist
item(s) skipped"`); if every item is invalid, `evaluate_checklist()` returns
`None` and the reviewer falls through to existing floors/freeform judgment
unchanged.

**Ordering:** hard floors (`write_file_failures`, `visible_text_probe`) run
first and short-circuit before the checklist is ever evaluated — confirmed by
`test_write_file_floor_short_circuits_before_checklist_is_evaluated`.

| Component | File |
|---|---|
| `ChecklistItem` | `trinity_pilot/core/types.py` |
| `evaluate_checklist()` | `trinity_pilot/reviewer/checklist.py` |
| Reviewer wiring | `trinity_pilot/reviewer/reviewer.py::ObjectiveReviewer.review` |
| Scoped prompt | `trinity_pilot/reviewer/prompts.py::CHECKLIST_ITEM_SYSTEM/_USER_TEMPLATE` |
| Tests | `tests/unit/test_types.py`, `tests/unit/test_reviewer_checklist.py`, `tests/unit/test_reviewer.py` |

## C5 — Tiered In-Loop Action Verification

**Problem:** the dedup-triggered reflection (existing C5) only fires on a
*repeated* identical tool call. Every action otherwise gets no grounding
beyond its own narration in `action_log`.

**Design:** every dispatched action maps to exactly one of three tiers in
`ActionTier`/`TIER_REGISTRY` (`trinity_pilot/workers/action_verification.py`),
chosen by us at registration time, never guessed at runtime — same
mismatch-avoidance reasoning as C1's dropped predicate tier:

- **`DETERMINISTIC`** (`write_file`, `run_command`) — reads what already
  happened in `evidence` (`write_file_failures`, `exit_code`). No wait, no LLM.
- **`EVENTUALLY_CONSISTENT`** (`launch_app`, `navigate`) — polls a worker-
  supplied `sensor_check` predicate via `tenacity.AsyncRetrying` with
  exponential backoff, bounded by `deadline_seconds`. Replaces the kind of
  fixed `asyncio.sleep(wait)` `launch_app` used before (see
  `desktop_worker.py::_action_sensor_check` for the concrete override —
  polls `psutil.pid_exists` on the launched PIDs instead of sleeping blind).
- **`LLM_GROUNDED`** (`click_button`, `type_text`) — reads a worker-supplied
  `sensor_read` (e.g. `desktop_worker.py::_action_sensor_read` grabs the active
  window title after a click) and folds the text into the observation. **No
  LLM call is made here** — the text rides along in the *same* next-turn
  observation the acting LLM already consumes, so this tier costs zero extra
  calls. Judgment is left entirely to that next turn; `VerifyResult.ok` is
  `None` for this tier by design, not a placeholder bug.

**Wiring point:** `agentic_mixin.py::run_loop`, immediately after computing
the tool-result observation string, before the dedup-prefix/`[STATE]` snapshot
folding. `verify_action()` is called unconditionally per step; it returns
`None` for any unregistered action or any tier whose required sensor callable
the worker didn't supply, so unmodified workers behave exactly as before.

**Nothing here ever touches `evidence`.** This is intentional — sending
every per-action grounding signal upstream to the reviewer/orchestrator would
flood it with worker-internal noise. The worker owns synthesizing its own
final evidence; tiered verify only helps it get there with fewer wrong turns.
Confirmed by `test_nothing_persisted_to_evidence_across_all_tiers`.

| Component | File |
|---|---|
| `ActionTier`, `TIER_REGISTRY`, `verify_action()` | `trinity_pilot/workers/action_verification.py` |
| Loop wiring + hook methods | `trinity_pilot/workers/agentic_mixin.py` |
| Concrete sensor overrides | `trinity_pilot/workers/desktop_worker.py::_action_sensor_check/_action_sensor_read` |
| Dependency | `tenacity>=9.0.0` (`pyproject.toml`) |
| Tests | `tests/unit/test_action_verification.py`, `tests/unit/test_terminal_worker.py`, `tests/unit/test_desktop_worker.py` |

## Status

Both mechanisms are implemented and unit-tested (386/386 unit tests passing,
including the new tests for both subsystems). **Neither has run against a
live VM scenario yet** — that requires `scripts/vm_pipeline.py` against a
booted VM, which this build session did not have access to. Do not claim
end-to-end validation in the thesis until a VM smoke run (checklist pass,
checklist fail, real eventually-tier wait on a cold launch) has actually been
observed; see `docs/contribution-ledger.md` for the corresponding claim status.
