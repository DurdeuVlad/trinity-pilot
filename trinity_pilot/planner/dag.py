from __future__ import annotations

from collections import deque

from trinity_pilot.core.types import DomainType, ObjectiveSpec


class CyclicDependencyError(Exception):
    pass


def _validate_unique_ids(specs: list[ObjectiveSpec]) -> None:
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for spec in specs:
        if spec.objective_id in seen:
            duplicate_ids.append(spec.objective_id)
        seen.add(spec.objective_id)
    if duplicate_ids:
        raise ValueError(f"Duplicate objective ids found: {duplicate_ids}")


def infer_cross_domain_independence(specs: list[ObjectiveSpec]) -> list[ObjectiveSpec]:
    """Infer only the conservative same-domain fallback dependencies.

    Explicit dependencies are left untouched. Objectives with no declared
    dependency are independent across domains, but same-domain objectives stay
    sequential by depending on the immediately preceding same-domain objective.
    """
    _validate_unique_ids(specs)
    last_by_domain: dict[DomainType, str] = {}
    for spec in specs:
        if spec.dependencies:
            last_by_domain[spec.domain] = spec.objective_id
            continue
        previous_same_domain = last_by_domain.get(spec.domain)
        if previous_same_domain:
            spec.dependencies = [previous_same_domain]
        last_by_domain[spec.domain] = spec.objective_id
    return specs


def build_graph(specs: list[ObjectiveSpec]) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Build in-degree and adjacency maps from ObjectiveSpec.dependencies."""
    _validate_unique_ids(specs)
    index = {s.objective_id: s for s in specs}
    in_degree: dict[str, int] = {s.objective_id: 0 for s in specs}
    adjacency: dict[str, list[str]] = {s.objective_id: [] for s in specs}

    for spec in specs:
        # Drop dependency ids that don't match any objective in this plan instead of
        # hard-failing the whole task — the planner LLM occasionally hallucinates or
        # echoes placeholder dependency text, and a bad id from one objective
        # shouldn't crash an otherwise-valid plan.
        valid_dep_ids = [dep_id for dep_id in spec.dependencies if dep_id in index]
        for dep_id in valid_dep_ids:
            adjacency[dep_id].append(spec.objective_id)
            in_degree[spec.objective_id] += 1

    return in_degree, adjacency


def resolve_execution_order(specs: list[ObjectiveSpec]) -> list[ObjectiveSpec]:
    """Topological sort (Kahn's algorithm) by ObjectiveSpec.dependencies."""
    index = {s.objective_id: s for s in specs}
    in_degree, adjacency = build_graph(specs)

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
