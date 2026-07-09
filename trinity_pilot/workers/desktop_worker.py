from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _finish_decl,
    _make_tool,
    _report_blocking_decl,
    _take_screenshot_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

def _snapshot_pids() -> set[int]:
    """Return the set of all currently running PIDs (best-effort, never raises)."""
    try:
        import psutil
        return {p.pid for p in psutil.process_iter(["pid"])}
    except Exception:
        return set()


_ACTION_SYSTEM = """\
You are a desktop automation agent on Windows.
Given a goal, output ONLY a JSON array of action steps to accomplish it.
Each step is one of:
  {"action":"launch","app":"<exe-name>","args":[],"wait":1.5}
  {"action":"focus","title_re":"<window-title-regex>","wait":0.5}
  {"action":"type","text":"<text>","interval":0.03}
  {"action":"hotkey","keys":["ctrl","s"]}
  {"action":"press","key":"<key>"}
  {"action":"wait","seconds":<float>}
  {"action":"write_file","path":"<absolute-path>","content":"<text>"}

CRITICAL RULES:
- ALWAYS use write_file to save content to disk. NEVER use GUI save dialogs (Ctrl+S / File > Save).
  The write_file action directly writes the file — it is instant, reliable, and uses the exact path you specify.
- If the goal says to write content to a file at a path like C:/Users/User/Desktop/foo.txt, use write_file with that EXACT path.
- If the goal is ONLY to open/launch Notepad (no file to display yet), launch WITHOUT file args:
  {"action":"launch","app":"notepad.exe","args":[],"wait":1.5}
- Only pass a file path as a Notepad argument AFTER write_file has already written that exact file in the SAME action list.
- Do NOT include markdown, prose, or code fences. Return the JSON array only.
- Use forward slashes in all paths. Never abbreviate paths. Copy file paths EXACTLY as given.
- When writing poem content, include the COMPLETE poem with ALL requested stanzas in the write_file "content" field.
  If 4 stanzas are requested, write ALL 4 stanzas (each stanza = 4 lines, stanzas separated by a blank line).
  Count the stanzas before outputting. Do NOT truncate, summarise, or stop early. The JSON "content" field must
  contain the full text with all stanzas — never a partial poem.
"""

_DESKTOP_AGENT_SYSTEM = """\
You are a desktop automation agent on Windows.
Use the available tools to accomplish the goal step by step.

Tool categories:
- SENSOR tools read, inspect, measure, and detect. They never change world state.
  Use them freely before and after actions to verify state.
- ACTION tools create, modify, execute, or delete. They change world state.
  Each action must be intentional. Prefer sensing first, then acting.

Available tools:

[SENSOR] screenshot: Capture a window or screen as an image attached to your next turn.
  Use mode='app' with app_title to capture the target window. READ the image yourself —
  it is the reliable way to see display values, labels, and UI state that UIA text misses.
[SENSOR] clipboard_read: Read current clipboard text (after copy via press_hotkey).
[SENSOR] read_window_text: Read UIA text snippets (often incomplete — prefer screenshot for on-screen values).

[ACTION] launch_app: Launch an application by executable name.
[ACTION] focus_window: Focus a window by title regex.
[ACTION] type_text: Type text into the currently focused window.
[ACTION] press_hotkey: Press a keyboard hotkey combination.
[ACTION] press_key: Press a single key.
[ACTION] click_button: Click a UI button by its visible label text (e.g. 'Got it', 'OK').
[ACTION] write_file: Write text content directly to a file at an absolute path.
[ACTION] wait: Pause execution for a number of seconds.
[ACTION] finish: Signal that the objective is complete or definitively failed.
[ACTION] report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

CRITICAL RULES:
- ALWAYS call focus_window BEFORE type_text, press_key, or press_hotkey.
  The system automatically re-focuses the last focused window before sending
  input, but you MUST still call focus_window at least once to declare which
  window should receive input. Without it, keystrokes may go to the wrong app.
- After launch_app, ALWAYS call focus_window with a title_re that matches the
  launched application before sending any keystrokes.
- ALWAYS use write_file to save content to disk. NEVER use GUI save dialogs.
- After write_file, open the created file so the user can see it. Use launch_app with the file
  path as an arg (e.g. {"action":"launch","app":"notepad.exe","args":["C:/path/to/file.txt"],"wait":1.5}).
- Call finish when the objective is done or definitively cannot be completed.
- Call report_blocking only if you genuinely cannot proceed without external input.
- Use forward slashes in all file paths.
- After each ACTION tool call, read its result before proceeding. If a tool failed or
  produced unexpected state, adapt — do not blindly continue to the next planned step.
- NEVER call finish until every action described in the GOAL is done. Read the GOAL in full
  before your first tool call.
- After actions that should show a result on screen, verify with screenshot(mode='app',
  app_title='<window title>'). The image is attached — read the display value directly
  from the pixels. Put the exact value you see into your finish summary.
- read_window_text is a fallback for labels/menus; it often omits numeric display fields.
  Do NOT call finish based on read_window_text alone when the goal asks you to report
  a value shown in the app — use screenshot and read the image first.
- To capture a value shown in an app: screenshot(mode='app') is preferred. Optionally
  try press_hotkey('ctrl','c') then clipboard_read if the app supports copy.
- NEVER call finish(success) for a task that required writing a file unless write_file
  has returned successfully for that file. Include the written file path in your finish summary.
- To CLOSE any application window: first use press_hotkey("alt", "F4") after focusing
  the window. Do NOT use Ctrl+W, Ctrl+F4, or any other shortcut — they trigger
  application-specific dialogs (e.g., Ctrl+W opens Resize/Skew in Paint, not close).
  If a "Save changes?" dialog appears and click_button("Don't save") fails, use
  kill_process(process_name="<exe>.exe") as a reliable direct termination fallback.
  kill_process is always available and does not require cmd.exe — prefer it over
  launching a terminal to type taskkill.
[ACTION] kill_process: Force-kill a process by .exe name (e.g. 'mspaint.exe'). Use when alt+F4 or click_button fail.
- Before performing actions in a freshly launched app, dismiss any welcome/popup
  dialogs. Check the screenshot after launch — if a coaching tooltip or dialog with
  a labeled button (e.g. "Got it", "OK", "Close") is visible, call
  click_button(button_text="Got it") (or the appropriate label) to dismiss it.
  Only fall back to press_key("escape") if no button label is visible.
  Do NOT proceed with the main task until the popup is gone — failing to dismiss
  a popup prevents subsequent key presses from reaching the target window.
  For Microsoft Paint: a "Try Image Creator" tooltip with a "Got it" button appears
  on launch. Call click_button(button_text="Got it") immediately after focus_window
  to dismiss it before drawing or closing Paint.
"""

