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
)
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError
from trinity_pilot.workers.evidence_schema import validate_evidence

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

Available tools:
- launch_app: Launch an application by executable name.
- focus_window: Focus a window by title regex.
- type_text: Type text into the currently focused window.
- press_hotkey: Press a keyboard hotkey combination.
- press_key: Press a single key.
- write_file: Write text content directly to a file at an absolute path.
- wait: Pause execution for a number of seconds.
- finish: Signal that the objective is complete or definitively failed.
- report_blocking: Signal an unresolvable blocker requiring orchestrator intervention.

CRITICAL RULES:
- ALWAYS use write_file to save content to disk. NEVER use GUI save dialogs.
- Call finish when the objective is done or definitively cannot be completed.
- Call report_blocking only if you genuinely cannot proceed without external input.
- Use forward slashes in all file paths.
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


class DesktopWorker(AgenticWorkerMixin, DomainWorker):
    """LLM-driven desktop worker using ReAct loop."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        if llm is None:
            from trinity_pilot.llm.gemini import GeminiProvider
            llm = GeminiProvider(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
            )
        super().__init__(llm=llm)

    def _worker_system_prompt(self) -> str:
        return _DESKTOP_AGENT_SYSTEM

    def _worker_tools(self) -> list[genai_types.Tool]:
        return [_make_tool([
            _launch_app_decl,
            _focus_window_decl,
            _type_text_decl,
            _press_hotkey_decl,
            _press_key_decl,
            _desktop_write_file_decl,
            _wait_decl,
            _finish_decl,
            _report_blocking_decl,
        ])]

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
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
            "degraded_mode": False,
            "error": None,
        }
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 60))
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

        if tool_name == "launch_app":
            app = args["app"]
            raw_args = args.get("args", "")
            app_args = raw_args.split() if raw_args else []
            app_args = [a.replace("/", "\\") if isinstance(a, str) else a for a in app_args]
            subprocess.Popen([app, *app_args])
            wait = float(args.get("wait", 1.5))
            await asyncio.sleep(wait)
            evidence["action_log"].append(f"Launched: {app}")
            return f"Launched {app}"

        elif tool_name == "focus_window":
            title_re = args["title_re"]
            wait = float(args.get("wait", 0.5))
            try:
                from pywinauto import Application
                app = Application(backend="uia").connect(title_re=title_re, timeout=5)
                win = app.top_window()
                win.set_focus()
            except Exception:
                pass
            await asyncio.sleep(wait)
            evidence["action_log"].append(f"Focused: {title_re}")
            return f"Focused window: {title_re}"

        elif tool_name == "type_text":
            text = args["text"]
            interval = float(args.get("interval", 0.03))
            await self._type_text(text, interval, evidence)
            await asyncio.sleep(0.1)
            evidence["typed_text"] = evidence.get("typed_text", "") + text
            evidence["action_log"].append(f"Typed {len(text)} chars")
            return f"Typed {len(text)} chars"

        elif tool_name == "press_hotkey":
            keys_str = args["keys"]
            keys = [k.strip() for k in keys_str.split(",")]
            await self._hotkey(keys, evidence)
            await asyncio.sleep(0.3)
            evidence["action_log"].append(f"Hotkey: {keys_str}")
            return f"Pressed hotkey: {keys_str}"

        elif tool_name == "press_key":
            key = args["key"]
            await self._press_key(key, evidence)
            await asyncio.sleep(0.2)
            evidence["action_log"].append(f"Press: {key}")
            return f"Pressed key: {key}"

        elif tool_name == "write_file":
            path = args["path"]
            content = args["content"]
            import pathlib
            pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(path).write_text(content, encoding="utf-8")
            evidence["written_files"].append(path)
            preview = content[:500] + ("..." if len(content) > 500 else "")
            evidence["action_log"].append(f"Wrote file: {path} ({len(content)} chars)")
            evidence[f"file_content_{pathlib.Path(path).name}"] = preview
            return f"File written: {path} ({len(content)} chars)"

        elif tool_name == "wait":
            secs = float(args.get("seconds", 0.5))
            await asyncio.sleep(secs)
            evidence["action_log"].append(f"Waited {secs}s")
            return f"Waited {secs}s"

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
            model=os.getenv("GEMINI_WORKER_MODEL", "gemini-2.0-flash"),
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
                    subprocess.Popen([app, *args])
                    wait = float(step.get("wait", 1.5))
                    await asyncio.sleep(wait)
                    evidence["action_log"].append(f"Launched: {app}")

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
                    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
                    pathlib.Path(path).write_text(content, encoding="utf-8")
                    preview = content[:500] + ("..." if len(content) > 500 else "")
                    evidence["action_log"].append(f"Wrote file: {path} ({len(content)} chars)")
                    evidence[f"file_content_{pathlib.Path(path).name}"] = preview

                else:
                    evidence["action_log"].append(f"Unknown action ignored: {act}")

            except Exception as exc:
                evidence["action_log"].append(f"Action '{act}' failed: {exc}")

    @staticmethod
    async def _type_text(text: str, interval: float, evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            send_keys(text, pause=interval, with_spaces=True, with_tabs=True, with_newlines=True)
            evidence["action_log"].append("Typed via pywinauto keyboard")
            return
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto type fallback failed: {exc}")

        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.write(text, interval=interval)
        evidence["action_log"].append("Typed via PyAutoGUI fallback")

    @staticmethod
    async def _hotkey(keys: list[str], evidence: dict[str, Any]) -> None:
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
    async def _press_key(key: str, evidence: dict[str, Any]) -> None:
        try:
            from pywinauto.keyboard import send_keys
            key_name = key.upper()
            send_keys(f"{{{key_name}}}")
            evidence["action_log"].append("Key press via pywinauto keyboard")
            return
        except Exception as exc:
            evidence["action_log"].append(f"pywinauto press fallback failed: {exc}")

        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.press(key)
        evidence["action_log"].append("Key press via PyAutoGUI fallback")

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
            img.thumbnail((640, 360))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=40)
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
