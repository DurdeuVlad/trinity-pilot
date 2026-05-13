from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
from typing import Any

from trinity_pilot.core.types import DomainType, ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError
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


class DesktopWorker(DomainWorker):
    """LLM-driven desktop worker: generates action plan then executes it."""

    def __init__(self) -> None:
        super().__init__()

    async def execute(self, spec: ObjectiveSpec) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "domain": "desktop",
            "objective_id": spec.objective_id,
            "screenshot": None,
            "element_tree_snapshot": None,
            "action_log": [],
            "degraded_mode": False,
            "error": None,
        }
        timeout_seconds = int(spec.metadata.get("timeout_seconds", 60))
        try:
            await asyncio.wait_for(
                self._run_objective(spec, evidence),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise WorkerError(
                f"Desktop timeout after {timeout_seconds}s for '{spec.objective_id}'"
            )
        except WorkerError:
            raise
        except Exception as exc:
            evidence["error"] = str(exc)
            raise WorkerError(
                f"Desktop execution failed for '{spec.objective_id}': {exc}"
            ) from exc
        validate_evidence(DomainType.DESKTOP, evidence)
        return evidence

    async def _run_objective(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> None:
        if sys.platform != "win32":
            evidence["degraded_mode"] = True
            evidence["action_log"].append("Platform is not win32 — degraded mode")
            self._capture_screenshot_fallback(evidence)
            return

        # Try UIA automation
        uia_ok = False
        try:
            import pywinauto  # noqa: F401 — probe import only
            uia_ok = True
        except Exception as exc:
            evidence["degraded_mode"] = True
            evidence["action_log"].append(f"UIA failed: {exc}")

        if uia_ok:
            try:
                actions = await self._generate_actions(spec.goal)
                evidence["action_log"].append(f"Generated {len(actions)} action steps")
                await self._execute_actions(actions, evidence)
                # Record any files written for reviewer verification
                written = [
                    a["path"] for a in actions
                    if a.get("action") == "write_file"
                    and isinstance(a.get("path"), str)
                ]
                for p in written:
                    import pathlib
                    evidence["action_log"].append(
                        f"File exists after execution: {p} = {pathlib.Path(p).exists()}"
                    )
            except Exception as exc:
                evidence["degraded_mode"] = True
                evidence["action_log"].append(f"Action generation/execution failed: {exc}")

        # Always attempt screenshot fallback
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
        # Strip markdown fences if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*(?:```|$)", raw)
        if match:
            raw = match.group(1).strip()
        return json.loads(raw)

    async def _execute_actions(
        self, actions: list[dict[str, Any]], evidence: dict[str, Any]
    ) -> None:
        import subprocess

        import pyautogui

        pyautogui.FAILSAFE = False  # worker runs in background thread

        for step in actions:
            act = step.get("action", "")
            try:
                if act == "launch":
                    app = step["app"]
                    # Normalize path arguments: forward slashes → backslashes on Windows
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
                    pyautogui.write(text, interval=interval)
                    await asyncio.sleep(0.1)
                    evidence["action_log"].append(f"Typed {len(text)} chars")

                elif act == "hotkey":
                    keys = step["keys"]
                    pyautogui.hotkey(*keys)
                    await asyncio.sleep(0.3)
                    evidence["action_log"].append(f"Hotkey: {'+'.join(keys)}")

                elif act == "press":
                    key = step["key"]
                    pyautogui.press(key)
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
                    # Add preview to evidence for reviewer
                    preview = content[:500] + ("..." if len(content) > 500 else "")
                    evidence["action_log"].append(f"Wrote file: {path} ({len(content)} chars)")
                    evidence[f"file_content_{pathlib.Path(path).name}"] = preview

                else:
                    evidence["action_log"].append(f"Unknown action ignored: {act}")

            except Exception as exc:
                evidence["action_log"].append(f"Action '{act}' failed: {exc}")

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

            import pyautogui
            img = pyautogui.screenshot()
            # Shrink to thumbnail to keep evidence payloads small.
            img.thumbnail((640, 360))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=40)
            evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()
            evidence["action_log"].append("Screenshot captured via PyAutoGUI (thumbnail)")
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