# Domain tool declarations
_launch_app_decl = genai_types.FunctionDeclaration(
    name="launch_app",
    description="Launch an application by executable name.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "app": genai_types.Schema(type=genai_types.Type.STRING, description="Executable name or path."),
            "args": genai_types.Schema(type=genai_types.Type.STRING, description="Space-separated arguments (optional)."),
            "wait": genai_types.Schema(type=genai_types.Type.NUMBER, description="Seconds to wait after launch."),
        },
        required=["app"],
    ),
)

_focus_window_decl = genai_types.FunctionDeclaration(
    name="focus_window",
    description="Focus a window matching a title regex.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "title_re": genai_types.Schema(type=genai_types.Type.STRING, description="Window title regex."),
            "wait": genai_types.Schema(type=genai_types.Type.NUMBER, description="Seconds to wait after focus."),
        },
        required=["title_re"],
    ),
)

_type_text_decl = genai_types.FunctionDeclaration(
    name="type_text",
    description="Type text into the currently focused window.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "text": genai_types.Schema(type=genai_types.Type.STRING, description="Text to type."),
            "interval": genai_types.Schema(type=genai_types.Type.NUMBER, description="Interval between keystrokes."),
        },
        required=["text"],
    ),
)

_press_hotkey_decl = genai_types.FunctionDeclaration(
    name="press_hotkey",
    description="Press a keyboard hotkey combination.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "keys": genai_types.Schema(type=genai_types.Type.STRING, description="Comma-separated keys e.g. 'ctrl,s'."),
        },
        required=["keys"],
    ),
)

_press_key_decl = genai_types.FunctionDeclaration(
    name="press_key",
    description="Press a single key.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "key": genai_types.Schema(type=genai_types.Type.STRING, description="Key name e.g. 'enter'."),
        },
        required=["key"],
    ),
)

_desktop_write_file_decl = genai_types.FunctionDeclaration(
    name="write_file",
    description="Write text content directly to a file at an absolute path.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "path": genai_types.Schema(type=genai_types.Type.STRING, description="Absolute path to write."),
            "content": genai_types.Schema(type=genai_types.Type.STRING, description="Text content to write."),
        },
        required=["path", "content"],
    ),
)

_wait_decl = genai_types.FunctionDeclaration(
    name="wait",
    description="Pause execution for a number of seconds.",
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "seconds": genai_types.Schema(type=genai_types.Type.NUMBER, description="Seconds to wait."),
        },
        required=["seconds"],
    ),
)

_get_clipboard_decl = genai_types.FunctionDeclaration(
    name="clipboard_read",
    description="Read and return the current clipboard text content.",
    parameters=genai_types.Schema(type=genai_types.Type.OBJECT, properties={}),
)

_read_window_text_decl = genai_types.FunctionDeclaration(
    name="read_window_text",
    description=(
        "Read UIA accessibility text snippets from a window. "
        "Often misses numeric display/result fields — use screenshot(mode='app') "
        "to read values shown on screen when the goal requires reporting a result."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "window_title_re": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Window title regex. Defaults to the last focused window.",
            ),
            "max_items": genai_types.Schema(
                type=genai_types.Type.INTEGER,
                description="Maximum snippets to return (default 15).",
            ),
        },
        required=[],
    ),
)

_click_button_decl = genai_types.FunctionDeclaration(
    name="click_button",
    description=(
        "Click a UI button found by its visible label text. "
        "Use this to dismiss dialog boxes, coaching tooltips, or popup buttons "
        "(e.g. 'Got it', 'OK', 'Cancel', 'Close'). "
        "Searches within the currently focused window if window_title_re is omitted."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "button_text": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Exact visible label of the button to click (e.g. 'Got it', 'OK').",
            ),
            "window_title_re": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Optional window title regex to search within. Defaults to the foreground window.",
            ),
        },
        required=["button_text"],
    ),
)

_kill_process_decl = genai_types.FunctionDeclaration(
    name="kill_process",
    description=(
        "Force-kill a process by executable name using taskkill /F /IM. "
        "Use this as a reliable fallback when alt+F4 or click_button fail to close a window. "
        "Example: kill_process(process_name='mspaint.exe') closes Paint without save dialogs."
    ),
    parameters=genai_types.Schema(
        type=genai_types.Type.OBJECT,
        properties={
            "process_name": genai_types.Schema(
                type=genai_types.Type.STRING,
                description="Executable filename to kill, e.g. 'mspaint.exe', 'notepad.exe'.",
            ),
        },
        required=["process_name"],
    ),
)


_CALCULATOR_BUTTON_LABELS: dict[str, list[str]] = {
    "0": ["Zero"],
    "1": ["One"],
    "2": ["Two"],
    "3": ["Three"],
    "4": ["Four"],
    "5": ["Five"],
    "6": ["Six"],
    "7": ["Seven"],
    "8": ["Eight"],
    "9": ["Nine"],
    "add": ["Plus", "+"],
    "plus": ["Plus", "+"],
    "subtract": ["Minus", "−", "-"],
    "minus": ["Minus", "−", "-"],
    "multiply": ["Multiply by", "×", "Multiply"],
    "times": ["Multiply by", "×", "Multiply"],
    "x": ["Multiply by", "×", "Multiply"],
    "divide": ["Divide by", "÷", "Divide"],
    "return": ["Equals", "="],
    "enter": ["Equals", "="],
    "equals": ["Equals", "="],
    "decimal": ["Decimal separator", "."],
    "dot": ["Decimal separator", "."],
}

