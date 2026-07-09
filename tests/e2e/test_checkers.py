import pytest
import json
from pathlib import Path
from tests.e2e.checkers import FileExistsCheck, FileContentContainsCheck, JsonFormatCheck, CheckResult
from tests.e2e.benchmark import BenchmarkTest

class MockAppDriver:
    def __init__(self):
        self.prompts = []
        self.wait_calls = []
        self.infra_checkpoints = {"execution_started": True}

    def submit(self, text: str):
        self.prompts.append(text)

    def wait_for(self, targets, timeout):
        self.wait_calls.append((targets, timeout))
        return "Ready"

class DummyBenchmark(BenchmarkTest):
    def __init__(self, driver, prompt, checkers):
        super().__init__(driver)
        self.prompt = prompt
        self.checkers = checkers

    def get_prompt(self) -> str:
        return self.prompt

    def get_checkers(self) -> list:
        return self.checkers

def test_file_exists_check(tmp_path):
    existing = tmp_path / "exists.txt"
    existing.touch()
    not_existing = tmp_path / "does_not_exist.txt"

    c1 = FileExistsCheck(existing)
    res1 = c1.check()
    assert res1.success is True
    assert "File exists" in res1.message

    c2 = FileExistsCheck(not_existing)
    res2 = c2.check()
    assert res2.success is False
    assert "not found" in res2.message

def test_file_content_contains_check(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello world", encoding="utf-8")

    c1 = FileContentContainsCheck(f, "world")
    res1 = c1.check()
    assert res1.success is True

    c2 = FileContentContainsCheck(f, "world", case_sensitive=True)
    assert c2.check().success is True

    c3 = FileContentContainsCheck(f, "World", case_sensitive=True)
    assert c3.check().success is False

    c4 = FileContentContainsCheck(f, "World", case_sensitive=False)
    assert c4.check().success is True

def test_json_format_check(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps({"a": 1, "b": "test"}), encoding="utf-8")

    c1 = JsonFormatCheck(f, ["a", "b"])
    res1 = c1.check()
    assert res1.success is True

    c2 = JsonFormatCheck(f, ["a", "c"])
    res2 = c2.check()
    assert res2.success is False
    assert "missing_keys" in res2.details

def test_benchmark_lifecycle_simulation():
    driver = MockAppDriver()
    checkers = [FileExistsCheck("dummy")]
    bench = DummyBenchmark(driver, "run test", checkers)

    # Let's mock a checker check to always be success for dummy file existence
    checkers[0].check = lambda: CheckResult(True, "Mocked success")

    results = bench.run()
    assert len(results) == 1
    assert results[0].success is True
    assert driver.prompts == ["run test", "yes"]
    assert len(driver.wait_calls) == 2
