"""FastMCP server exposing DesktopWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.desktop_server
Internal hot-path skips this server and calls DesktopWorker directly.

MCP tools exposed
-----------------
High-level task tools:
  desktop_screenshot  — capture current desktop screenshot
  desktop_find_window — find a window and return element tree

Domain tools (mirrored from the inner ReAct loop):
  launch_app         — launch an application by executable name
  focus_window       — focus a window by title regex
  type_text          — type text into the focused window
  press_hotkey       — press a hotkey combination
  press_key          — press a single key
  write_file         — write text to an absolute path
  wait               — pause for N seconds

Control tools:
  finish             — signal objective complete or failed
  report_blocking    — signal an unresolvable blocker
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastmcp import FastMCP

from trinity_pilot.core.types import (
    DomainType,
    ObjectiveSpec,
    RiskClass,
)
from trinity_pilot.workers.desktop_worker import DesktopWorker

mcp = FastMCP(
    name="trinity-pilot-desktop",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("health://desktop")
def health() -> str:
    return "ok"


@mcp.resource("version://desktop")
def version() -> str:
    return "0.1.0"


# ---------------------------------------------------------------------------
# High-level task tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def desktop_screenshot(objective_id: str, goal: str) -> dict:
    """Take a screenshot of the current desktop and return evidence."""
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_screenshot"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["screenshot captured"],
        evidence_bundle=["screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    worker = DesktopWorker()
    return await worker.execute(spec)


@mcp.tool()
async def desktop_find_window(objective_id: str, goal: str) -> dict:
    """Find a window and return its element tree snapshot."""
    spec = ObjectiveSpec(
        objective_id=objective_id,
        goal=goal,
        dependencies=[],
        domain=DomainType.DESKTOP,
        required_capabilities=["desktop_uia"],
        risk_class=RiskClass.LOW,
        preconditions=[],
        success_tests=["window found"],
        evidence_bundle=["element_tree_snapshot", "screenshot"],
        max_attempts=1,
        rollback_or_abort_rule="abort",
    )
    worker = DesktopWorker()
    return await worker.execute(spec)


# ---------------------------------------------------------------------------
# Domain tools (mirror the inner ReAct loop tools)
# ---------------------------------------------------------------------------

@mcp.tool()
async def launch_app(app: str, args: str = "", wait: float = 1.5) -> dict:
    """Launch an application by executable name and wait for it to start."""
    import subprocess
    app_args = args.split() if args else []
    subprocess.Popen([app, *app_args])
    await asyncio.sleep(wait)
    return {"launched": app, "wait": wait}


@mcp.tool()
async def focus_window(title_re: str, wait: float = 0.5) -> dict:
    """Focus a window matching a title regex."""
    try:
        from pywinauto import Application
        application = Application(backend="uia").connect(title_re=title_re, timeout=5)
        application.top_window().set_focus()
    except Exception as exc:
        return {"focused": False, "title_re": title_re, "error": str(exc)}
    await asyncio.sleep(wait)
    return {"focused": True, "title_re": title_re}


@mcp.tool()
async def type_text(text: str, interval: float = 0.03) -> dict:
    """Type text into the currently focused window."""
    try:
        from pywinauto.keyboard import send_keys
        send_keys(text, pause=interval, with_spaces=True, with_tabs=True, with_newlines=True)
    except Exception as exc:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.write(text, interval=interval)
    await asyncio.sleep(0.1)
    return {"typed_chars": len(text)}


@mcp.tool()
async def press_hotkey(keys: str) -> dict:
    """Press a hotkey combination. keys: comma-separated e.g. 'ctrl,s'."""
    key_list = [k.strip() for k in keys.split(",")]
    try:
        from pywinauto.keyboard import send_keys
        modifier_map = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
        modifiers = "".join(modifier_map[k.lower()] for k in key_list[:-1] if k.lower() in modifier_map)
        send_keys(f"{modifiers}{key_list[-1]}")
    except Exception:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.hotkey(*key_list)
    await asyncio.sleep(0.3)
    return {"hotkey": keys}


@mcp.tool()
async def press_key(key: str) -> dict:
    """Press a single key by name e.g. 'enter', 'tab', 'escape'."""
    try:
        from pywinauto.keyboard import send_keys
        send_keys(f"{{{key.upper()}}}")
    except Exception:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.press(key)
    await asyncio.sleep(0.2)
    return {"key": key}


@mcp.tool()
async def write_file(path: str, content: str) -> dict:
    """Write text content directly to a file at an absolute path.

    Parent directories are created automatically.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "bytes_written": len(content.encode())}


@mcp.tool()
async def wait(seconds: float) -> dict:
    """Pause execution for the specified number of seconds."""
    await asyncio.sleep(seconds)
    return {"waited": seconds}


# ---------------------------------------------------------------------------
# Control tools
# ---------------------------------------------------------------------------

@mcp.tool()
def finish(status: str, summary: str) -> dict:
    """Signal that the objective is complete or definitively failed.

    status: "success" | "failure"
    summary: one-paragraph description of outcome.
    """
    if status not in ("success", "failure"):
        status = "failure"
    return {"control": "finish", "status": status, "summary": summary}


@mcp.tool()
def report_blocking(reason: str, attempted: str = "") -> dict:
    """Signal an unresolvable blocker requiring orchestrator intervention."""
    return {"control": "report_blocking", "reason": reason, "attempted": attempted}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
