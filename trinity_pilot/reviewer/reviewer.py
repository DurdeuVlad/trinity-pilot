from __future__ import annotations

import json
import re
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
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider
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

        checklist_result = await evaluate_checklist(spec, evidence, self._provider)
        if checklist_result is not None:
            return checklist_result

        return await self._review_with_llm(spec, evidence)

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
        evidence_for_json = {k: v for k, v in evidence.items() if k != "screenshot"}
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