_PYWINAUTO_KEY_ALIASES: dict[str, str] = {
    "multiply": "{*}",
    "times": "{*}",
    "x": "{*}",
    "add": "{+}",
    "plus": "{+}",
    "subtract": "-",
    "minus": "-",
    "divide": "/",
    "return": "{ENTER}",
    "enter": "{ENTER}",
    "equals": "{ENTER}",
    "decimal": ".",
    "dot": ".",
}

_PYAUTOGUI_KEY_ALIASES: dict[str, str] = {
    "multiply": "multiply",
    "times": "multiply",
    "x": "multiply",
    "add": "add",
    "plus": "add",
    "subtract": "subtract",
    "minus": "subtract",
    "divide": "divide",
    "return": "enter",
    "enter": "enter",
    "equals": "enter",
    "decimal": "decimal",
    "dot": "decimal",
}


def _agent_dbg(
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    *,
    hypothesis_id: str = "press-key",
) -> None:
    try:
        from trinity_pilot.telemetry.trace import emit as trace_emit

        trace_emit(
            location,
            message,
            data,
            hypothesis_id=hypothesis_id,
            run_id="probe",
            span="worker",
        )
    except Exception:
        pass


class DesktopWorker(AgenticWorkerMixin, DomainWorker):
    """LLM-driven desktop worker using ReAct loop."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.gemini import GeminiProvider
            llm = GeminiProvider(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.5-flash"),
            )
        super().__init__(llm=llm)
        # Title-regex of the window the agent last asked to focus.
        # Re-asserted automatically before every input tool so keystrokes
        # never land in a random foreground window.
        self._target_window: str | None = None

    def _worker_system_prompt(self) -> str:
        return _DESKTOP_AGENT_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            _launch_app_decl,
            _focus_window_decl,
            _type_text_decl,
            _press_hotkey_decl,
            _press_key_decl,
            _click_button_decl,
            _kill_process_decl,
            _desktop_write_file_decl,
            _wait_decl,
            _get_clipboard_decl,
            _read_window_text_decl,
            _take_screenshot_decl,
            _finish_decl,
            _report_blocking_decl,
        ])]

    def _worker_environment_context(self, spec, evidence) -> str:  # type: ignore[override]
        import sys as _sys
        import pathlib
        platform_name = "Windows" if _sys.platform == "win32" else _sys.platform
        active_title = self._get_active_window_title()
        desktop = str(pathlib.Path.home() / "Desktop").replace("\\", "/")
        username = os.environ.get("USERNAME") or os.environ.get("USER") or "User"
        lines = ["DESKTOP STATE:"]
        lines.append(f"  Platform: {platform_name}")
        lines.append(f"  Username: {username}")
        lines.append(f"  Desktop path: {desktop}")
        lines.append(f"  Home dir: {str(pathlib.Path.home()).replace(chr(92), '/')}")
        if active_title:
            lines.append(f"  Active window: {active_title!r}")
        else:
            lines.append("  Active window: unknown")
        return "\n".join(lines)

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:  # type: ignore[override]
        active = self._get_active_window_title() or "unknown"
        action_log = evidence.get("action_log", [])
        last_action = action_log[-1] if action_log else "none"
        windows = self._get_open_windows()
        windows_str = f"[{', '.join(windows)}]" if windows else "[]"
        return "\n".join([
            f"active_window={active!r}",
            f"open_windows={windows_str}",
            f"last_action={last_action}",
        ])

    def _action_sensor_check(self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]):  # type: ignore[override]
        if tool_name != "launch_app":
            return None
        launched_pids = list(evidence.get("launched_pids") or [])
        if not launched_pids:
            return None

        async def _check() -> bool:
            try:
                import psutil
                return any(psutil.pid_exists(pid) for pid in launched_pids)
            except Exception:
                return False

        return _check

    def _action_sensor_read(self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]):  # type: ignore[override]
        if tool_name != "click_button":
            return None

        async def _read() -> str:
            active = self._get_active_window_title() or "unknown"
            return f"active_window after click: {active!r}"

        return _read

    @staticmethod
    def _get_open_windows() -> list[str]:
        """Enumerate visible top-level window titles (Windows only, caps at 10)."""
        _WIN_CAP = 10
        try:
            import ctypes
            titles: list[str] = []

            def _callback(hwnd: int, _: int) -> bool:
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value.strip()
                        if title:
                            titles.append(title)
                return True

            _WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            ctypes.windll.user32.EnumWindows(_WNDENUMPROC(_callback), 0)
            return titles[:_WIN_CAP]
        except Exception:
            return []

    @staticmethod
    def _get_active_window_title() -> str | None:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or None
        except Exception:
            return None

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        self._target_window = None  # reset per-objective; no cross-contamination
        evidence: dict[str, Any] = {
            "domain": "desktop",
            "objective_id": spec.objective_id,
            "screenshot": None,
            "element_tree_snapshot": None,
            "action_log": [],
            "selected_actions": [],
            "typed_text": "",
            "visible_text": "",
            "written_files": [],
            "launched_pids": [],   # PIDs of every process spawned via launch_app
            "degraded_mode": False,
            "error": None,
        }
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 120))
        try:
            result = await asyncio.wait_for(
                self.run_loop(spec, evidence),
                timeout=timeout_seconds,
            )
            evidence["worker_result_status"] = result.status
            evidence["worker_result_summary"] = result.summary
        except asyncio.TimeoutError:
            raise WorkerError(
                f"Desktop timeout after {timeout_seconds}s for '{spec.objective_id}'"
            )
        except WorkerBlocker:
            raise
        except WorkerError:
            raise
        except Exception as exc:
            evidence["error"] = str(exc)
            raise WorkerError(
                f"Desktop execution failed for '{spec.objective_id}': {exc}"
            ) from exc
        validate_evidence(DomainType.DESKTOP, evidence)
        return evidence

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> str:
        import subprocess

        _agent_dbg(
            "desktop_worker.py:_dispatch_tool",
            "tool_dispatch",
            {"tool": tool_name, "args_preview": {k: str(v)[:80] for k, v in args.items()}},
        )

        if tool_name == "launch_app":
            app = args["app"]
            raw_args = args.get("args", "")
            if isinstance(raw_args, list):
                app_args = raw_args
            elif raw_args:
                app_args = raw_args.split()
            else:
                app_args = []
            app_args = [a.replace("/", "\\") if isinstance(a, str) else a for a in app_args]
            # Map exe names to window title patterns so we can detect existing instances.
            _EXE_TITLE_MAP = {
                "notepad.exe": "notepad",
                "notepad": "notepad",
                "calc.exe": "calculator",
                "calc": "calculator",
                "mspaint.exe": "paint",
                "mspaint": "paint",
            }
            title_hint = _EXE_TITLE_MAP.get(app.lower())
            if title_hint:
                try:
                    from pywinauto import findwindows
                    existing = findwindows.find_windows(title_re=f"(?i){title_hint}")
                    if existing:
                        import ctypes
                        hwnd = existing[0]
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                        evidence["action_log"].append(f"Reused existing window: {app}")
                        return f"Reused existing {app} window (already open)"
                except Exception:
                    pass  # fall through to normal launch
            pids_before = _snapshot_pids()
            proc = subprocess.Popen([app, *app_args])
            wait = float(args.get("wait", 1.5))
            await asyncio.sleep(wait)
            # Record the direct PID plus any processes spawned during the wait
            # window (covers UWP stubs like calc.exe that spawn CalculatorApp.exe
            # as a separate process and then exit).
            new_pids = _snapshot_pids() - pids_before
            new_pids.add(proc.pid)
            evidence.setdefault("launched_pids", []).extend(sorted(new_pids))
            evidence["action_log"].append(
                f"Launched: {app} (pids={sorted(new_pids)})"
            )
            return f"Launched {app} (pids={sorted(new_pids)})"

        elif tool_name == "focus_window":
            title_re = args["title_re"]
            wait = float(args.get("wait", 0.5))
            focused = await self._focus_window(title_re, evidence)
            if focused:
                self._target_window = title_re
            await asyncio.sleep(wait)
            return f"Focused window: {title_re}"

        elif tool_name == "type_text":
            text = args["text"]
            _MAX_TYPE_CHARS = 500
            if len(text) > _MAX_TYPE_CHARS:
                evidence["action_log"].append(
                    f"type_text blocked: {len(text)} chars > {_MAX_TYPE_CHARS} limit"
                )
                return (
                    f"🛑 BLOCKED: type_text called with {len(text)} characters. "
                    f"Maximum per call is {_MAX_TYPE_CHARS}. "
                    "Typing thousands of characters is not a supported automation pattern. "
                    "Call finish('failure') explaining that the goal requires excessive repetition."
                )
            interval = float(args.get("interval", 0.03))
            await self._ensure_target_focused(evidence)
            if self._calculator_window_open():
                evidence["action_log"].append(
                    f"type_text blocked in Calculator: {text!r}"
                )
                return (
                    "🛑 BLOCKED: type_text does not work in Windows Calculator. "
                    "Use press_key for each digit and operator separately "
                    "(e.g. press_key('1'), press_key('2'), press_key('multiply'), "
                    "press_key('1'), press_key('2'), press_key('equals')). "
                    "Then read_window_text or press_hotkey('ctrl','c') and clipboard_read."
                )
            await self._type_text(text, interval, evidence)
            await asyncio.sleep(0.1)
            evidence["typed_text"] = evidence.get("typed_text", "") + text
            evidence["action_log"].append(f"Typed {len(text)} chars")
            return f"Typed {len(text)} chars"

        elif tool_name == "press_hotkey":
            keys_str = args["keys"]
            keys = [k.strip() for k in keys_str.split(",")]
            await self._ensure_target_focused(evidence)
            await self._hotkey(keys, evidence)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Hotkey: {keys_str}")
            return f"Pressed hotkey: {keys_str}"

        elif tool_name == "press_key":
            key = args["key"]
            await self._ensure_target_focused(evidence)
            await self._press_key(key, evidence)
            await asyncio.sleep(0.2)
            evidence["action_log"].append(f"Press: {key}")
            return f"Pressed key: {key}"

        elif tool_name == "click_button":
            button_text = args["button_text"]
            window_title_re = args.get("window_title_re")
            try:
                from pywinauto import Application
                import win32gui
                if window_title_re:
                    app_obj = Application(backend="uia").connect(
                        title_re=window_title_re, timeout=5
                    )
                    win_obj = app_obj.top_window()
                else:
                    hwnd = win32gui.GetForegroundWindow()
                    app_obj = Application(backend="uia").connect(handle=hwnd)
                    win_obj = app_obj.top_window()
                # Try multiple strategies: exact → case-insensitive → any control type
                _strategies = [
                    dict(title=button_text, control_type="Button"),
                    dict(title_re=f"(?i){re.escape(button_text)}", control_type="Button"),
                    dict(title_re=f"(?i){re.escape(button_text)}"),
                ]
                _last_exc = None
                for _s in _strategies:
                    try:
                        btn = win_obj.child_window(**_s)
                        btn.click_input()
                        await asyncio.sleep(0.3)
                        evidence["action_log"].append(f"click_button: '{button_text}' strat={_s}")
                        return f"Clicked button '{button_text}'"
                    except Exception as _e:
                        _last_exc = _e
                evidence["action_log"].append(f"click_button all strategies failed: {_last_exc}")
                return f"click_button failed (button '{button_text}' not found): {_last_exc}"
            except Exception as exc:
                evidence["action_log"].append(f"click_button failed: {exc}")
                return f"click_button failed: {exc}"

        elif tool_name == "write_file":
            path = args["path"]
            content = args["content"]
            import pathlib
            p = pathlib.Path(path)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            except Exception as exc:
                evidence.setdefault("write_file_failures", []).append({"path": path, "error": str(exc)})
                evidence["action_log"].append(f"write_file FAILED: {path}: {exc}")
                return f"write_file failed: {path}: {exc}"
            exists_after = p.exists()
            evidence.setdefault("written_files_verified", {})[path] = exists_after
            if not exists_after:
                evidence.setdefault("write_file_failures", []).append(
                    {"path": path, "error": "file missing immediately after write"}
                )
            evidence["written_files"].append(path)
            preview = content[:500] + ("..." if len(content) > 500 else "")
            evidence["action_log"].append(
                f"Wrote file: {path} ({len(content)} chars) verified_exists={exists_after}"
            )
            evidence[f"file_content_{p.name}"] = preview
            return f"File written: {path} ({len(content)} chars) verified_exists={exists_after}"

        elif tool_name == "wait":
            secs = float(args.get("seconds", 0.5))
            await asyncio.sleep(secs)
            evidence["action_log"].append(f"Waited {secs}s")
            return f"Waited {secs}s"

        elif tool_name == "screenshot":
            if self._target_window and not args.get("app_title"):
                args = {**args, "mode": args.get("mode", "app"), "app_title": self._target_window}
            result = await super()._dispatch_tool(tool_name, args, evidence)
            _agent_dbg(
                "desktop_worker.py:screenshot",
                "screenshot_for_vision",
                {
                    "mode": args.get("mode", "app"),
                    "app_title": args.get("app_title", ""),
                    "has_image": isinstance(result, tuple),
                },
                hypothesis_id="vision-read",
            )
            return result

        elif tool_name == "kill_process":
            import subprocess as _sp
            process_name = args.get("process_name", "")
            try:
                result = _sp.run(
                    ["taskkill", "/F", "/IM", process_name],
                    capture_output=True, text=True, timeout=10,
                )
                await asyncio.sleep(0.5)
                msg = f"kill_process {process_name}: exit={result.returncode} {result.stdout.strip()} {result.stderr.strip()}"
                evidence["action_log"].append(msg)
                return msg
            except Exception as exc:
                evidence["action_log"].append(f"kill_process failed: {exc}")
                return f"kill_process failed: {exc}"

        elif tool_name == "clipboard_read":
            text = self._read_clipboard_text()
            if text:
                evidence["clipboard_text"] = text
                evidence["action_log"].append(f"clipboard_read: {text[:100]!r}")
                return text
            evidence["action_log"].append("clipboard_read: (empty)")
            return "(clipboard is empty)"

        elif tool_name == "read_window_text":
            title_re = args.get("window_title_re") or self._target_window
            max_items = int(args.get("max_items", 15))
            snippets = self._read_window_text_uia(title_re, max_items=max_items)
            evidence["visible_text_snippets"] = snippets
            evidence["action_log"].append(
                f"read_window_text: {len(snippets)} snippet(s) from {title_re!r}"
            )
            _agent_dbg(
                "desktop_worker.py:read_window_text",
                "window_text_read",
                {"title_re": title_re, "snippets": snippets[:5]},
                hypothesis_id="general-sensor",
            )
            if not snippets:
                return (
                    "No readable text found in the target window. "
                    "Call screenshot(mode='app', app_title=<window>) — the image is attached "
                    "for you to read the on-screen value directly."
                )
            body = "\n".join(f"- {s}" for s in snippets)
            obs = f"Visible text in window ({title_re or 'foreground'}):\n{body}"
            if not self._uia_snippets_show_result_value(snippets):
                obs += (
                    "\n\nUIA did not expose a clear numeric result field "
                    "(only labels/expressions may be visible to accessibility). "
                    "Call screenshot(mode='app', app_title=<window>) and read the "
                    "display value from the attached image before finish."
                )
            return obs

        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    # ------------------------------------------------------------------
    # Backward-compatible helpers
    # ------------------------------------------------------------------

    async def _run_objective(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> None:
        if sys.platform != "win32":
            evidence["degraded_mode"] = True
            evidence["action_log"].append("Platform is not win32 — degraded mode")
            self._capture_screenshot_fallback(evidence)
            return

        uia_ok = False
        try:
            import pywinauto  # noqa: F401
            uia_ok = True
        except Exception as exc:
            evidence["degraded_mode"] = True
            evidence["action_log"].append(f"UIA failed: {exc}")

        if uia_ok:
            try:
                actions = spec.metadata.get("audit_actions") or await self._generate_actions(spec.goal)
                evidence["action_log"].append(f"Generated {len(actions)} action steps")
                evidence["selected_actions"] = actions
                if actions:
                    evidence["selected_action"] = actions[0].get("action")
                evidence["action_signature"] = {
                    "action": actions[0].get("action") if actions else None,
                    "target": actions[0].get("app") or actions[0].get("title_re") if actions else None,
                    "args": actions[0].get("args") if actions else None,
                    "steering_context": spec.metadata.get("steering_context"),
                }
                await self._execute_actions(actions, evidence)
                expected_text = str(spec.metadata.get("expected_text", ""))
                if expected_text:
                    from trinity_pilot.audit.desktop_probe import probe_notepad_visible_text
                    probe = probe_notepad_visible_text(expected_text)
                    evidence["visible_text_probe"] = probe.to_dict()
                    if probe.visible_text_match or probe.screenshot_text_match:
                        evidence["visible_text"] = expected_text
                written = [
                    a["path"] for a in actions
                    if a.get("action") == "write_file"
                    and isinstance(a.get("path"), str)
                ]
                for p in written:
                    import pathlib
                    evidence["written_files"].append(p)
                    evidence["action_log"].append(
                        f"File exists after execution: {p} = {pathlib.Path(p).exists()}"
                    )
            except Exception as exc:
                evidence["degraded_mode"] = True
                evidence["action_log"].append(f"Action generation/execution failed: {exc}")

        self._capture_screenshot_fallback(evidence)

    async def _generate_actions(self, goal: str) -> list[dict[str, Any]]:
        from trinity_pilot.llm.base import LLMMessage
        from trinity_pilot.llm.gemini import GeminiProvider

        provider = GeminiProvider(
            api_key=os.environ["GEMINI_API_KEY"],
            model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.5-flash"),
        )
        response = await provider.complete(
            [LLMMessage(role="user", content=f"GOAL: {goal}\n\nGenerate the action list now.")],
            system=_ACTION_SYSTEM,
        )
        raw = response.content.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*(?:```|$)", raw)
        if match:
            raw = match.group(1).strip()
        return json.loads(raw)

    async def _execute_actions(
        self, actions: list[dict[str, Any]], evidence: dict[str, Any]
    ) -> None:
        import subprocess

        for step in actions:
            act = step.get("action", "")
            try:
                if act == "launch":
                    app = step["app"]
                    args = [a.replace("/", "\\") if isinstance(a, str) else a for a in step.get("args", [])]
                    _EXE_TITLE_MAP = {
                        "notepad.exe": "notepad", "notepad": "notepad",
                        "calc.exe": "calculator", "calc": "calculator",
                        "mspaint.exe": "paint", "mspaint": "paint",
                    }
                    title_hint = _EXE_TITLE_MAP.get(app.lower())
                    if title_hint:
                        try:
                            from pywinauto import findwindows
                            existing = findwindows.find_windows(title_re=f"(?i){title_hint}")
                            if existing:
                                import ctypes
                                hwnd = existing[0]
                                ctypes.windll.user32.ShowWindow(hwnd, 9)
                                ctypes.windll.user32.SetForegroundWindow(hwnd)
                                evidence["action_log"].append(f"Reused existing window: {app}")
                                continue
                        except Exception:
                            pass
                    pids_before = _snapshot_pids()
                    proc = subprocess.Popen([app, *args])
                    wait = float(step.get("wait", 1.5))
                    await asyncio.sleep(wait)
                    new_pids = _snapshot_pids() - pids_before
                    new_pids.add(proc.pid)
                    evidence.setdefault("launched_pids", []).extend(sorted(new_pids))
                    evidence["action_log"].append(
                        f"Launched: {app} (pids={sorted(new_pids)})"
                    )

                elif act == "focus":
                    title_re = step["title_re"]
                    wait = float(step.get("wait", 0.5))
                    try:
                        from pywinauto import Application
                        app = Application(backend="uia").connect(title_re=title_re, timeout=5)
                        win = app.top_window()
                        win.set_focus()
                    except Exception:
                        pass
                    await asyncio.sleep(wait)
                    evidence["action_log"].append(f"Focused: {title_re}")

                elif act == "type":
                    text = step["text"]
                    interval = float(step.get("interval", 0.03))
                    await self._type_text(text, interval, evidence)
                    await asyncio.sleep(0.1)
                    evidence["typed_text"] += text
                    evidence["action_log"].append(f"Typed {len(text)} chars")

                elif act == "hotkey":
                    keys = step["keys"]
                    await self._hotkey(keys, evidence)
                    await asyncio.sleep(0.3)
                    evidence["action_log"].append(f"Hotkey: {'+'.join(keys)}")

                elif act == "press":
                    key = step["key"]
                    await self._press_key(key, evidence)
                    await asyncio.sleep(0.2)
                    evidence["action_log"].append(f"Press: {key}")

                elif act == "wait":
                    secs = float(step.get("seconds", 0.5))
                    await asyncio.sleep(secs)
                    evidence["action_log"].append(f"Waited {secs}s")

                elif act == "write_file":
                    path = step["path"]
                    content = step["content"]
                    import pathlib
                    p = pathlib.Path(path)
                    try:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(content, encoding="utf-8")
                        exists_after = p.exists()
                    except Exception as write_exc:
                        evidence.setdefault("write_file_failures", []).append(
                            {"path": path, "error": str(write_exc)}
                        )
                        evidence["action_log"].append(f"write_file FAILED: {path}: {write_exc}")
                        raise
                    evidence.setdefault("written_files_verified", {})[path] = exists_after
                    if not exists_after:
                        evidence.setdefault("write_file_failures", []).append(
                            {"path": path, "error": "file missing immediately after write"}
                        )
                    preview = content[:500] + ("..." if len(content) > 500 else "")
                    evidence["action_log"].append(
                        f"Wrote file: {path} ({len(content)} chars) verified_exists={exists_after}"
                    )
                    evidence[f"file_content_{p.name}"] = preview

                else:
                    evidence["action_log"].append(f"Unknown action ignored: {act}")

            except Exception as exc:
                evidence["action_log"].append(f"Action '{act}' failed: {exc}")

    async def _focus_window(self, title_re: str, evidence: dict[str, Any]) -> bool:
        """Focus a window by title regex. Returns True on success.

        Uses pure Win32 EnumWindows via ctypes — no UIA queries, no WinUI3 hang.
        Polls up to 30s for the window to become visible (covers slow app launches).
        """
        import ctypes
        import ctypes.wintypes
        import re as _re
        import time

        pattern = _re.compile(title_re, _re.IGNORECASE)
        user32 = ctypes.windll.user32

        def _find_visible_hwnd() -> int | None:
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            def _cb(hwnd: int, _: int) -> bool:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if pattern.search(buf.value):
                    found.append(hwnd)
                    return False  # stop enumeration
                return True

            user32.EnumWindows(_cb, 0)
            return found[0] if found else None

        try:
            deadline = time.monotonic() + 30
            hwnd: int | None = None
            while time.monotonic() < deadline:
                hwnd = _find_visible_hwnd()
                if hwnd:
                    break
                await asyncio.sleep(0.5)

            if not hwnd:
                evidence["action_log"].append(
                    f"focus_window failed ({title_re}): window not visible after 30s"
                )
                return False

            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Focused: {title_re}")
            return True
        except Exception as exc:
            evidence["action_log"].append(f"focus_window failed ({title_re}): {exc}")
            return False

    async def _ensure_target_focused(self, evidence: dict[str, Any]) -> None:
        """Re-assert focus on the last declared target window before sending input.

        Called automatically before every type_text / press_key / press_hotkey
        so keystrokes always land in the intended application even if something
        else grabbed focus in between steps.
        """
        if not self._target_window:
            return  # no target declared yet — trust whatever has focus
        try:
            active = self._get_active_window_title() or ""
            import re as _re
            if _re.search(self._target_window, active, _re.IGNORECASE):
                return  # already focused — nothing to do
            # Focus drifted — re-assert
            await self._focus_window(self._target_window, evidence)
        except Exception:
            pass  # best-effort; don't block the input operation

    async def _type_text(self, text: str, interval: float, evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            send_keys(text, pause=interval, with_spaces=True, with_tabs=True, with_newlines=True)
            evidence["action_log"].append("Typed via pywinauto keyboard")
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto type fallback failed: {exc}")
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.write(text, interval=interval)
            evidence["action_log"].append("Typed via PyAutoGUI fallback")

        # Accumulate typed text so verify_visible_text can confirm visible delivery.
        # Only counted as visible proof when focus_window was called first
        # (meaning keystrokes were intentionally directed at a known window).
        if self._target_window:
            evidence["visible_text"] = evidence.get("visible_text", "") + text

    async def _hotkey(self, keys: list[str], evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            modifier_map = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
            modifiers = "".join(modifier_map[k.lower()] for k in keys[:-1] if k.lower() in modifier_map)
            key = keys[-1]
            send_keys(f"{modifiers}{key}")
            evidence["action_log"].append("Hotkey via pywinauto keyboard")
            return
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto hotkey fallback failed: {exc}")

        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.hotkey(*keys)
        evidence["action_log"].append("Hotkey via PyAutoGUI fallback")

    @staticmethod
    def _pywinauto_key_sequence(key: str) -> str:
        k = key.strip().lower()
        if k in _PYWINAUTO_KEY_ALIASES:
            return _PYWINAUTO_KEY_ALIASES[k]
        if len(k) == 1 and (k.isdigit() or k in ".+-*/"):
            return k
        return f"{{{key.strip().upper()}}}"

    @staticmethod
    def _pyautogui_key_name(key: str) -> str:
        k = key.strip().lower()
        if k in _PYAUTOGUI_KEY_ALIASES:
            return _PYAUTOGUI_KEY_ALIASES[k]
        return k

    @staticmethod
    def _read_clipboard_text() -> str:
        import subprocess
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _calculator_window_open(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from pywinauto import findwindows
            return bool(findwindows.find_windows(title_re=r"(?i)calculator"))
        except Exception:
            title = (self._get_active_window_title() or "").lower()
            target = (self._target_window or "").lower()
            return "calculator" in title or "calculator" in target

    @staticmethod
    def _calculator_text_to_keys(text: str) -> list[str] | None:
        """Parse arithmetic text into Calculator press_key names (UWP-safe)."""
        s = text.strip().lower()
        s = re.sub(r"\bmultiplied\s+by\b", "*", s)
        s = re.sub(r"\btimes\b", "*", s)
        s = re.sub(r"\bplus\b", "+", s)
        s = re.sub(r"\bminus\b", "-", s)
        s = re.sub(r"\bdivided\s+by\b", "/", s)
        s = s.replace("×", "*").replace("÷", "/").replace("x", "*")
        s = re.sub(r"\s+", "", s).rstrip("=")

        m = re.fullmatch(r"(\d+(?:\.\d+)?)([\+\-\*/])(\d+(?:\.\d+)?)", s)
        if not m:
            return None
        left, op, right = m.group(1), m.group(2), m.group(3)
        op_key = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}[op]
        keys: list[str] = []
        for ch in left:
            keys.append(ch)
        keys.append(op_key)
        for ch in right:
            keys.append(ch)
        keys.append("equals")
        return keys

    # Generic UIA text reading — works for any application window.
    _UA_LABEL_SKIP_RE = re.compile(
        r"^(Display is \d+|Line \d+,?\s*Column \d+|System|Pane|TitleBar)$",
        re.IGNORECASE,
    )

    @classmethod
    def _is_meaningful_ui_text(cls, text: str, control_type: str = "") -> bool:
        t = text.strip()
        if not t or len(t) > 5000:
            return False
        if cls._UA_LABEL_SKIP_RE.match(t):
            return False
        if control_type == "Text" and t.lower().startswith("display is "):
            return False
        return bool(re.search(r"\w", t))

    @classmethod
    def _score_ui_snippet(cls, text: str, control_type: str) -> float:
        if not cls._is_meaningful_ui_text(text, control_type):
            return -1.0
        t = text.strip()
        score = 0.0
        if control_type in ("Document", "Edit"):
            score += 10.0
        if re.fullmatch(r"[\d.,]+", t.replace(",", "")):
            score += 25.0
        elif re.search(r"\d", t):
            score += 5.0
        score += min(len(t), 200) / 40.0
        return score

    @classmethod
    def _uia_snippets_show_result_value(cls, snippets: list[str]) -> bool:
        """True when UIA snippets include a standalone numeric result, not just an expression."""
        for raw in snippets:
            t = raw.strip()
            if re.fullmatch(r"[\d.,]+", t.replace(",", "")):
                return True
            if re.search(r"=\s*[\d.,]+\s*$", t):
                return True
        return False

    @classmethod
    def _read_window_text_uia(
        cls, window_title_re: str | None, *, max_items: int = 15
    ) -> list[str]:
        """Collect ranked visible text snippets from a window (any app)."""
        if sys.platform != "win32":
            return []
        try:
            from pywinauto import Application
            import win32gui

            hwnd: int | None = None
            if window_title_re:
                from pywinauto import findwindows
                pattern = re.compile(window_title_re, re.IGNORECASE)
                for h in findwindows.find_windows(title_re=window_title_re):
                    if pattern.search(win32gui.GetWindowText(h) or ""):
                        hwnd = h
                        break
            if hwnd is None:
                hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return []

            app = Application(backend="uia").connect(handle=hwnd, timeout=5)
            win = app.top_window()
            scored: list[tuple[float, str]] = []
            seen: set[str] = set()

            for ctrl_type in ("Document", "Edit", "Text"):
                for el in win.descendants(control_type=ctrl_type):
                    try:
                        val = getattr(el, "get_value", lambda: None)()
                        if not val:
                            val = el.window_text()
                        text = str(val).strip()
                        if not text or text in seen:
                            continue
                        score = cls._score_ui_snippet(text, ctrl_type)
                        if score < 0:
                            continue
                        seen.add(text)
                        scored.append((score, text))
                    except Exception:
                        continue

            scored.sort(key=lambda x: x[0], reverse=True)
            return [t for _, t in scored[:max_items]]
        except Exception:
            return []

    async def _press_calculator_key_uia(self, key: str, evidence: dict[str, Any]) -> bool:
        if not self._calculator_window_open():
            return False
        try:
            from pywinauto import Application, findwindows

            hwnds = findwindows.find_windows(title_re=r"(?i)calculator")
            if not hwnds:
                return False
            app = Application(backend="uia").connect(handle=hwnds[0])
            win = app.top_window()
            labels = _CALCULATOR_BUTTON_LABELS.get(key.strip().lower(), [])
            if not labels and len(key.strip()) == 1:
                labels = [key.strip()]
            for label in labels:
                strategies = [
                    {"title": label, "control_type": "Button"},
                    {"title_re": f"(?i)^{re.escape(label)}$", "control_type": "Button"},
                    {"title_re": f"(?i){re.escape(label)}"},
                ]
                for kwargs in strategies:
                    try:
                        btn = win.child_window(**kwargs)
                        if btn.exists(timeout=0.5):
                            btn.click_input()
                            evidence["action_log"].append(f"Calculator UIA click: {label}")
                            _agent_dbg(
                                "desktop_worker.py:_press_calculator_key_uia",
                                "uia_click_ok",
                                {"key": key, "label": label},
                            )
                            return True
                    except Exception:
                        continue
            _agent_dbg(
                "desktop_worker.py:_press_calculator_key_uia",
                "uia_click_miss",
                {"key": key, "labels": labels},
            )
            return False
        except Exception as exc:
            evidence["action_log"].append(f"Calculator UIA press failed: {exc}")
            _agent_dbg(
                "desktop_worker.py:_press_calculator_key_uia",
                "uia_click_error",
                {"key": key, "error": str(exc)},
            )
            return False

    async def _press_key(self, key: str, evidence: dict[str, Any]) -> None:
        _agent_dbg("desktop_worker.py:_press_key", "press_key_start", {"key": key})

        if await self._press_calculator_key_uia(key, evidence):
            return

        sequence = self._pywinauto_key_sequence(key)
        try:
            from pywinauto.keyboard import send_keys
            send_keys(sequence)
            evidence["action_log"].append(f"Key press via pywinauto keyboard: {sequence!r}")
            _agent_dbg(
                "desktop_worker.py:_press_key",
                "pywinauto_ok",
                {"key": key, "sequence": sequence},
            )
            return
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto press fallback failed: {exc}")

        import pyautogui
        pyautogui.FAILSAFE = False
        py_name = self._pyautogui_key_name(key)
        pyautogui.press(py_name)
        evidence["action_log"].append(f"Key press via PyAutoGUI fallback: {py_name!r}")
        _agent_dbg(
            "desktop_worker.py:_press_key",
            "pyautogui_ok",
            {"key": key, "py_name": py_name},
        )

    def _run_uia(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> None:
        app_title = self._extract_window_title(spec.goal)
        if app_title:
            try:
                from pywinauto import Application
                app = Application(backend="uia").connect(title_re=app_title, timeout=5)
                win = app.top_window()
                win.wait("visible", timeout=5)
                import io
                tree = self._element_tree(win)
                evidence["element_tree_snapshot"] = json.dumps(tree, ensure_ascii=False)
                evidence["action_log"].append(f"Connected to window: {app_title}")
                buf = io.BytesIO()
                win.capture_as_image().save(buf, format="PNG")
                evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()
            except Exception as exc:
                raise RuntimeError(f"UIA connect failed: {exc}") from exc
        else:
            self._capture_screenshot_fallback(evidence)
            evidence["action_log"].append("No target window identified in goal")

    @staticmethod
    def _element_tree(win: Any, depth: int = 2) -> dict:
        try:
            return {
                "title": str(win.window_text()),
                "control_type": str(win.element_info.control_type),
                "children": [
                    DesktopWorker._element_tree(c, depth - 1)
                    for c in win.children()
                ] if depth > 0 else [],
            }
        except Exception:
            return {}

    @staticmethod
    def _capture_screenshot_fallback(evidence: dict[str, Any]) -> None:
        try:
            import io
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.thumbnail((1280, 720))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()
            evidence["action_log"].append("Screenshot captured via PIL ImageGrab (thumbnail)")
        except Exception as exc:
            evidence["action_log"].append(f"Screenshot failed: {exc}")

    @staticmethod
    def _extract_window_title(goal: str) -> str | None:
        import re
        match = re.search(r'(?:window|app|application)\s+"([^"]+)"', goal, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'(?:window|app|application)\s+([A-Za-z][A-Za-z0-9 ]+)', goal, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None
