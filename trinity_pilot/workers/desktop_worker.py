from __future__ import annotations

import base64
import sys
from typing import Any

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.workers.base import DomainWorker, WorkerError


class DesktopWorker(DomainWorker):
    """Accessibility-first desktop worker. UIA backend on Windows; degrades to screenshot."""

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
        try:
            await self._run_objective(spec, evidence)
        except WorkerError:
            raise
        except Exception as exc:
            evidence["error"] = str(exc)
            raise WorkerError(
                f"Desktop execution failed for '{spec.objective_id}': {exc}"
            ) from exc
        return evidence

    async def _run_objective(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> None:
        if sys.platform != "win32":
            evidence["degraded_mode"] = True
            evidence["action_log"].append("Platform is not win32 — degraded mode")
            self._capture_screenshot_fallback(evidence)
            return

        try:
            self._run_uia(spec, evidence)
        except Exception as exc:
            evidence["degraded_mode"] = True
            evidence["action_log"].append(
                f"UIA failed ({exc}), falling back to screenshot"
            )
            self._capture_screenshot_fallback(evidence)

    def _run_uia(self, spec: ObjectiveSpec, evidence: dict[str, Any]) -> None:
        import json
        from pywinauto import Application, findwindows

        goal_lower = spec.goal.lower()

        app_title = self._extract_window_title(spec.goal)
        if app_title:
            try:
                app = Application(backend="uia").connect(title_re=app_title, timeout=5)
                win = app.top_window()
                win.wait("visible", timeout=5)

                # Capture element tree snapshot
                tree = self._element_tree(win)
                evidence["element_tree_snapshot"] = json.dumps(tree, ensure_ascii=False)
                evidence["action_log"].append(f"Connected to window: {app_title}")

                # Take screenshot via win
                screenshot_path = win.capture_as_image()
                import io
                buf = io.BytesIO()
                screenshot_path.save(buf, format="PNG")
                evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()

            except Exception as exc:
                raise RuntimeError(f"UIA connect failed: {exc}") from exc
        else:
            # No specific window — take a full desktop screenshot as evidence
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
            import pyautogui
            import io
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            evidence["screenshot"] = base64.b64encode(buf.getvalue()).decode()
            evidence["action_log"].append("Screenshot captured via PyAutoGUI")
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
