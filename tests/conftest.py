import pytest

from trinity_pilot.memory.db import open_db


def pytest_addoption(parser):
    parser.addoption(
        "--real",
        action="store_true",
        default=False,
        help="Run real tests that require live environment (Gemini API, browser, etc.)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real: mark test as requiring live environment — only runs with --real flag",
    )
    config.addinivalue_line(
        "markers",
        "vm_official: canonical VM failure/adversarial suite",
    )


def pytest_collection_modifyitems(config, items):
    explicit_live_audit = any("test_live_e2e_audit.py" in str(arg) for arg in config.args)
    if not config.getoption("--real"):
        skip_real = pytest.mark.skip(reason="Pass --real to run live environment tests")
        for item in items:
            if explicit_live_audit and ("live_audit" in item.keywords or item.fspath.basename == "test_live_e2e_audit.py"):
                continue
            if "real" in item.keywords or item.fspath.basename.startswith("test_") and "tests/real" in str(item.fspath):
                item.add_marker(skip_real)


@pytest.fixture
def in_memory_db():
    conn = open_db(":memory:")
    yield conn
    conn.close()
