from __future__ import annotations
from dataclasses import dataclass, field
import time


class BudgetExceeded(Exception):
    def __init__(self, budget_type: str) -> None:
        self.budget_type = budget_type
        super().__init__(f"Budget exceeded: {budget_type}")


@dataclass
class ObjectiveBudget:
    max_steps: int
    max_tokens: int
    wall_seconds: float
    _steps: int = field(default=0, init=False, repr=False)
    _tokens: int = field(default=0, init=False, repr=False)
    _started_at: float = field(default_factory=time.monotonic, init=False, repr=False)

    def charge_step(self) -> None:
        self._check_wall_clock()
        self._steps += 1
        if self._steps > self.max_steps:
            raise BudgetExceeded("steps")

    def charge_tokens(self, n: int) -> None:
        self._check_wall_clock()
        self._tokens += n
        if self._tokens > self.max_tokens:
            raise BudgetExceeded("tokens")

    def steps_used(self) -> int:
        return self._steps

    def tokens_used(self) -> int:
        return self._tokens

    def _check_wall_clock(self) -> None:
        if time.monotonic() - self._started_at >= self.wall_seconds:
            raise BudgetExceeded("wall_clock")

    @classmethod
    def default(cls) -> "ObjectiveBudget":
        return cls(max_steps=50, max_tokens=100_000, wall_seconds=600.0)
