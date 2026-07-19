from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from trinity_pilot.core.types import FailureReason, ObjectiveSpec, ReviewResult
from trinity_pilot.llm.base import LLMMessage, LLMProvider
from trinity_pilot.reviewer.checklist import evaluate_checklist
from trinity_pilot.reviewer.prompts import REVIEWER_SYSTEM, REVIEWER_USER_TEMPLATE


class ReviewError(Exception):
    pass


def _extract_json(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1).strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


class ObjectiveReviewer:
    def __init__(
        self,
        provider: LLMProvider,
        sensor_call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self._provider = provider
        self._sensor_call = sensor_call
        self.shadow_floor_trigger_count = 0
        self.floor_override_count = 0

    @property
    def floor_override_rate(self) -> float:
        if self.shadow_floor_trigger_count == 0:
            return 0.0
        return self.floor_override_count / self.shadow_floor_trigger_count

    async def review(
        self,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
        *,
        shadow_llm_on_floor_trigger: bool = False,
    ) -> ReviewResult:
        tool_log = evidence.get("tool_call_log")
        if isinstance(tool_log, list) and tool_log:
            final = tool_log[-1]
            if isinstance(final, dict) and final.get("tool") == "finish":
                control = final.get("result", {})
                if control.get("status") == "failure":
                    return ReviewResult(
                        passed=False,
                        failure_reason=FailureReason.FAILED_ASSERTION,
                        notes="Worker tool log recorded an explicit failure finish.",
                    )
        # An exact, sensor-backed completion result is stronger than a model
        # narrative. Workers use it when a final state can be read directly.
        completion = evidence.get("completion")
        if isinstance(completion, dict) and isinstance(completion.get("passed"), bool):
            if completion["passed"]:
                return ReviewResult(
                    passed=True,
                    notes=f"Programmatic completion check passed: {completion.get('summary', 'all postconditions met')}",
                )
            return ReviewResult(
                passed=False,
                failure_reason=FailureReason.FAILED_ASSERTION,
                notes=f"Programmatic completion check failed: {completion.get('summary', 'postcondition unmet')}",
                recovery_hint="Bring the target application into the required final state and capture a fresh readback.",
            )

        # Programmatic ground-truth floor: a write_file action that errored or
        # left no file on disk is an objective failure regardless of what the
        # action_log narrates. Don't let the LLM's text-based judgment override this.
        write_failures = evidence.get("write_file_failures")
        if write_failures:
            paths = ", ".join(str(f.get("path", "?")) for f in write_failures)
            result = ReviewResult(
                passed=False,
                failure_reason=FailureReason.MISSING_ARTIFACT,
                notes=f"Programmatic check: write_file failed or file missing after write for: {paths}",
                recovery_hint="Retry the write_file action and verify the target path is writable and the file exists immediately after writing.",
            )
            return await self._maybe_shadow_floor_review(
                result,
                spec,
                evidence,
                shadow_llm_on_floor_trigger=shadow_llm_on_floor_trigger,
            )

        visible_text_probe = evidence.get("visible_text_probe")
        if (
            isinstance(visible_text_probe, dict)
            and visible_text_probe.get("passed") is False
            and visible_text_probe.get("file_only_delivery") is True
        ):
            result = ReviewResult(
                passed=False,
                failure_reason=FailureReason.MISSING_ARTIFACT,
                notes="Programmatic floor: file-only delivery is insufficient proof of on-screen typing",
                recovery_hint="Retry by typing the expected text into the target desktop application and verify it is visible on screen, not just written to a file.",
            )
            return await self._maybe_shadow_floor_review(
                result,
                spec,
                evidence,
                shadow_llm_on_floor_trigger=shadow_llm_on_floor_trigger,
            )

        # The executor's claims are not proof. When it wrote an artifact, independently
        # re-read its metadata through the sensor MCP before asking the reviewer model.
        # This stays bounded and read-only: at most five sensor calls per review.
        await self._collect_independent_sensors(evidence)

        checklist_result = await evaluate_checklist(spec, evidence, self._provider)
        if checklist_result is not None:
            return checklist_result

        return await self._review_with_llm(spec, evidence)

    async def _collect_independent_sensors(self, evidence: dict[str, Any]) -> None:
        if self._sensor_call is None:
            return
        paths: list[str] = []
        for path in evidence.get("written_files", []):
            if isinstance(path, str):
                paths.append(path)
        for record in evidence.get("tool_call_log", []):
            if not isinstance(record, dict) or record.get("tool") not in {"write_file", "save_file"}:
                continue
            path = record.get("args", {}).get("path")
            if isinstance(path, str):
                paths.append(path)
        seen: set[str] = set()
        sensor_results: list[dict[str, Any]] = []
        for path in paths:
            if path in seen or len(sensor_results) >= 5:
                continue
            seen.add(path)
            try:
                sensor_results.append({
                    "tool": "file_stat",
                    "path": path,
                    "result": await self._sensor_call("file_stat", {"path": path}),
                })
            except Exception as exc:
                sensor_results.append({"tool": "file_stat", "path": path, "error": str(exc)})
        if sensor_results:
            evidence["reviewer_sensor_log"] = sensor_results

    async def _maybe_shadow_floor_review(
        self,
        floor_result: ReviewResult,
        spec: ObjectiveSpec,
        evidence: dict[str, Any],
        *,
        shadow_llm_on_floor_trigger: bool,
    ) -> ReviewResult:
        if not shadow_llm_on_floor_trigger:
            return floor_result

        shadow_result = await self._review_with_llm(spec, evidence)
        self.shadow_floor_trigger_count += 1
        if shadow_result.passed:
            self.floor_override_count += 1
        return floor_result

    async def _review_with_llm(
        self, spec: ObjectiveSpec, evidence: dict[str, Any]
    ) -> ReviewResult:
        import base64

        # Strip raw screenshot bytes from evidence JSON — pass as real image instead.
        # The reviewer must never see executor chain-of-thought or intermediate
        # model prose; only explicit action records and submitted evidence.
        hidden_keys = {"screenshot", "llm_transcript", "thinking", "reasoning"}
        evidence_for_json = {k: v for k, v in evidence.items() if k not in hidden_keys}
        screenshot_b64: str = evidence.get("screenshot", "")

        user_msg = REVIEWER_USER_TEMPLATE.format(
            spec_json=json.dumps(spec.to_dict(), indent=2),
            evidence_json=json.dumps(evidence_for_json, indent=2),
        )

        image_data: bytes | None = None
        if screenshot_b64:
            try:
                image_data = base64.b64decode(screenshot_b64)
            except Exception:
                image_data = None

        messages = [LLMMessage(
            role="user",
            content=user_msg,
            image_data=image_data,
            image_mime="image/jpeg",
        )]

        try:
            response = await self._provider.complete(
                messages=messages,
                system=REVIEWER_SYSTEM,
            )
        except Exception as exc:
            raise ReviewError(f"LLM call failed: {exc}") from exc

        raw = _extract_json(response.content)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReviewError(
                f"Reviewer returned invalid JSON: {exc}\nRaw: {response.content}"
            ) from exc

        passed = bool(data.get("passed", False))
        notes = str(data.get("notes", ""))

        failure_reason: FailureReason | None = None
        if not passed:
            raw_reason = data.get("failure_reason")
            if raw_reason:
                try:
                    failure_reason = FailureReason(raw_reason)
                except ValueError:
                    # Unrecognised reason — default to failed_assertion
                    failure_reason = FailureReason.FAILED_ASSERTION

        recovery_hint = str(data.get("recovery_hint", ""))
        return ReviewResult(
            passed=passed,
            failure_reason=failure_reason,
            notes=notes,
            recovery_hint=recovery_hint,
        )
