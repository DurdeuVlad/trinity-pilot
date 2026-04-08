import pytest

from trinity_core.orchestrators.desktop_reviewer import DesktopReviewer


class _Adapter:
    pass


@pytest.mark.asyncio
async def test_desktop_reviewer_approves_happy_path():
    reviewer = DesktopReviewer(_Adapter())
    result = await reviewer.review(
        objective="open app window",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "success", "content": "open app and window visible"}],
    )
    assert result.approved is True


@pytest.mark.asyncio
async def test_desktop_reviewer_rejects_error_log():
    reviewer = DesktopReviewer(_Adapter())
    result = await reviewer.review(
        objective="open app",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "error", "content": "failed"}],
    )
    assert result.approved is False
