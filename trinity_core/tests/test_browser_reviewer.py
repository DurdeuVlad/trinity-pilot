import pytest

from trinity_core.orchestrators.browser_reviewer import BrowserReviewer


class _Adapter:
    async def get_current_url(self):
        return "https://example.com/results"


@pytest.mark.asyncio
async def test_browser_reviewer_approves_successful_log():
    reviewer = BrowserReviewer(_Adapter())
    result = await reviewer.review(
        objective="navigate and search",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "success", "content": "search result extracted"}],
    )
    assert result.approved is True


@pytest.mark.asyncio
async def test_browser_reviewer_rejects_errors():
    reviewer = BrowserReviewer(_Adapter())
    result = await reviewer.review(
        objective="extract",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "error", "content": "failed"}],
    )
    assert result.approved is False


@pytest.mark.asyncio
async def test_browser_reviewer_rejects_extract_objective_without_extract_call():
    reviewer = BrowserReviewer(_Adapter())
    result = await reviewer.review(
        objective="extract all products",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "success", "content": "navigated to page"}],
    )
    assert result.approved is False
    assert "extract" in result.feedback.lower()


@pytest.mark.asyncio
async def test_browser_reviewer_rejects_navigate_without_url():
    class _NoUrlAdapter:
        async def get_current_url(self):
            return ""

    reviewer = BrowserReviewer(_NoUrlAdapter())
    result = await reviewer.review(
        objective="navigate to docs",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "success", "content": "navigated"}],
    )
    assert result.approved is False


@pytest.mark.asyncio
async def test_browser_reviewer_rejects_search_without_results():
    reviewer = BrowserReviewer(_Adapter())
    result = await reviewer.review(
        objective="search for Python tutorials",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "success", "content": "typed query"}],
    )
    assert result.approved is False
    assert "search" in result.feedback.lower() or "result" in result.feedback.lower()


@pytest.mark.asyncio
async def test_browser_reviewer_feedback_is_specific():
    reviewer = BrowserReviewer(_Adapter())
    result = await reviewer.review(
        objective="extract items",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "error", "content": "timeout"}],
    )
    assert result.approved is False
    assert len(result.feedback) > 10
