import pytest

from trinity_core.orchestrators.cli_reviewer import CLIReviewer


class _Adapter:
    pass


@pytest.mark.asyncio
async def test_cli_reviewer_approves_output():
    reviewer = CLIReviewer(_Adapter())
    result = await reviewer.review(
        objective="check output",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "success", "content": "output contains done"}],
    )
    assert result.approved is True


@pytest.mark.asyncio
async def test_cli_reviewer_rejects_error():
    reviewer = CLIReviewer(_Adapter())
    result = await reviewer.review(
        objective="run command",
        definition_of_done="",
        execution_log=[{"role": "tool", "status": "error", "content": "bad"}],
    )
    assert result.approved is False
