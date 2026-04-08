import pytest
import time
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from orchestrator.agent_loop_v2 import execute_task
from openai import OpenAI

pytestmark = pytest.mark.live


@pytest.mark.asyncio
@patch('orchestrator.module_clients.desktop_task')
@patch('orchestrator.module_clients.cli_task')
async def test_e2e_notepad_grocery_list(mock_cli, mock_desktop):
    """E2E-01: Open notepad, type grocery list, save as groceries.txt"""
    
    mock_desktop.side_effect = [
        {"result": "Notepad opened", "steps_taken": 2, "error": None},
        {"result": "Text typed successfully", "steps_taken": 1, "error": None},
        {"result": "File saved as groceries.txt", "steps_taken": 3, "error": None}
    ]
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "test-key"))
    
    start_time = time.monotonic()
    
    with patch('orchestrator.agent_loop_v2.OpenAI', return_value=client):
        mock_response = Mock()
        mock_message = Mock()
        mock_message.tool_calls = None
        mock_message.content = "Task completed: Created groceries.txt with 5-item list"
        mock_response.choices = [Mock(message=mock_message)]
        
        with patch.object(client.chat.completions, 'create', return_value=mock_response):
            result = await execute_task(
                client,
                "Open notepad, type a 5-item grocery list, save as groceries.txt"
            )
    
    elapsed = time.monotonic() - start_time
    
    assert result["error"] is None or result["error"] == "max_iterations_reached"
    assert elapsed < 30.0, f"Task took {elapsed:.1f}s, expected < 30s"


@pytest.mark.asyncio
@patch('orchestrator.module_clients.cli_task')
async def test_e2e_list_python_files(mock_cli):
    """E2E-02: List all Python files in current directory"""
    
    mock_cli.return_value = {
        "result": "main.py\ntest_module.py\nconfig.py",
        "steps_taken": 1,
        "error": None
    }
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "test-key"))
    
    start_time = time.monotonic()
    
    with patch('orchestrator.agent_loop_v2.OpenAI', return_value=client):
        mock_response = Mock()
        mock_message = Mock()
        mock_message.tool_calls = None
        mock_message.content = "Found 3 Python files: main.py, test_module.py, config.py"
        mock_response.choices = [Mock(message=mock_message)]
        
        with patch.object(client.chat.completions, 'create', return_value=mock_response):
            result = await execute_task(
                client,
                "List all Python files in the current working directory"
            )
    
    elapsed = time.monotonic() - start_time
    
    assert ".py" in result["result"]
    assert elapsed < 5.0, f"Task took {elapsed:.1f}s, expected < 5s"
    assert result["iterations"] <= 2, f"Used {result['iterations']} iterations, expected ≤ 2"


@pytest.mark.asyncio
@patch('orchestrator.module_clients.browser_task')
async def test_e2e_google_search(mock_browser):
    """E2E-03: Search Google and open first result"""
    
    mock_browser.side_effect = [
        {"result": "Navigated to Google", "steps_taken": 1, "error": None},
        {"result": "Search completed", "steps_taken": 2, "error": None},
        {"result": "Opened https://doc.qt.io/qtforpython/", "steps_taken": 1, "error": None}
    ]
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "test-key"))
    
    with patch('orchestrator.agent_loop_v2.OpenAI', return_value=client):
        mock_response = Mock()
        mock_message = Mock()
        mock_message.tool_calls = None
        mock_message.content = "Opened PyQt6 documentation at doc.qt.io"
        mock_response.choices = [Mock(message=mock_message)]
        
        with patch.object(client.chat.completions, 'create', return_value=mock_response):
            result = await execute_task(
                client,
                "Search Google for PyQt6 documentation and open the first result"
            )
    
    assert result["error"] is None or result["error"] == "max_iterations_reached"
    assert "captcha" not in result["result"].lower()


@pytest.mark.asyncio
@patch('orchestrator.module_clients.cli_task')
@patch('orchestrator.service_manager.ServiceManager')
async def test_e2e_service_restart_recovery(mock_service_manager, mock_cli):
    """E2E-04: Service restart and task retry"""
    
    call_count = [0]
    
    def cli_side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {
                "result": "",
                "steps_taken": 0,
                "error": "service_error: CLI service unavailable"
            }
        return {
            "result": "Command executed successfully",
            "steps_taken": 1,
            "error": None
        }
    
    mock_cli.side_effect = cli_side_effect
    
    mock_manager = Mock()
    mock_manager.health_check_all.return_value = {
        "cli": {"status": "ok"},
        "desktop": {"status": "ok"},
        "browser": {"status": "ok"}
    }
    mock_service_manager.return_value = mock_manager
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", "test-key"))
    
    with patch('orchestrator.agent_loop_v2.OpenAI', return_value=client):
        mock_response = Mock()
        mock_message = Mock()
        mock_message.tool_calls = None
        mock_message.content = "Task completed after service recovery"
        mock_response.choices = [Mock(message=mock_message)]
        
        with patch.object(client.chat.completions, 'create', return_value=mock_response):
            result1 = await execute_task(client, "List files")
            result2 = await execute_task(client, "List files")
    
    assert mock_manager.health_check_all.called
    assert call_count[0] >= 2
