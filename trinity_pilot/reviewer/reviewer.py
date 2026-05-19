from __future__ import annotations

import json
import re
from typing import Any

from trinity_pilot.core.types import FailureReason, ObjectiveSpec, ReviewResult
from trinity_pilot.llm.base import LLMMessage, LLMProvider
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

    async def review(
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
