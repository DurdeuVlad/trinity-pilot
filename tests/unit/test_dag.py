import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.planner.dag import (
    CyclicDependencyError,
    infer_cross_domain_independence,
    resolve_execution_order,
)


def _spec(
    obj_id: str,
    deps: list[str],
    domain: DomainType = DomainType.BROWSER,
) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id=obj_id,
        goal=f"Do {obj_id}",
        dependencies=deps,
        domain=domain,
        required_capabilities=["cap"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["done"],
        evidence_bundle=["screenshot"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


class TestResolveExecutionOrder:
    def test_single_objective_no_deps(self):
        specs = [_spec("a", [])]
        ordered = resolve_execution_order(specs)
        assert [s.objective_id for s in ordered] == ["a"]

    def test_linear_chain(self):
        # c depends on b, b depends on a → order: a, b, c
        specs = [_spec("c", ["b"]), _spec("b", ["a"]), _spec("a", [])]
        ordered = resolve_execution_order(specs)
        ids = [s.objective_id for s in ordered]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_parallel_objectives_all_included(self):
        # b and c both depend on a; d depends on both b and c
        specs = [
            _spec("a", []),
            _spec("b", ["a"]),
            _spec("c", ["a"]),
            _spec("d", ["b", "c"]),
        ]
        ordered = resolve_execution_order(specs)
        ids = [s.objective_id for s in ordered]
        assert len(ids) == 4
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_cycle_raises(self):
        specs = [_spec("a", ["b"]), _spec("b", ["a"])]
        with pytest.raises(CyclicDependencyError):
            resolve_execution_order(specs)

    def test_unknown_dependency_is_dropped_not_raised(self):
        # Planner LLM occasionally hallucinates a dependency id — dag.py drops
        # unknown ids instead of failing the whole plan (see dag.py comment).
        specs = [_spec("a", ["nonexistent"])]
        ids = [s.objective_id for s in resolve_execution_order(specs)]
        assert ids == ["a"]

    def test_duplicate_objective_id_raises(self):
        specs = [_spec("a", []), _spec("a", [])]
        with pytest.raises(ValueError, match="Duplicate objective ids"):
            resolve_execution_order(specs)

    def test_empty_list_returns_empty(self):
        assert resolve_execution_order([]) == []


class TestInferCrossDomainIndependence:
    def test_different_domains_without_declared_deps_stay_independent(self):
        specs = [
            _spec("browser", [], DomainType.BROWSER),
            _spec("terminal", [], DomainType.TERMINAL),
        ]

        inferred = infer_cross_domain_independence(specs)

        assert inferred[0].dependencies == []
        assert inferred[1].dependencies == []

    def test_same_domain_without_declared_deps_gets_previous_same_domain_edge(self):
        specs = [
            _spec("first", [], DomainType.BROWSER),
            _spec("other-domain", [], DomainType.TERMINAL),
            _spec("second", [], DomainType.BROWSER),
        ]

        inferred = infer_cross_domain_independence(specs)

        assert inferred[0].dependencies == []
        assert inferred[1].dependencies == []
        assert inferred[2].dependencies == ["first"]

    def test_explicit_declared_dependency_wins_regardless_of_domain(self):
        specs = [
            _spec("browser", [], DomainType.BROWSER),
            _spec("terminal", ["browser"], DomainType.TERMINAL),
        ]

        inferred = infer_cross_domain_independence(specs)

        assert inferred[1].dependencies == ["browser"]
