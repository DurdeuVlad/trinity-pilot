"""SingleAgentWorker — ablation baseline that merges all domain tools into one agent.

No Planner, no DAG, no Reviewer, no retry-with-reflection.
One ReAct loop with all tools available simultaneously.
Used for the ablation experiment in the CSSC-2026 paper.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from google.genai import types as genai_types

from trinity_pilot.core.types import DomainType, ObjectiveSpec, RiskClass
from trinity_pilot.llm.base import LLMProvider
from trinity_pilot.workers.agentic_mixin import (
    AgenticWorkerMixin,
    _finish_decl,
    _make_tool,
    _report_blocking_decl,
    _take_screenshot_decl,
)
from trinity_pilot.workers.base import DomainWorker, WorkerError
from trinity_pilot.workers.browser_worker import (
    _click_decl,
    _fill_decl,
    _navigate_decl,
    _read_page_decl,
)
from trinity_pilot.workers.desktop_worker import (
    _focus_window_decl,
    _get_clipboard_decl,
    _launch_app_decl,
    _press_hotkey_decl,
    _press_key_decl,
    _type_text_decl,
    _wait_decl,
)
from trinity_pilot.workers.terminal_worker import _run_command_decl, _write_file_decl
from trinity_pilot.workers.worker_result import WorkerResult
from trinity_pilot.workers.write_verification import verify_and_write_file

_MAX_OUTPUT_CHARS = 10_000
_CMD_TIMEOUT = 30.0

_SA_SYSTEM = """\
You are a single-agent task executor on Windows with access to browser, terminal, and desktop tools.
Use the available tools to accomplish the goal step by step.

Tool categories:
- SENSOR tools read, inspect, measure, and detect. They never change world state.
  Use them freely before and after actions to verify state.
- ACTION tools create, modify, execute, or delete. They change world state.
  Each action must be intentional. Prefer sensing first, then acting.

Available tools:

[SENSOR] screenshot: Capture the current screen as visual evidence.
[SENSOR] read_page: Read current browser page title, URL, and DOM text preview.
[SENSOR] clipboard_read: Read current clipboard text.

[ACTION] navigate: Navigate the browser to a URL.
[ACTION] click: Click a CSS selector on the current page.
[ACTION] fill: Fill an input field on the current page.
[ACTION] run_command: Execute a PowerShell command.
[ACTION] write_file: Write text content directly to a file at an absolute path.
[ACTION] launch_app: Launch an application by executable name.
[ACTION] focus_window: Focus a window by title regex.
[ACTION] type_text: Type text into the currently focused window.
[ACTION] press_hotkey: Press a keyboard hotkey combination.
[ACTION] press_key: Press a single key.
[ACTION] wait: Pause execution for a number of seconds.
[ACTION] finish: Signal that the objective is complete or definitively failed.
[ACTION] report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

RULES:
- After each ACTION tool call, read its result before proceeding. If a tool failed
  or produced unexpected state, adapt — do not blindly continue.
- For browser tasks: call `navigate` directly — the browser is already running headless.
  Do NOT use launch_app to open a browser. Just call navigate(url=...) as the first tool.
- For desktop tasks: launch_app first, then focus_window before sending any keystrokes.
- For terminal tasks: use run_command for PowerShell commands; use write_file to write files.
- ALWAYS use write_file to save content to disk. NEVER use GUI save dialogs (Ctrl+S).
- Always use backslash-escaped paths in run_command: C:\\\\Users\\\\User\\\\file.txt
- For write_file paths you may use forward slashes: C:/Users/User/file.txt
- For terminal tasks, prefer targeted commands over broad ones. Example: use
  `hostname` and `(Get-WmiObject Win32_OperatingSystem).Caption` instead of `systeminfo`.
  Avoid `systeminfo` — it is slow and produces excessive output.
- CRITICAL: Call finish(status="success") IMMEDIATELY after the task is complete.
  Do NOT take extra steps to verify, screenshot, or double-check after calling write_file
  or run_command successfully. Trust the tool result and call finish right away.
