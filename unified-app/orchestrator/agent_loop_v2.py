import logging
from typing import Optional
from openai import OpenAI
from orchestrator.module_clients import desktop_task, cli_task, browser_task

logger = logging.getLogger(__name__)


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "desktop_task",
            "description": "Execute desktop automation tasks (Windows UIA). Use for: launching apps, clicking UI elements, typing text, reading window content, focusing windows. Returns result from Desktop Module Service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Natural language description of the desktop task"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional additional context or state information"
                    }
                },
                "required": ["description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cli_task",
            "description": "Execute PowerShell/CLI commands. Use for: file operations, listing directories, reading files, running system commands. All commands are validated against an allowlist. Returns result from CLI Module Service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Natural language description of the CLI task"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional additional context or state information"
                    }
                },
                "required": ["description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_task",
            "description": "Execute web browser automation tasks (Playwright). Use for: navigating URLs, clicking web elements, reading page content, filling forms. Browser session persists across calls. Returns result from Browser Module Service.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Natural language description of the browser task"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional additional context or state information"
                    }
                },
                "required": ["description"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "desktop_task": desktop_task,
    "cli_task": cli_task,
    "browser_task": browser_task
}


async def execute_task(
    client: OpenAI,
    user_request: str,
    max_iterations: int = 6
) -> dict:
    """
    Execute a user task using GPT-4o with module service tools.
    
    Args:
        client: OpenAI client instance
        user_request: Natural language task description
        max_iterations: Maximum agent loop iterations (default 6)
        
    Returns:
        dict with keys: result (str), iterations (int), error (Optional[str])
    """
    logger.info(f"Starting orchestrator task: {user_request}")
    
    system_prompt = """You are Trinity Pilot, a desktop automation orchestrator.

You have access to three module services:
- desktop_task: Windows desktop automation (UIA)
- cli_task: PowerShell/CLI commands (allowlist-validated)
- browser_task: Web browser automation (Playwright)

Guidelines:
1. Prefer single-call solutions when possible
2. Only decompose multi-domain tasks (e.g., "search Google, then save result to file")
3. Pass context between calls when needed
4. If a module returns an error, report it clearly to the user
5. Complete tasks efficiently with minimal tool calls

Execute the user's task using the appropriate module service(s)."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_request}
    ]
    
    iterations = 0
    
    for iteration in range(max_iterations):
        iterations += 1
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            messages.append(message)
            
            if not message.tool_calls:
                result_text = message.content or ""
                logger.info(f"Task completed in {iterations} iterations")
                return {
                    "result": result_text,
                    "iterations": iterations,
                    "error": None
                }
            
            for tool_call in message.tool_calls:
                function_name = tool_call.function.name
                function_args = eval(tool_call.function.arguments)
                
                logger.info(f"Calling {function_name}: {function_args.get('description', '')}")
                
                tool_function = TOOL_FUNCTIONS.get(function_name)
                if not tool_function:
                    tool_result = {
                        "result": "",
                        "steps_taken": 0,
                        "error": f"Unknown tool: {function_name}"
                    }
                else:
                    tool_result = await tool_function(**function_args)
                
                result_str = f"Result: {tool_result.get('result', '')}"
                if tool_result.get('error'):
                    result_str += f"\nError: {tool_result['error']}"
                result_str += f"\nSteps taken: {tool_result.get('steps_taken', 0)}"
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str
                })
        
        except Exception as e:
            logger.error(f"Error in agent loop iteration {iteration}: {e}", exc_info=True)
            return {
                "result": "",
                "iterations": iterations,
                "error": f"Agent loop error: {str(e)}"
            }
    
    logger.warning(f"Max iterations ({max_iterations}) reached")
    
    final_response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages + [{"role": "user", "content": "Please summarize what you've accomplished so far."}]
    )
    
    return {
        "result": final_response.choices[0].message.content or "Max iterations reached",
        "iterations": iterations,
        "error": "max_iterations_reached"
    }
