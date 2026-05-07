"""Fixtures for real tests."""
import os
import pytest


@pytest.fixture(autouse=True)
def require_real_flag(request):
    """Skip any test in this folder unless --real is passed."""
    if not request.config.getoption("--real", default=False):
        pytest.skip("Pass --real to run live environment tests")


@pytest.fixture
def gemini_api_key():
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    return key
