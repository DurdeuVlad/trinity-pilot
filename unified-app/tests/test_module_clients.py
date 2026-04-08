import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.module_clients import desktop_task, cli_task, browser_task


@pytest.mark.asyncio
async def test_desktop_task_success():
    from unittest.mock import Mock
    
    mock_response = Mock()
    mock_response.json = Mock(return_value={
        "result": "Notepad opened",
        "steps_taken": 2,
        "error": None
    })
    mock_response.raise_for_status = Mock()
    
    with patch('orchestrator.module_clients.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        
        result = await desktop_task("Open Notepad")
        
        assert result["result"] == "Notepad opened"
        assert result["steps_taken"] == 2
        assert result["error"] is None


@pytest.mark.asyncio
async def test_cli_task_success():
    from unittest.mock import Mock
    
    mock_response = Mock()
    mock_response.json = Mock(return_value={
        "result": "file1.py\nfile2.py",
        "steps_taken": 1,
        "error": None
    })
    mock_response.raise_for_status = Mock()
    
    with patch('orchestrator.module_clients.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        
        result = await cli_task("List Python files")
        
        assert "file1.py" in result["result"]
        assert result["steps_taken"] == 1


@pytest.mark.asyncio
async def test_browser_task_success():
    from unittest.mock import Mock
    
    mock_response = Mock()
    mock_response.json = Mock(return_value={
        "result": "Navigated to example.com",
        "steps_taken": 1,
        "error": None
    })
    mock_response.raise_for_status = Mock()
    
    with patch('orchestrator.module_clients.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        
        result = await browser_task("Navigate to https://example.com")
        
        assert "example.com" in result["result"]


@pytest.mark.asyncio
async def test_desktop_task_connection_error():
    import httpx
    
    with patch('orchestrator.module_clients.httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        
        result = await desktop_task("Open Notepad")
        
        assert result["error"].startswith("service_error:")
        assert "unavailable" in result["error"].lower()
        assert result["steps_taken"] == 0


@pytest.mark.asyncio
async def test_cli_task_uses_correct_port():
    from unittest.mock import Mock
    from orchestrator.module_clients import CLI_URL
    
    mock_response = Mock()
    mock_response.json = Mock(return_value={"result": "OK", "steps_taken": 1, "error": None})
    mock_response.raise_for_status = Mock()
    
    with patch('orchestrator.module_clients.httpx.AsyncClient') as mock_client:
        mock_post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = mock_post
        
        await cli_task("Test command")
        
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert CLI_URL in call_args[0][0]


@pytest.mark.asyncio
async def test_browser_task_with_context():
    from unittest.mock import Mock
    
    mock_response = Mock()
    mock_response.json = Mock(return_value={"result": "OK", "steps_taken": 1, "error": None})
    mock_response.raise_for_status = Mock()
    
    with patch('orchestrator.module_clients.httpx.AsyncClient') as mock_client:
        mock_post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value.post = mock_post
        
        await browser_task("Click button", context="Already on login page")
        
        call_args = mock_post.call_args
        json_data = call_args[1]["json"]
        assert json_data["description"] == "Click button"
        assert json_data["context"] == "Already on login page"
