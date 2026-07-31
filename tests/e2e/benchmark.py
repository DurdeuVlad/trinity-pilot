from abc import ABC, abstractmethod
from typing import List

from tests.e2e._gui_driver import AFTER_CONFIRM, AFTER_SUBMIT, AppDriver
from tests.e2e.checkers import CheckDeliverable, CheckResult


class BenchmarkTest(ABC):
    def __init__(self, driver: AppDriver) -> None:
        self.app = driver

    @abstractmethod
    def get_prompt(self) -> str:
        """Return the prompt to submit to the agent."""
        pass

    @abstractmethod
    def get_checkers(self) -> List[CheckDeliverable]:
        """Return the list of CheckDeliverable instances to run after completion."""
        pass

    def run(self, plan_timeout: float = 50.0, run_timeout: float = 120.0) -> List[CheckResult]:
        """Execute the E2E benchmark flow: submit, confirm, wait, and verify."""
        prompt = self.get_prompt()
        self.app.submit(prompt)
        
        after_submit = self.app.wait_for(AFTER_SUBMIT, timeout=plan_timeout)
        if after_submit in ("Planning failed", "Error"):
            return [CheckResult(False, f"Planning failed during E2E flow: {after_submit}")]
            
        self.app.submit("yes")
        self.app.wait_for(AFTER_CONFIRM, timeout=run_timeout)
        
        # Enforce execution started check (handled by wait_for patch)
        if not getattr(self.app, "infra_checkpoints", {}).get("execution_started", False):
             return [CheckResult(False, "Task did not start executing (stuck at Ready)")]

        results = []
        for checker in self.get_checkers():
            res = checker.check()
            results.append(res)
        return results
