from __future__ import annotations

from trinity_pilot.audit.runner import (
    format_dag_parallel_ablation_table,
    run_dag_parallel_ablation,
)


async def test_dag_parallel_ablation_reports_four_distinct_shapes():
    rows = await run_dag_parallel_ablation()
    fractions = {row["cross_domain_independence_fraction"] for row in rows}

    assert len(rows) == 4
    assert len(fractions) == 4
    assert all(row["wall_clock_savings_ratio"] > 0 for row in rows)
    assert rows[-1]["wall_clock_savings_ratio"] > rows[0]["wall_clock_savings_ratio"]
    assert all(set(row["statuses"].values()) == {"passed"} for row in rows)

    table = format_dag_parallel_ablation_table(rows)
    assert "cross_domain_independence_fraction" in table
    assert "wall_clock_savings_ratio" in table
