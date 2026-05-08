import pytest

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.workers.base import WorkerError
from trinity_pilot.workers.browser_worker import BrowserWorker
from trinity_pilot.workers.desktop_worker import DesktopWorker
from trinity_pilot.workers.router import WorkerRouter
from trinity_pilot.workers.terminal_worker import TerminalWorker


def _spec(domain: DomainType) -> ObjectiveSpec:
    return ObjectiveSpec(
        objective_id="obj-1",
        goal="do something",
        dependencies=[],
        domain=domain,
        required_capabilities=["cap"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["done"],
        evidence_bundle=["screenshot"],
        max_attempts=3,
        rollback_or_abort_rule="abort",
    )


class TestWorkerRouter:
    def test_browser_domain_returns_browser_worker(self):
        router = WorkerRouter()
        worker = router.route(_spec(DomainType.BROWSER))
        assert isinstance(worker, BrowserWorker)

    def test_terminal_domain_returns_terminal_worker(self):
        router = WorkerRouter()
        worker = router.route(_spec(DomainType.TERMINAL))
        assert isinstance(worker, TerminalWorker)

    def test_desktop_domain_returns_desktop_worker(self):
        router = WorkerRouter()
        worker = router.route(_spec(DomainType.DESKTOP))
        assert isinstance(worker, DesktopWorker)

    def test_mixed_domain_raises_worker_error(self):
        router = WorkerRouter()
        with pytest.raises(WorkerError, match="MIXED"):
            router.route(_spec(DomainType.MIXED))

    def test_each_route_call_returns_fresh_instance(self):
        router = WorkerRouter()
        w1 = router.route(_spec(DomainType.BROWSER))
        w2 = router.route(_spec(DomainType.BROWSER))
        assert w1 is not w2


class TestWorkerErrorClass:
    def test_worker_error_is_exception_subclass(self):
        assert issubclass(WorkerError, Exception)

    def test_worker_error_message_preserved(self):
        err = WorkerError("something went wrong")
        assert "something went wrong" in str(err)

    def test_worker_error_can_be_raised_and_caught(self):
        import pytest
        with pytest.raises(WorkerError, match="test error"):
            raise WorkerError("test error")
