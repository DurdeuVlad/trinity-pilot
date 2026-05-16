from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from trinity_pilot.core.types import ObjectiveSpec
from trinity_pilot.llm.base import LLMMessage, LLMProvider, LLMResponse


_ANALYSER_SYSTEM = """\
You are an orchestration analyst for an AI automation system.
A worker has reported a blocking condition it cannot resolve on its own.
Given the objective spec and the retry history, decide one of two actions:

1. "auto_steer": You believe the worker can succeed with revised guidance. Provide a concrete recovery hint.
2. "ask_user": The situation requires human input or clarification. Provide a specific question for the user.

Respond ONLY with a JSON object:
{"action": "auto_steer", "guidance": "<concrete hint>", "question": ""}
or
{"action": "ask_user", "guidance": "", "question": "<specific question for the user>"}

Do NOT include markdown fences. Return only the JSON object.
"""


@dataclass
class SteerDecision:
    action: Literal["auto_steer", "ask_user"]
    guidance: str = ""
    question: str = ""


class OrchestratorAnalyser:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def analyse(
        self,
        spec: ObjectiveSpec,
        retry_context: list[dict[str, Any]],
        blocker_reason: str,
    ) -> SteerDecision:
        """Analyse a blocked objective and return a steering decision.

        Args:
            spec: The objective spec (including goal, metadata, steering context).
            retry_context: List of reflection dicts from ReflectionStore.
            blocker_reason: The reason string from WorkerBlocker.

        Returns:
            SteerDecision with action and either guidance or question.
        """
        context_text = "\n".join(
            f"Attempt {i+1}: {r.get('failure_reason', 'unknown')} -- {r.get('recovery_hint', '')}"
            for i, r in enumerate(retry_context)
        )
        user_msg = (
            f"OBJECTIVE: {spec.goal}\n\n"
            f"BLOCKER: {blocker_reason}\n\n"
            f"RETRY HISTORY ({len(retry_context)} attempts):\n{context_text or 'None'}\n\n"
            "Decide: auto_steer or ask_user?"
        )
        try:
            response: LLMResponse = await self._llm.complete(
                [LLMMessage(role="user", content=user_msg)],
                system=_ANALYSER_SYSTEM,
                timeout=15.0,
            )
        except Exception:
            # Fallback: if analyser call fails, default to auto_steer with the blocker reason
            return SteerDecision(action="auto_steer", guidance=blocker_reason)

        raw = (response.content or "").strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                action = data.get("action", "auto_steer")
                if action not in ("auto_steer", "ask_user"):
                    action = "auto_steer"
                return SteerDecision(
                    action=action,
                    guidance=data.get("guidance", ""),
                    question=data.get("question", ""),
                )
            except Exception:
                pass
        # Parsing failed -- default to auto_steer
        return SteerDecision(action="auto_steer", guidance=raw or blocker_reason)
