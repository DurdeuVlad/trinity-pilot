from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.planner.dag import build_graph

ObjectiveRunner = Callable[[ObjectiveSpec], Coroutine[Any, Any, dict[str, Any]]]


class DAGScheduler:
    """Run a static, pre-computed objective DAG with cross-domain parallelism.

    The graph is not mutated at runtime. This closes the old gap where Trinity
    Pilot computed a DAG and then flattened it into a sequential loop; it does
    not implement dynamic graph mutation or replanning.
    """

    EXCLUSIVE_DOMAINS: set[DomainType] = {DomainType.DESKTOP, DomainType.MIXED}


    def __init__(
        self,
        specs: list[ObjectiveSpec],
        runner: ObjectiveRunner,
        *,
        results: dict[str, Any] | None = None,
    ) -> None:
        self._specs_by_id = {spec.objective_id: spec for spec in specs}
        self._in_degree, self._adjacency = build_graph(specs)
        self._ready: set[str] = {
            objective_id for objective_id, degree in self._in_degree.items() if degree == 0
        }
        self._pending: dict[asyncio.Task[dict[str, Any]], str] = {}
        self._dispatched: set[str] = set()
        self._results: dict[str, Any] = results if results is not None else {}
        self._runner = runner
        self._lock = asyncio.Lock()

    @property
    def results(self) -> dict[str, Any]:
        return dict(self._results)

    async def run(self) -> dict[str, Any]:
        while self._ready or self._pending:
            ready_specs = await self._pop_ready()
            for spec in ready_specs:
                task: asyncio.Task[dict[str, Any]] = asyncio.create_task(self._runner(spec))
                self._pending[task] = spec.objective_id

            if not self._pending:
                break

            done, _ = await asyncio.wait(
                list(self._pending.keys()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                objective_id = self._pending.pop(task)
                result = self._task_result(task)
                self._results[objective_id] = result
                if result.get("status") == "passed":
                    await self._mark_passed(objective_id)
                elif result.get("status") == "cancelled":
                    await self._mark_blocked_subtree(objective_id, objective_id, "cancelled")
                else:
                    # A failed objective should not erase useful progress. The
                    # static DAG lets us skip only the blocked subtree while
                    # unrelated in-flight and newly-ready work keeps running.
                    await self._mark_blocked_subtree(objective_id, objective_id, "failed")

        return dict(self._results)

    async def _pop_ready(self) -> list[ObjectiveSpec]:
        async with self._lock:
            # running_domains is the set of domains of currently executing tasks
            running_domains = {self._specs_by_id[task_id].domain for task_id in self._pending.values()}

            ready_specs: list[ObjectiveSpec] = []
            objective_ids = list(self._ready)
            for objective_id in objective_ids:
                if objective_id in self._dispatched or objective_id in self._results:
                    self._ready.discard(objective_id)
                    continue

                spec = self._specs_by_id[objective_id]
                is_exclusive = spec.domain in self.EXCLUSIVE_DOMAINS

                # Check conflict with currently running tasks
                has_running_conflict = False
                for r_dom in running_domains:
                    if is_exclusive or r_dom in self.EXCLUSIVE_DOMAINS:
                        has_running_conflict = True
                        break

                if has_running_conflict:
                    continue

                # Check conflict with tasks already selected in this tick/pop batch
                has_selected_conflict = False
                for sel_spec in ready_specs:
                    if is_exclusive or sel_spec.domain in self.EXCLUSIVE_DOMAINS:
                        has_selected_conflict = True
                        break

                if has_selected_conflict:
                    continue

                self._ready.discard(objective_id)
                self._dispatched.add(objective_id)
                ready_specs.append(spec)
                running_domains.add(spec.domain)

            return ready_specs

    @staticmethod
    def _task_result(task: asyncio.Task[dict[str, Any]]) -> dict[str, Any]:
        try:
            return task.result()
        except asyncio.CancelledError:
            return {"status": "cancelled", "failure_reason": "cancelled"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "failure_reason": str(exc)}

    async def _mark_passed(self, objective_id: str) -> None:
        async with self._lock:
            for dependent_id in self._adjacency.get(objective_id, []):
                if dependent_id in self._results:
                    continue
                self._in_degree[dependent_id] -= 1
                if self._in_degree[dependent_id] == 0:
                    self._ready.add(dependent_id)

    async def _mark_blocked_subtree(
        self,
        objective_id: str,
        blocked_by: str,
        blocker_status: str,
    ) -> None:
        async with self._lock:
            stack = list(self._adjacency.get(objective_id, []))
            seen: set[str] = set()
            while stack:
                dependent_id = stack.pop()
                if dependent_id in seen:
                    continue
                seen.add(dependent_id)
                stack.extend(self._adjacency.get(dependent_id, []))
                self._ready.discard(dependent_id)
                if dependent_id in self._dispatched or dependent_id in self._results:
                    continue
                self._results[dependent_id] = {
                    "status": "skipped",
                    "reason": f"depends_on_{blocker_status}_objective:{blocked_by}",
                    "blocked_by": blocked_by,
                }
