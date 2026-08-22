from __future__ import annotations

import asyncio
import base64
import json
import re
from typing import Any

from trinity_pilot.core.types import ChecklistItem, FailureReason, ObjectiveSpec, ReviewResult
from trinity_pilot.llm.base import LLMMessage, LLMProvider
from trinity_pilot.reviewer.prompts import CHECKLIST_ITEM_SYSTEM, CHECKLIST_ITEM_USER_TEMPLATE


class ChecklistEvalError(Exception):
    pass


def _extract_json(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1).strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


async def evaluate_checklist(
    spec: ObjectiveSpec,
    evidence: dict[str, Any],
    provider: LLMProvider,
) -> ReviewResult | None:
    """Evaluate the objective's planner-authored verification checklist.

    Returns None when there is nothing to evaluate (no checklist, or every item
    malformed) so the caller falls through to the existing floor/freeform review
    path unchanged. Returns a ReviewResult — pass or hard fail — when at least
    one valid item was evaluated. A single failing item vetoes the objective,
    same hard-veto semantics as the existing write_file/visible_text floors.
    """
    valid_items = [item for item in spec.verification_checklist if item.is_valid()]
    skipped = len(spec.verification_checklist) - len(valid_items)

    if not valid_items:
        return None

    try:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_evaluate_item(item, evidence, provider))
                for item in valid_items
            ]
    except* ChecklistEvalError as eg:
        raise eg.exceptions[0] from None
    results = [t.result() for t in tasks]

    # An item the reviewer couldn't answer (planner under-specified its sensors)
    # is inconclusive, not a failure — it must not veto an otherwise-correct
    # objective. Only an item the reviewer actively answered "no" counts as failed.
    inconclusive = [
        (item, res) for item, res in zip(valid_items, results) if res["insufficient_data"]
    ]
    failed = [
        (item, res)
        for item, res in zip(valid_items, results)
        if not res["passed"] and not res["insufficient_data"]
    ]

    skip_note = f" ({skipped} malformed checklist item(s) skipped)" if skipped else ""
    inconclusive_note = (
        f" ({len(inconclusive)} checklist item(s) inconclusive, not counted)"
        if inconclusive
        else ""
    )

    if failed:
        item, res = failed[0]
        notes = (
            f"Checklist item failed: '{item.instruction}' — {res['notes']}"
            f"{skip_note}{inconclusive_note}"
        )
        return ReviewResult(
            passed=False,
            failure_reason=FailureReason.FAILED_ASSERTION,
            notes=notes,
            recovery_hint=f"Address the unmet checklist item: {item.instruction}",
        )

    answered = len(valid_items) - len(inconclusive)
    return ReviewResult(
        passed=True,
        failure_reason=None,
        notes=f"{answered} checklist item(s) passed{skip_note}{inconclusive_note}",
        recovery_hint="",
    )


async def _evaluate_item(
    item: ChecklistItem,
    evidence: dict[str, Any],
    provider: LLMProvider,
) -> dict[str, Any]:
    sensor_data = {key: evidence.get(key) for key in item.sensors if key in evidence}
    # File observations are a separate evidence channel from process stdout.
    # Include them when present so artifact checklists can verify written files
    # without mistaking file contents (such as script source) for command output.
    if evidence.get("file_readback") and "file_readback" not in sensor_data:
        sensor_data["file_readback"] = evidence["file_readback"]
    screenshot_b64 = sensor_data.pop("screenshot", "") if "screenshot" in sensor_data else ""

    user_msg = CHECKLIST_ITEM_USER_TEMPLATE.format(
        instruction=item.instruction,
        sensor_data_json=json.dumps(sensor_data, indent=2, default=str),
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
        response = await provider.complete(messages=messages, system=CHECKLIST_ITEM_SYSTEM)
    except Exception as exc:
        raise ChecklistEvalError(f"LLM call failed for checklist item: {exc}") from exc

    raw = _extract_json(response.content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChecklistEvalError(
            f"Checklist item reviewer returned invalid JSON: {exc}\nRaw: {response.content}"
        ) from exc

    return {
        "passed": bool(data.get("passed", False)),
        "insufficient_data": bool(data.get("insufficient_data", False)),
        "notes": str(data.get("notes", "")),
    }
