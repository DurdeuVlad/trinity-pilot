"""FastMCP server exposing DesktopWorker capabilities at the product boundary.

Run: python -m trinity_pilot.mcp.desktop_server
Internal hot-path skips this server and calls DesktopWorker directly.

MCP tools exposed
-----------------
High-level task tools:
  desktop_run        — run a full agentic desktop objective

Domain sensor tools (read-only, desktop-specific):
  uia_tree          — UIA accessibility tree of focused or named window
  focused_element   — currently focused UI element details
  window_hierarchy  — all windows with z-order and visibility
  get_element_value — value/text of a specific UI element by locator
  app_state         — running state of a named application

Cross-cutting sensors (screenshot, window enumeration, clipboard) are in
sensor_server.py — NOT duplicated here.

Domain action tools (mirrored from the inner ReAct loop):
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

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.mcp.tool_registry import ToolManifest, ToolMetadata
from trinity_pilot.workers.base import WorkerBlocker, WorkerError
from trinity_pilot.workers.desktop_worker import DesktopWorker

mcp = FastMCP(
    name="trinity-pilot-desktop",
    version="0.1.0",
)

SERVER_NAME = "trinity-pilot-desktop"

TOOL_MANIFEST: ToolManifest = (
    ToolMetadata("desktop_run", SERVER_NAME, "task", "Run a full desktop objective."),
    ToolMetadata("uia_tree", SERVER_NAME, "sensor", "Read a UIA accessibility tree."),
    ToolMetadata("focused_element", SERVER_NAME, "sensor", "Read the focused UI element."),
    ToolMetadata("window_hierarchy", SERVER_NAME, "sensor", "Read desktop window hierarchy."),
    ToolMetadata("get_element_value", SERVER_NAME, "sensor", "Read a UI element value."),
    ToolMetadata("app_state", SERVER_NAME, "sensor", "Read application running state."),
    ToolMetadata("launch_app", SERVER_NAME, "action", "Launch an application."),
    ToolMetadata("focus_window", SERVER_NAME, "action", "Focus a window."),
    ToolMetadata("type_text", SERVER_NAME, "action", "Type text into the focused window."),
    ToolMetadata("press_hotkey", SERVER_NAME, "action", "Press a hotkey."),
    ToolMetadata("press_key", SERVER_NAME, "action", "Press a key."),
    ToolMetadata("write_file", SERVER_NAME, "action", "Write text to a file."),
    ToolMetadata("wait", SERVER_NAME, "action", "Pause desktop execution."),
    ToolMetadata("finish", SERVER_NAME, "control", "Signal objective completion."),
    ToolMetadata("report_blocking", SERVER_NAME, "control", "Signal an unresolvable blocker."),
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
# High-level task tool
# ---------------------------------------------------------------------------

@mcp.tool()
async def desktop_run(spec_dict: dict) -> dict:
    """Execute a full desktop objective and return a tagged result envelope.

    spec_dict is ObjectiveSpec.to_dict() — the complete objective spec,
    including metadata (retry_context, steering_context, dependency_evidence,
    timeout_seconds), dependencies, max_attempts, risk_class, etc. This is the
    real dispatch boundary: a fresh DesktopWorker is constructed per call.

    Returns one of three tagged shapes (WorkerBlocker/WorkerError cannot cross
    the MCP JSON-RPC boundary as raised exceptions, so they are translated):
      {"mcp_status": "ok", "evidence": {...}}
      {"mcp_status": "blocker", "reason": str, "result": {status, summary,
                                            evidence, steps_taken, tokens_used}}
      {"mcp_status": "error", "message": str}
    """
    spec = ObjectiveSpec.from_dict(spec_dict)
    timeout = float(spec.metadata.get("timeout_seconds", 180))
    worker = DesktopWorker()
    try:
        evidence = await asyncio.wait_for(worker.execute(spec), timeout=timeout)
        return {"mcp_status": "ok", "evidence": evidence}
    except WorkerBlocker as exc:
        result = exc.result
        return {
            "mcp_status": "blocker",
            "reason": str(exc),
            "result": {
                "status": result.status,
                "summary": result.summary,
                "evidence": result.evidence,
                "steps_taken": result.steps_taken,
                "tokens_used": result.tokens_used,
            },
        }
    except asyncio.TimeoutError:
        return {
            "mcp_status": "error",
            "message": f"Desktop MCP dispatch timed out after {timeout:.0f}s",
        }
    except WorkerError as exc:
        return {"mcp_status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Domain sensor tools (read-only, desktop-specific)
# Cross-cutting sensors (screenshot, window_list, clipboard_read, file_stat)
# live in sensor_server.py. Domain-specific desktop sensors stay here.
# ---------------------------------------------------------------------------

@mcp.tool()
def uia_tree(window_title: str = "") -> dict:
    """Return the UIA accessibility tree of the focused window or a named window.

    Args:
        window_title: Optional regex to match window title. Defaults to focused window.

    Returns:
        dict with tree_text (string representation) and window_title.
    """
    try:
        from pywinauto import Application, findwindows
        if window_title:
            handles = findwindows.find_windows(title_re=window_title)
            if not handles:
                return {"found": False, "error": f"No window matching '{window_title}'"}
            app = Application(backend="uia").connect(handle=handles[0], timeout=3)
        else:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            app = Application(backend="uia").connect(handle=hwnd, timeout=3)
        wrapper = app.top_window()
        import io
        buf = io.StringIO()
        wrapper.print_control_identifiers(out=buf)
        tree_text = buf.getvalue()
        actual_title = wrapper.window_text()
        return {"found": True, "window_title": actual_title, "tree_text": tree_text}
    except Exception as exc:
        return {"found": False, "error": str(exc)}


@mcp.tool()
def focused_element() -> dict:
    """Return details about the currently focused UI element.

    Returns:
        dict with name, control_type, value, rect (x, y, width, height).
    """
    try:
        import ctypes
        import ctypes.wintypes
        from pywinauto import Application
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        app = Application(backend="uia").connect(handle=hwnd, timeout=3)
        wrapper = app.top_window()
        focused = wrapper.get_focus()
        rect = focused.rectangle()
        return {
            "name": focused.window_text(),
            "control_type": focused.element_info.control_type,
            "value": getattr(focused, "get_value", lambda: "")(),
            "rect": {
                "x": rect.left, "y": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            },
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def window_hierarchy() -> dict:
    """Return all visible top-level windows with z-order, visibility, and process info.

    Returns:
        dict with windows: list of {title, pid, z_order, x, y, width, height}.
    """
    import ctypes
    import ctypes.wintypes
    windows = []
    z = 0

    def _callback(hwnd: int, _: int) -> bool:
        nonlocal z
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title:
                    rect = ctypes.wintypes.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    pid = ctypes.c_ulong()
                    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    windows.append({
                        "title": title,
                        "pid": pid.value,
                        "z_order": z,
                        "x": rect.left, "y": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                    })
                    z += 1
        return True

    try:
        _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    except Exception as exc:
        return {"windows": [], "error": str(exc)}
    return {"windows": windows}


@mcp.tool()
def get_element_value(locator: str, window_title: str = "") -> dict:
    """Read the value or text of a UI element by its name or locator.

    Args:
        locator: Element name (auto_id, name, or title).
        window_title: Optional window title regex to narrow search.

    Returns:
        dict with found, value, control_type.
    """
    try:
        from pywinauto import Application, findwindows
        if window_title:
            handles = findwindows.find_windows(title_re=window_title)
            if not handles:
                return {"found": False, "error": f"No window matching '{window_title}'"}
            app = Application(backend="uia").connect(handle=handles[0], timeout=3)
        else:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            app = Application(backend="uia").connect(handle=hwnd, timeout=3)
        wrapper = app.top_window()
        child = wrapper.child_window(title=locator)
        value = child.window_text()
        return {
            "found": True,
            "value": value,
            "control_type": child.element_info.control_type,
        }
    except Exception as exc:
        return {"found": False, "error": str(exc)}


@mcp.tool()
def app_state(process_name: str) -> dict:
    """Check the running state of an application by process name.

    Args:
        process_name: Executable name (e.g. 'notepad.exe').

    Returns:
        dict with running, window_count, focused_window_title, pids.
    """
    try:
        import psutil
        procs = [p for p in psutil.process_iter(["pid", "name"]) if p.info["name"].lower() == process_name.lower()]
        if not procs:
            return {"running": False, "process_name": process_name}
        pids = [p.info["pid"] for p in procs]
    except Exception:
        pids = []

    import ctypes
    import ctypes.wintypes
    matching_windows = []

    def _callback(hwnd: int, _: int) -> bool:
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title:
                    matching_windows.append(title)
        return True

    try:
        _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    except Exception:
        pass

    focused_hwnd = ctypes.windll.user32.GetForegroundWindow()
    focused_pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(focused_hwnd, ctypes.byref(focused_pid))
    focused_title = None
    if focused_pid.value in pids:
        length = ctypes.windll.user32.GetWindowTextLengthW(focused_hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(focused_hwnd, buf, length + 1)
        focused_title = buf.value or None

    return {
        "running": bool(pids),
        "process_name": process_name,
        "pids": pids,
        "window_count": len(matching_windows),
        "window_titles": matching_windows,
        "focused_window_title": focused_title,
    }


# ---------------------------------------------------------------------------
# Domain action tools (mirror the inner ReAct loop tools)
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
    """Press a single key by name e.g. 'enter', 'multiply', '1'."""
    worker = DesktopWorker.__new__(DesktopWorker)
    evidence: dict = {"action_log": []}
    await worker._press_key(key, evidence)
    await asyncio.sleep(0.2)
    return {"key": key, "log": evidence["action_log"][-1] if evidence["action_log"] else ""}


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