- Call report_blocking only if you genuinely cannot proceed without external input.
"""


class SingleAgentWorker(AgenticWorkerMixin, DomainWorker):
    """Single-agent ablation baseline: all domain tools, one ReAct loop."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.gemini import GeminiProvider
            llm = GeminiProvider(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.5-flash"),
            )
        super().__init__(llm=llm)
        # Browser state (lazy init on first browser tool call)
        self._page: Any = None
        self._pw: Any = None
        self._pw_browser: Any = None
        self._pw_context: Any = None
        # Desktop state
        self._target_window: str | None = None
        # Terminal workspace
        self._workspace: str | None = None

    # ------------------------------------------------------------------
    # AgenticWorkerMixin interface
    # ------------------------------------------------------------------

    def _worker_system_prompt(self) -> str:
        return _SA_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            # browser
            _navigate_decl, _click_decl, _fill_decl, _read_page_decl,
            # terminal (write_file covers desktop write_file too — same schema)
            _run_command_decl, _write_file_decl,
            # desktop
            _launch_app_decl, _focus_window_decl, _type_text_decl,
            _press_hotkey_decl, _press_key_decl, _wait_decl, _get_clipboard_decl,
            # common
            _take_screenshot_decl, _finish_decl, _report_blocking_decl,
        ])]

    def _worker_environment_context(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> str:
        import pathlib
        platform_name = "Windows" if sys.platform == "win32" else sys.platform
        desktop = str(pathlib.Path.home() / "Desktop").replace("\\", "/")
        username = os.environ.get("USERNAME") or os.environ.get("USER") or "User"
        workspace = evidence.get("workspace", "")
        lines = [
            "ENVIRONMENT:",
            f"  Platform: {platform_name}",
            f"  Username: {username}",
            f"  Desktop: {desktop}",
        ]
        if workspace:
            lines.append(f"  Terminal workspace: {workspace}")
        return "\n".join(lines)

    def _worker_state_snapshot(self, evidence: dict[str, Any]) -> str:
        action_log = evidence.get("action_log", [])
        last_action = action_log[-1] if action_log else "none"
        page_url = evidence.get("page_url") or "about:blank"
        return f"last_action={last_action}\nbrowser_url={page_url}"

    # ------------------------------------------------------------------
    # Browser helpers
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WorkerError("playwright not installed — cannot use browser tools") from exc
        self._pw = await async_playwright().start()
        self._pw_browser = await self._pw.chromium.launch(headless=True, args=["--no-sandbox"])
        self._pw_context = await self._pw_browser.new_context()
        self._page = await self._pw_context.new_page()

    async def _cleanup_browser(self) -> None:
        for attr, method in (
            ("_page", "close"),
            ("_pw_context", "close"),
            ("_pw_browser", "close"),
            ("_pw", "stop"),
        ):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    await getattr(obj, method)()
                except Exception:
                    pass
                setattr(self, attr, None)

    # ------------------------------------------------------------------
    # Desktop helpers (borrowed from DesktopWorker)
    # ------------------------------------------------------------------

    async def _focus_window(self, title_re: str, evidence: dict[str, Any]) -> bool:
        import ctypes
        import ctypes.wintypes
        import time

        pattern = re.compile(title_re, re.IGNORECASE)
        user32 = ctypes.windll.user32

        def _find_hwnd() -> int | None:
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
                    return False
                return True

            user32.EnumWindows(_cb, 0)
            return found[0] if found else None

        try:
            deadline = time.monotonic() + 30
            hwnd: int | None = None
            while time.monotonic() < deadline:
                hwnd = _find_hwnd()
                if hwnd:
                    break
                await asyncio.sleep(0.5)
            if not hwnd:
                evidence["action_log"].append(f"focus_window failed: {title_re!r} not visible after 30s")
                return False
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Focused: {title_re}")
            return True
        except Exception as exc:
            evidence["action_log"].append(f"focus_window failed ({title_re}): {exc}")
            return False

    async def _ensure_target_focused(self, evidence: dict[str, Any]) -> None:
        if not self._target_window:
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            active = buf.value or ""
            if re.search(self._target_window, active, re.IGNORECASE):
                return
            await self._focus_window(self._target_window, evidence)
        except Exception:
            pass

    async def _type_text(self, text: str, interval: float, evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            send_keys(text, pause=interval, with_spaces=True, with_tabs=True, with_newlines=True)
            evidence["action_log"].append("Typed via pywinauto keyboard")
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto type fallback: {exc}")
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.write(text, interval=interval)

    async def _hotkey(self, keys: list[str], evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            modifier_map = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
            mods = "".join(modifier_map[k.lower()] for k in keys[:-1] if k.lower() in modifier_map)
            send_keys(f"{mods}{keys[-1]}")
            evidence["action_log"].append("Hotkey via pywinauto")
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto hotkey fallback: {exc}")
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.hotkey(*keys)

    async def _press_key(self, key: str, evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            send_keys(f"{{{key.upper()}}}")
            evidence["action_log"].append("Key press via pywinauto")
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto press fallback: {exc}")
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press(key)

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def _dispatch_tool(
        self, tool_name: str, args: dict[str, Any], evidence: dict[str, Any]
    ) -> Any:
        # ── Browser tools ──────────────────────────────────────────────
        if tool_name == "navigate":
            await self._ensure_browser()
            url = args["url"]
            try:
                response = await self._page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            except Exception as nav_err:
                return (
                    f"NAVIGATION FAILED: {nav_err}. "
                    "The URL is unreachable. Call finish with status=failure."
                )
            evidence["page_url"] = self._page.url
            evidence["page_http_status"] = response.status if response is not None else None
            status_info = f" (HTTP {response.status})" if response is not None else ""
            evidence["action_log"].append(f"navigate: {url}{status_info}")
            return f"Navigated to {url}{status_info}"

        elif tool_name == "click":
            await self._ensure_browser()
            selector = args["selector"]
            await self._page.click(selector, timeout=10_000)
            evidence["action_log"].append(f"click: {selector}")
            return f"Clicked {selector}"

        elif tool_name == "fill":
            await self._ensure_browser()
            selector = args["selector"]
            value = args["value"]
            await self._page.fill(selector, value, timeout=10_000)
            evidence["action_log"].append(f"fill: {selector}")
            return f"Filled {selector} with {value!r}"

        elif tool_name == "read_page":
            await self._ensure_browser()
            title = await self._page.title()
            url = self._page.url
            dom_raw = await self._page.content()
            dom_text = re.sub(r"<[^>]+>", " ", dom_raw)
            dom_text = re.sub(r"\s+", " ", dom_text).strip()[:2000]
            evidence["page_title"] = title
            evidence["page_url"] = url
            evidence["action_log"].append(f"read_page: {url!r}")
            return f"title={title!r} url={url}\ntext={dom_text}"

        # ── Terminal tools ─────────────────────────────────────────────
        elif tool_name == "run_command":
            from trinity_pilot.workers.terminal_worker import TerminalWorker
            command = args["command"]
            allow_failure = args.get("allow_failure", False)
            cwd = self._workspace or tempfile.gettempdir()
            stdout, stderr, exit_code = await TerminalWorker._run_command(command, cwd=cwd)
            evidence["stdout"] = stdout[-_MAX_OUTPUT_CHARS:]
            evidence["stderr"] = stderr[-_MAX_OUTPUT_CHARS:]
            evidence["exit_code"] = exit_code
            evidence["action_log"].append(f"run_command: exit={exit_code} cmd={command[:100]}")
            if exit_code != 0 and not allow_failure:
                return f"FAILED exit={exit_code}\nstderr: {stderr[:500]}\nstdout: {stdout[:200]}"
            return f"exit={exit_code}\nstdout: {stdout[:1000]}\nstderr: {stderr[:200]}"

        elif tool_name == "write_file":
            path = args["path"]
            content = args["content"]
            result = verify_and_write_file(path, content, evidence)
            if evidence.get("write_file_failures") and any(
                "PermissionError" in f.get("error", "") for f in evidence["write_file_failures"]
            ):
                return f"PERMISSION DENIED: Cannot write to {path}. Call finish with status=failure."
            evidence.setdefault("created_files", []).append(path)
            return result

        # ── Desktop tools ──────────────────────────────────────────────
        elif tool_name == "launch_app":
            import subprocess as _subprocess
            app = args["app"]
            raw_args = args.get("args", "")
            app_args = raw_args.split() if raw_args else []
            app_args = [a.replace("/", "\\") for a in app_args if isinstance(a, str)]
            # Browser app names: redirect to navigate tool instead of launching exe
            _BROWSER_APPS = {"chrome", "chrome.exe", "chromium", "chromium.exe",
                             "msedge", "msedge.exe", "firefox", "firefox.exe",
                             "browser", "iexplore.exe", "iexplore"}
            if app.lower() in _BROWSER_APPS:
                return (
                    "Browser is already running headless. "
                    "Use navigate(url=...) to go to a URL instead of launch_app."
                )
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
                        return f"Reused existing {app} window"
                except Exception:
                    pass
            _subprocess.Popen([app, *app_args])
            wait = float(args.get("wait", 1.5))
            await asyncio.sleep(wait)
            evidence["action_log"].append(f"Launched: {app}")
            return f"Launched {app}"

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
                return (
                    f"🛑 BLOCKED: type_text called with {len(text)} characters. "
                    f"Maximum per call is {_MAX_TYPE_CHARS}. Use write_file instead."
                )
            interval = float(args.get("interval", 0.03))
            await self._ensure_target_focused(evidence)
            await self._type_text(text, interval, evidence)
            await asyncio.sleep(0.1)
            evidence["action_log"].append(f"Typed {len(text)} chars")
            return f"Typed {len(text)} chars"

        elif tool_name == "press_hotkey":
            keys = [k.strip() for k in args["keys"].split(",")]
            await self._ensure_target_focused(evidence)
            await self._hotkey(keys, evidence)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Hotkey: {args['keys']}")
            return f"Pressed hotkey: {args['keys']}"

        elif tool_name == "press_key":
            key = args["key"]
            await self._ensure_target_focused(evidence)
            await self._press_key(key, evidence)
            await asyncio.sleep(0.2)
            evidence["action_log"].append(f"Press: {key}")
            return f"Pressed key: {key}"

        elif tool_name == "wait":
            secs = float(args.get("seconds", 0.5))
            await asyncio.sleep(secs)
            evidence["action_log"].append(f"Waited {secs}s")
            return f"Waited {secs}s"

        elif tool_name == "clipboard_read":
            import subprocess as _subprocess
            try:
                result = _subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard"],
                    capture_output=True, text=True, timeout=5,
                )
                text = result.stdout.strip()
                evidence["action_log"].append(f"clipboard_read: {text[:100]!r}")
                return text if text else "(clipboard is empty)"
            except Exception as exc:
                evidence["action_log"].append(f"clipboard_read failed: {exc}")
                return f"clipboard_read failed: {exc}"

        else:
            return await super()._dispatch_tool(tool_name, args, evidence)

    # ------------------------------------------------------------------
    # Public execution API
    # ------------------------------------------------------------------

    async def execute_raw(self, task: str, *, max_steps: int = 20) -> WorkerResult:
        """Run a raw task string through the ReAct loop. No ObjectiveSpec required."""
        spec = ObjectiveSpec(
            objective_id="sa_task",
            goal=task,
            dependencies=[],
            domain=DomainType.MIXED,
            required_capabilities=[],
            risk_class=RiskClass.MEDIUM,
            preconditions=[],
            success_tests=[],
            evidence_bundle=["action_log"],
            max_attempts=1,
            rollback_or_abort_rule="abort on failure",
            metadata={"max_agent_steps": max_steps},
        )
        evidence: dict[str, Any] = {
            "domain": "single_agent",
            "objective_id": "sa_task",
            "action_log": [],
        }
        self._workspace = tempfile.mkdtemp(prefix="trinity-sa-")
        evidence["workspace"] = self._workspace

        import datetime as _dt
        _ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S_%f")[:19]
        _log_dir = Path(os.path.expanduser("~")) / ".ai" / "sa_logs"
        _log_path = _log_dir / f"sa_run_{_ts}.json"
        _result: WorkerResult | None = None
        try:
            _result = await self.run_loop(spec, evidence, max_steps=max_steps)
            return _result
        except Exception as exc:
            _result = WorkerResult(status="failure", summary=f"{type(exc).__name__}: {exc}", evidence=evidence)
            return _result
        finally:
            try:
                import json as _json
                _log_dir.mkdir(parents=True, exist_ok=True)
                _log_path.write_text(_json.dumps({
                    "task": task,
                    "status": _result.status if _result else "exception",
                    "summary": _result.summary if _result else "",
                    "steps_taken": _result.steps_taken if _result else 0,
                    "tokens_used": _result.tokens_used if _result else 0,
                    "action_log": evidence.get("action_log", []),
                    "llm_transcript": evidence.get("llm_transcript", []),
                    "exit_code": evidence.get("exit_code"),
                    "stdout": (evidence.get("stdout") or "")[:5000],
                    "stderr": (evidence.get("stderr") or "")[:2000],
                    "created_files": evidence.get("created_files", []),
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
            await self._cleanup_browser()
            if self._workspace:
                shutil.rmtree(self._workspace, ignore_errors=True)
                self._workspace = None

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        max_steps = int(spec.metadata.get("max_agent_steps", 40))
        result = await self.execute_raw(spec.goal, max_steps=max_steps)
        return {
            "domain": "single_agent",
            "worker_result_status": result.status,
            "worker_result_summary": result.summary,
            **result.evidence,
            "objective_id": spec.objective_id,
        }
