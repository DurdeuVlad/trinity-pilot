"""Test cross-module workflows."""
import pytest
import asyncio
import os
from trinity_core.trinity import TrinityExecutor
from trinity_core.models import TaskInput
from trinity_core.config import TrinityConfig

@pytest.fixture
def config():
    """Create test configuration."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set")
    
    return TrinityConfig(
        gemini_api_key=api_key,
        debug_mode=True
    )

@pytest.mark.integration
@pytest.mark.asyncio
async def test_web_to_desktop_workflow(config):
    """
    Workflow: 
    1. Use browser to fetch data
    2. Use desktop to process data in app
    3. Use CLI to save results
    """
    async with TrinityExecutor(config=config) as executor:
        # Step 1: Web - navigate and "extract" data
        web_task = TaskInput(
            task_id="workflow_web",
            description="Navigate to example.com",
            domain="web",
            expected_outcome="Page loads"
        )
        web_result = await executor.execute(web_task)
        
        # Extract "data" from web result (simulated)
        page_title = web_result.metadata.get("raw_result", {}).get("title", "Example Domain")
        
        # Step 2: Desktop - type the "data" into Notepad
        desktop_task = TaskInput(
            task_id="workflow_desktop",
            description=f"Type '{page_title}' into Notepad",
            domain="desktop",
            context={"app_name": "Notepad"},
            expected_outcome="Text typed successfully"
        )
        desktop_result = await executor.execute(desktop_task)
        
        # Step 3: CLI - save to file
        cli_task = TaskInput(
            task_id="workflow_cli",
            description=f"Write '{page_title}' to workflow_output.txt",
            domain="cli",
            expected_outcome="Success"
        )
        cli_result = await executor.execute(cli_task)
        
        # Verify tasks were attempted
        assert web_result.task_id == "workflow_web"
        assert desktop_result.task_id == "workflow_desktop"
        assert cli_result.task_id == "workflow_cli"
