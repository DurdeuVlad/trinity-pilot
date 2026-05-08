from __future__ import annotations

from collections import deque

from trinity_pilot.core.types import ObjectiveSpec


class CyclicDependencyError(Exception):
    pass


def resolve_execution_order(specs: list[ObjectiveSpec]) -> list[ObjectiveSpec]:
    """Topological sort (Kahn's algorithm) by ObjectiveSpec.dependencies."""
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for spec in specs:
        if spec.objective_id in seen:
            duplicate_ids.append(spec.objective_id)
        seen.add(spec.objective_id)
    if duplicate_ids:
        raise ValueError(f"Duplicate objective ids found: {duplicate_ids}")

    index = {s.objective_id: s for s in specs}
    in_degree: dict[str, int] = {s.objective_id: 0 for s in specs}
    adjacency: dict[str, list[str]] = {s.objective_id: [] for s in specs}

    for spec in specs:
        for dep_id in spec.dependencies:
            if dep_id not in index:
                raise ValueError(
                    f"Objective '{spec.objective_id}' depends on unknown id '{dep_id}'"
                )
            adjacency[dep_id].append(spec.objective_id)
            in_degree[spec.objective_id] += 1

    queue: deque[str] = deque(
        obj_id for obj_id, deg in in_degree.items() if deg == 0
    )
    order: list[ObjectiveSpec] = []

    while queue:
        obj_id = queue.popleft()
        order.append(index[obj_id])
        for dependent_id in adjacency[obj_id]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                queue.append(dependent_id)

    if len(order) != len(specs):
        cycle_ids = [
            obj_id for obj_id, deg in in_degree.items() if deg > 0
        ]
        raise CyclicDependencyError(
            f"Cyclic dependency detected among objectives: {cycle_ids}"
        )

    return order
