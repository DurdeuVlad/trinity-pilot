# Trinity Pilot Contribution Ledger

## Purpose

This document keeps thesis claims tied to current code, cited literature, and
actual evidence. If a claim cannot be traced to implementation and paper
evidence, it is downgraded here before it becomes a defense problem.

Local research PDFs under `docs/research/` are currently placeholder files with
the text `PDF moved from root.` Paper sections are therefore treated as pending
verification unless a task brief names the section explicitly.

## Claim Status Legend

- `Ahead of cited SOTA`
- `Adaptation / parity with narrower setting`
- `Engineering contribution`
- `Implementation cleanup`
- `Unproven / do not claim yet`

## Contribution Matrix

| ID | Claim | Status | Code references | SOTA references | Evidence now | Evidence still needed | Defense wording |
|---|---|---|---|---|---|---|---|
| C1 | Programmatic reviewer floor prevents an LLM judge from accepting file-only or missing-artifact delivery as task success, generalized with a planner-authored verification checklist for objectives the two hardcoded floors don't cover. | Engineering contribution; ahead of 4/5 cited papers, parity with the 5th — verified against arXiv HTML text (see SOTA verification note below; spot-check before defense). Checklist extension is implemented and unit-tested (`tests/unit/test_reviewer_checklist.py`, 8/8 passing); **not yet validated on a live VM run** — do not claim end-to-end proof until that happens. | `trinity_pilot/reviewer/reviewer.py::ObjectiveReviewer.review`; `trinity_pilot/reviewer/reviewer.py::ObjectiveReviewer.floor_override_rate`; `trinity_pilot/audit/desktop_probe.py::verify_visible_text`; `trinity_pilot/workers/write_verification.py::verify_and_write_file`; `trinity_pilot/core/types.py::ChecklistItem`; `trinity_pilot/reviewer/checklist.py::evaluate_checklist` | Agent S (`2410.08164`, §3.1.3 Self-Evaluator — pure LLM judgment from trajectory, no deterministic check); PC-Agent (`2502.14282`, §2.4.1 Reflection Agent — pure VLM screenshot-diff, no deterministic check); MobileAgent-v2 (`2406.01014`, §3.5 Reflection Agent — pure VLM screenshot-diff, no deterministic check); UFO2 (`2504.14603`, §3.7 has deterministic UIA preconditions but §5.6 final task verdict is still LLM/CoT-based with no override floor); UFO3 (`2511.11332`, §8.4 Composable Execution Logic — claims real deterministic environment-state verification, the one genuine close competitor) | Deterministic floors for `write_file_failures` and `visible_text_probe.file_only_delivery == True` now span all 4 domain workers (desktop, terminal, browser, single-agent), plus shadow floor counters (`floor_override_rate`). | Manually confirm UFO3 §8.4 in the raw PDF (current finding is from an automated HTML summarization pass, not a direct read); run the floor-override-rate measurement on a VM batch. | Trinity Pilot's deterministic evidence floor outranks Agent S/PC-Agent/MobileAgent-v2, which rely entirely on LLM or VLM judgment with no override-proof floor. Against UFO2 it improves on the post-hoc LLM evaluator specifically (UFO2's runtime preconditions are pre-action, not artifact verification). Against UFO3, claim parity/narrower scope only, not superiority, until §8.4 is confirmed by direct read. |
| C2 | Static DAG dispatch runs cross-domain-independent objectives concurrently and preserves unrelated partial progress after a failure. | Adaptation / parity with narrower setting; ahead of UFO2 specifically on concurrency | `trinity_pilot/planner/dag.py::infer_cross_domain_independence`; `trinity_pilot/planner/dag.py::resolve_execution_order`; `trinity_pilot/orchestrator/scheduler.py::DAGScheduler`; `trinity_pilot/orchestrator/engine.py::AsyncTaskOrchestrator.run` | UFO2 (`2504.14603`, §3.1-3.2 — centralized HostAgent, FSM-serialized, no parallel dispatch at all); UFO3 (`2511.11332`, §4.4 Runtime Dynamism — TaskConstellation is mutable at runtime, edges inserted/removed live; §6.2 — concurrent edits while other tasks run) | `DAGScheduler` dispatches ready nodes with `asyncio.create_task`, uses `asyncio.Lock` around ready-set mutation, marks only dependent subtrees skipped after failure, and enforces modular domain exclusion (e.g. exclusive desktop execution). | Wall-clock ablation on representative multi-objective tasks; manually confirm UFO2 §3.1-3.2 and UFO3 §4.4/§6.2 from raw PDF text. | Trinity Pilot is ahead of UFO2, which has zero concurrent subtask dispatch. Against UFO3's continuously-mutating runtime graph, Trinity Pilot's static precomputed DAG is narrower scope by design — do not claim UFO3-style dynamic graph mutation. |
| C4 | MCP extensibility boundary separates sensor, action, control, and task tools so observer/reviewer consumers can receive sensor-only views across servers. | Engineering contribution | `trinity_pilot/mcp/tool_registry.py::ToolMetadata`; `trinity_pilot/mcp/tool_registry.py::sensor_only_tools`; `trinity_pilot/mcp/browser_server.py::TOOL_MANIFEST`; `trinity_pilot/mcp/desktop_server.py::TOOL_MANIFEST`; `trinity_pilot/mcp/terminal_server.py::TOOL_MANIFEST`; `trinity_pilot/mcp/desktop_automation_server.py::TOOL_MANIFEST`; `trinity_pilot/mcp/sensor_server.py::TOOL_MANIFEST` | MCP specification/reference, citation pending; no direct SOTA comparison claimed | Tool manifests label tools as `sensor`, `action`, `control`, or `task`; `sensor_only_tools()` filters multiple manifests; cross-cutting sensors live in `sensor_server.py` while domain sensors remain in domain servers. | Cite exact MCP reference/version; confirm tests cover multi-server filtering and no sensor duplication in the central sensor server. | Trinity Pilot exposes an MCP metadata boundary that lets consumers build sensor-only tool views without duplicating every domain-specific sensor into one server. |
| C5 | Mid-episode reflection can inject live reflection when the worker repeats the same tool call, generalized to a tiered verify-after-every-action design. | Adaptation / parity with narrower setting. The generalized tiered design (deterministic / eventually-consistent / LLM-grounded) is now **implemented and unit-tested** (`tests/unit/test_action_verification.py`, 15/15 passing; wired into the shared ReAct loop in `agentic_mixin.py`; concrete sensor overrides demonstrated in `desktop_worker.py` for `launch_app`/`click_button`). **Not yet validated on a live VM run** — do not claim the coverage-parity differentiator until that happens. | `trinity_pilot/workers/agentic_mixin.py` around the dedup guard and the `verify_action()` call site; `trinity_pilot/memory/reflection.py::ReflectionStore`; `trinity_pilot/workers/action_verification.py::ActionTier/TIER_REGISTRY/verify_action`; `trinity_pilot/workers/desktop_worker.py::_action_sensor_check/_action_sensor_read` | Agent S (`2410.08164`, §3.1.2 Trajectory Reflector — continuous throughout the episode, not failure-triggered); PC-Agent (`2502.14282`, §2.4.1 Reflection Agent — continuous per-action screenshot-diff, pure VLM); MobileAgent-v2 (`2406.01014`, §3.5 Reflection Agent — continuous per-action screenshot-diff, pure VLM) | ReAct worker step detects repeated tool call (2nd identical call) under opt-in metadata, runs a mid-episode reflection LLM query, and injects the live suggestion into observation. | Manually confirm Agent S §3.1.2, PC-Agent §2.4.1, MobileAgent-v2 §3.5 from raw PDF text; implement and test the generalized tiered design before claiming parity. | As shipped today, this is narrower than Agent S/PC-Agent/MobileAgent-v2, all of which reflect after every action, not just on a repeat. The designed-but-unbuilt tiered version would reach parity on coverage while adding a differentiator none of the three have: deterministic/eventually-consistent checks for checkable actions, reserving an LLM call only for genuinely fuzzy ones — do not claim this differentiator until it ships and is tested. |
| C6 | VM/probe cache and SSH robustness make benchmark runs less stale and less fragile. | Implementation cleanup | `scripts/vm_pipeline.py::find_cached_results`; `scripts/vm_pipeline.py::_inject_meta`; `scripts/vm_pipeline.py::resolve_model`; `scripts/vm_pipeline.py::scp_to_vm`; `scripts/vm_pipeline.py::scp_from_vm` | No SOTA paper claim; internal evaluation infrastructure only | Cache lookup now includes `worker_model` and `planner_model`; result metadata records both models; SCP helpers retry timeout cases. | Run the standalone cache fixture and a VM-backed cache smoke when the VM is available. | This improves evaluation hygiene; it is not a thesis novelty claim. |

## SOTA verification note

The SOTA references above came from an automated arXiv-HTML fetch-and-summarize pass (a smaller model reading the rendered HTML page and answering targeted questions), not a direct read of the source PDFs by a human or by the main model. Section numbers and quotes are strong leads, not certified citations. Spot-check UFO3 §8.4 (C1's closest competitor) and Agent S §3.1.2 (C5's strongest comparator) against the raw PDF text before using these in the defense.

## Detailed Notes

### C1 - Programmatic Reviewer Floor

`trinity_pilot/reviewer/reviewer.py::ObjectiveReviewer.review` checks
`evidence["write_file_failures"]` before the LLM reviewer. It also checks
`evidence["visible_text_probe"]` and fails a desktop objective when
`file_only_delivery` is true and the probe did not pass. Both paths return
`FailureReason.MISSING_ARTIFACT` with a concrete retry hint before calling the
LLM. `ObjectiveReviewer.floor_override_rate` tracks how often a shadow LLM would
have passed when the floor fired. `trinity_pilot/workers/write_verification.py::verify_and_write_file`
is the shared helper that populates these evidence fields; it is now called from
all 4 domain workers (desktop, terminal, browser, single-agent), not just desktop.

SOTA check (arXiv HTML pass, pending manual confirm): Agent S §3.1.3, PC-Agent
§2.4.1, and MobileAgent-v2 §3.5 all use pure LLM/VLM judgment with no
deterministic check that can override the judge — Trinity Pilot's floor is a
real differentiator against all three. UFO2 §3.7 has deterministic
*precondition* checks (`is_enabled`/`is_visible`) before an action runs, but its
final task-success verdict (§5.6) is still LLM/CoT-based with no override floor
— differentiation holds but is narrower than against the first three. UFO3
§8.4 explicitly claims real deterministic environment-state verification ("applies
commands... deterministically," gathers real environment data rather than LLM
log interpretation) — this is the one paper where superiority is not safe to
claim without reading the raw section directly.

Do not say: "Trinity Pilot has a generally superior reviewer." Say it has a
deterministic floor with no LLM override path, ahead of Agent S/PC-Agent/MobileAgent-v2
and UFO2's final verdict step, and parity (not superiority) against UFO3 until
§8.4 is manually confirmed.

### C2 - Static DAG Dispatch And Partial Progress

`trinity_pilot/planner/dag.py::infer_cross_domain_independence` conservatively
adds same-domain dependencies when the planner leaves them blank. Cross-domain
objectives without explicit dependencies stay independent. `resolve_execution_order`
uses Kahn's algorithm for a topological order.

`trinity_pilot/orchestrator/scheduler.py::DAGScheduler` runs the static graph.
Ready objectives are dispatched as asyncio tasks, ready-set mutation is guarded
by `asyncio.Lock`, and failed objectives skip only their dependent subtree via
`_mark_blocked_subtree`. To prevent focus-stealing and keyboard/mouse focus collisions,
the scheduler enforces a modular exclusion policy: exclusive domains (e.g. `desktop`
and `mixed`) cannot run in parallel with any other domain.

What can be claimed now: static-DAG concurrent dispatch, partial progress
after failure, and domain-level exclusion safety, and concurrency that UFO2
(`2504.14603` §3.1-3.2, centralized HostAgent + FSM serialization) does not have
at all. What cannot be claimed: UFO3-style dynamic graph mutation, runtime
replanning (`2511.11332` §4.4/§6.2 — TaskConstellation is mutable at runtime,
edges inserted/removed live, concurrent edits while other tasks run), or general
multi-agent superiority.

Do not say: "dynamic Constellation-style orchestration." Say "static precomputed
DAG dispatch with modular exclusion safety and narrower scope than UFO3, ahead of
UFO2's sequential FSM dispatch."

### C4 - MCP Extensibility Boundary

`trinity_pilot/mcp/tool_registry.py::ToolMetadata` validates tool metadata and
restricts kind to `sensor`, `action`, `control`, or `task`.
`sensor_only_tools()` filters manifests from multiple servers. Browser,
desktop, terminal, desktop automation, and central sensor servers each expose
`TOOL_MANIFEST` entries.

The important architectural point is not benchmark performance. The point is
that reviewer or observer consumers can mount all relevant servers and filter
to read-only sensors without forcing every domain sensor into
`sensor_server.py`.

What can be claimed now: a metadata-level sensor/action boundary exists. What
cannot be claimed: benchmark superiority, security isolation, or complete
policy enforcement.

Do not say: "safe sandboxing." Say "tool metadata supports sensor-only views."

### C5 - Mid-Episode Reflection

`trinity_pilot/workers/agentic_mixin.py` has a dedup guard around repeated tool
calls. It warns on the second identical call and blocks on the third or later
call. `trinity_pilot/memory/reflection.py::ReflectionStore` persists
inter-attempt reflections after failures.

The mid-episode reflection is implemented at the second identical tool call.
If enabled via `spec.metadata["mid_episode_reflection"]`, it fires a side-channel ReAct
reflection LLM call, obtains a one-sentence recovery hint, and appends it to the warning
observation.

What can be claimed now: intra-attempt reflection triggered at repeated calls
under opt-in metadata. What cannot be claimed: general-purpose continuous critique
or Agent S-style general reflector.

SOTA check (arXiv HTML pass, pending manual confirm): Agent S §3.1.2 (Trajectory
Reflector — runs continuously throughout the episode, not failure/repeat-triggered),
PC-Agent §2.4.1 and MobileAgent-v2 §3.5 (both reflect after *every* action via
screenshot-diff, pure VLM judgment) are all broader-coverage than Trinity Pilot's
current dedup-triggered version. A generalized design — verify after every action
using a 3-tier dispatch (deterministic check for write_file/run_command-style
actions, poll-with-backoff for eventually-consistent actions like launch_app/navigate,
and an LLM-grounded check fed into the *same* next-turn observation — no extra LLM
call — for genuinely fuzzy actions like click_button) was discussed and would reach
coverage parity with PC-Agent/MobileAgent-v2 while adding a differentiator none of
the three have: zero LLM calls spent on deterministic/eventually-consistent actions.
This design is not yet implemented or tested.

Do not say: "continuous trajectory reflector like Agent S" or claim the tiered
differentiator until the generalized design above actually ships and is tested.
As shipped today, say only "narrow mid-episode reflection triggered by the dedup
warning" — this is narrower than all three cited papers, not parity.

### C6 - VM/Probe/Model-Cache Infrastructure

`scripts/vm_pipeline.py::find_cached_results` now matches cache entries on
`app_hash`, `suite`, `runs`, `worker_model`, and `planner_model`.
`_inject_meta` writes those model fields into result metadata. `resolve_model`
normalizes CLI/env/default model choices. The SCP helpers retry timeouts for
VM transfer reliability.

What can be claimed now: the benchmark pipeline is less likely to reuse stale
results across model changes. What cannot be claimed: any SOTA improvement.

Do not say: "novel evaluation method." Say "evaluation infrastructure cleanup."

## Claims To Avoid

- Do not claim UFO3-style dynamic graph mutation or runtime graph repair; the
  current scheduler runs a static precomputed DAG.
- Do not claim reviewer superiority over UFO3 specifically until §8.4 is read
  directly from the raw PDF, not just the arXiv-HTML summarization pass. Superiority
  over Agent S, UFO2 (final-verdict step), MobileAgent-v2, and PC-Agent is supported
  by section-level findings above but still wants a manual spot-check before defense.
- Do not claim MCP metadata filtering is a security boundary. It is a tool-view
  and extensibility boundary.
- Do not count W0 infrastructure fixes as thesis novelty.
- C5's generalized tiered design is implemented and unit-tested as of 2026-06-29,
  but do not claim Agent S/PC-Agent/MobileAgent-v2 coverage parity in the thesis
  until it has run against a live VM scenario — unit tests with mocked sensors
  prove the dispatch logic, not real-world behavior on a real desktop/browser.
- C1's checklist extension is implemented and unit-tested as of 2026-06-29, same
  caveat — do not claim it in the defense as validated end-to-end until a VM
  smoke run has actually exercised a checklist pass and a checklist fail.
- C3 (risk-gated human query / VeriOS) is cut from this thesis's claim set — do not
  reference it in the paper.

## Update Rules

1. Any future W-stream that changes contribution strength must update this
   ledger in the same change.
2. Any new or moved implementation point must update the `Code references`
   column and the matching detailed note.
3. Any SOTA comparison must include a paper name and exact section/page once the
   full paper is available.
4. Evidence gaps stay explicit. Use `pending`, `missing`, or `do not claim`
   instead of vague confidence.
5. W0-style infrastructure work belongs here only as evaluation hygiene or
   implementation cleanup, not as a headline thesis claim.
