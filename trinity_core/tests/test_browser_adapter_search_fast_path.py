"""Regression tests for BrowserAdapter page-title and search fast paths."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_core.adapters.browser import BrowserAdapter
from trinity_core.models import TaskInput


@pytest.mark.asyncio
async def test_page_title_fast_path_uses_prior_opened_url() -> None:
    prior = {"obj1": {"desc": "Open the page at https://example.com", "result": "Opened https://example.com"}}
    task = TaskInput(
        task_id="page-title-1",
        description="Extract the title from the webpage's HTML.",
        domain="web",
        context={"_prior_results": prior},
    )

    with patch(
        "trinity_core.adapters.browser._extract_page_title_from_url",
        new_callable=AsyncMock,
        return_value="Example Domain",
    ) as title_mock, patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
    ) as run_browser_task:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "page_title"
    assert result.metadata["page_title"] == "Example Domain"
    assert result.metadata["source_url"] == "https://example.com"
    title_mock.assert_awaited_once_with("https://example.com")
    run_browser_task.assert_not_called()


@pytest.mark.asyncio
async def test_search_fast_path_returns_first_result_for_search_objective() -> None:
    task = TaskInput(
        task_id="search-fast-1",
        description="Search for 'Python documentation' using a web browser",
        domain="web",
        context={},
    )

    with patch(
        "trinity_core.adapters.browser._extract_first_search_result_title",
        new_callable=AsyncMock,
        return_value=("Welcome to Python.org", "https://duckduckgo.com/?q=Python%20documentation&ia=web"),
    ) as search_mock, patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
    ) as run_browser_task:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "search"
    assert result.metadata["query"] == "Python documentation"
    assert "Welcome to Python.org" in result.metadata["output"]
    search_mock.assert_awaited_once_with("Python documentation")
    run_browser_task.assert_not_called()


@pytest.mark.asyncio
async def test_search_fast_path_uses_prior_query_for_followup_title_objective() -> None:
    prior = {
        "obj1": {
            "desc": "Search for 'Python programming language' using a web browser.",
            "result": "Successfully searched for 'Python programming language' using DuckDuckGo.",
        }
    }
    task = TaskInput(
        task_id="search-fast-2",
        description="Extract the title of the first search result.",
        domain="web",
        context={"_prior_results": prior},
    )

    with patch(
        "trinity_core.adapters.browser._extract_first_search_result_title",
        new_callable=AsyncMock,
        return_value=("Python (programming language) - Wikipedia", "https://duckduckgo.com/?q=Python%20programming%20language&ia=web"),
    ) as search_mock, patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
    ) as run_browser_task:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "search"
    assert result.metadata["first_result_title"] == "Python (programming language) - Wikipedia"
    assert result.metadata["output"] == "Python (programming language) - Wikipedia"
    search_mock.assert_awaited_once_with("Python programming language")
    run_browser_task.assert_not_called()
