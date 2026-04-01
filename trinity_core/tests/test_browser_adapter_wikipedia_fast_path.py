"""Regression tests for BrowserAdapter semantic paragraph copy fast paths."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trinity_core.adapters.browser import BrowserAdapter, _select_first_meaningful_text
from trinity_core.models import TaskInput


@pytest.mark.asyncio
async def test_wikipedia_first_paragraph_fast_path_returns_text_output() -> None:
    prior = {"obj1": {"desc": "Open the Wikipedia page for cats.", "result": "Page opened."}}
    task = TaskInput(
        task_id="wiki-copy-1",
        description="Copy the first paragraph from the Wikipedia page.",
        domain="web",
        context={"_prior_results": prior},
    )

    with patch(
        "trinity_core.adapters.browser._extract_wikipedia_first_paragraph",
        new_callable=AsyncMock,
        return_value="The cat is a domestic species of small carnivorous mammal.",
    ) as extract_mock, patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
    ) as run_browser_task:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "wikipedia_first_paragraph"
    assert result.metadata["text_output"].startswith("The cat is a domestic species")
    assert result.execution_log[-1].details.startswith("The cat is a domestic species")
    extract_mock.assert_awaited_once_with("cats")
    run_browser_task.assert_not_called()


@pytest.mark.asyncio
async def test_generic_semantic_copy_fast_path_uses_prior_opened_url() -> None:
    prior = {"obj1": {"desc": "Open the article page.", "result": "Opened https://example.com/articles/cats"}}
    task = TaskInput(
        task_id="page-copy-1",
        description="Copy the first paragraph from the article page.",
        domain="web",
        context={"_prior_results": prior},
    )

    with patch(
        "trinity_core.adapters.browser._extract_semantic_text_from_url",
        new_callable=AsyncMock,
        return_value="Cats are curious mammals often discussed in this article.",
    ) as extract_mock, patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
    ) as run_browser_task:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "semantic_first_paragraph"
    assert result.metadata["source_url"] == "https://example.com/articles/cats"
    assert result.metadata["text_output"].startswith("Cats are curious mammals")
    extract_mock.assert_awaited_once()
    assert extract_mock.await_args.args[0] == "https://example.com/articles/cats"
    run_browser_task.assert_not_called()


@pytest.mark.asyncio
async def test_generic_semantic_copy_fast_path_uses_url_in_description() -> None:
    task = TaskInput(
        task_id="page-copy-2",
        description="Read the opening paragraph from https://example.com/blog/cats and copy it.",
        domain="web",
        context={},
    )

    with patch(
        "trinity_core.adapters.browser._extract_semantic_text_from_url",
        new_callable=AsyncMock,
        return_value="Cats have lived alongside humans for thousands of years.",
    ) as extract_mock:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "semantic_first_paragraph"
    assert result.metadata["source_url"] == "https://example.com/blog/cats"
    assert result.metadata["text_output"].startswith("Cats have lived alongside humans")
    assert extract_mock.await_args.args[0] == "https://example.com/blog/cats"


@pytest.mark.asyncio
async def test_wikipedia_open_fast_path_opens_system_browser() -> None:
    task = TaskInput(
        task_id="wiki-open-1",
        description="search",
        expected_outcome='I need to open the Wikipedia page for cats. I will use the web browser to search for "cats wikipedia".',
        domain="web",
        context={},
    )

    with patch(
        "trinity_core.adapters.browser._open_wikipedia_topic_in_browser",
        return_value="https://en.wikipedia.org/wiki/cats",
    ) as open_mock, patch(
        "trinity_core.adapters.browser.run_browser_task",
        new_callable=AsyncMock,
    ) as run_browser_task:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "wikipedia_open"
    assert result.metadata["output"] == "Opened https://en.wikipedia.org/wiki/cats"
    open_mock.assert_called_once_with("cats")
    run_browser_task.assert_not_called()


@pytest.mark.asyncio
async def test_wikipedia_open_fast_path_infers_topic_from_search_query() -> None:
    task = TaskInput(
        task_id="wiki-open-2",
        description="Search the web for cats wikipedia",
        domain="web",
        context={},
    )

    with patch(
        "trinity_core.adapters.browser._open_wikipedia_topic_in_browser",
        return_value="https://en.wikipedia.org/wiki/cats",
    ) as open_mock:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "wikipedia_open"
    open_mock.assert_called_once_with("cats")


@pytest.mark.asyncio
async def test_wikipedia_open_fast_path_infers_topic_from_navigate_wording() -> None:
    task = TaskInput(
        task_id="wiki-open-3",
        description="Open Wikipedia and navigate to the 'Cats' page.",
        domain="web",
        context={},
    )

    with patch(
        "trinity_core.adapters.browser._open_wikipedia_topic_in_browser",
        return_value="https://en.wikipedia.org/wiki/cats",
    ) as open_mock:
        result = await BrowserAdapter().execute(task)

    assert result.status == "success"
    assert result.metadata["fast_path"] == "wikipedia_open"
    open_mock.assert_called_once_with("Cats")


def test_select_first_meaningful_text_skips_empty_and_short_candidates() -> None:
    candidates = [
        "",
        "   ",
        "Cats",
        "The cat, also referred to as the domestic cat, is a small carnivorous mammal.[1]",
        "Later paragraph",
    ]

    selected = _select_first_meaningful_text(candidates)

    assert selected == "The cat, also referred to as the domestic cat, is a small carnivorous mammal."


def test_select_first_meaningful_text_falls_back_to_first_nonempty_candidate() -> None:
    candidates = ["", "Short note", "Another short note"]

    selected = _select_first_meaningful_text(candidates)

    assert selected == "Short note"
