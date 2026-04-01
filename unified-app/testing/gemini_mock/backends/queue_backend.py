"""Queue-backed deterministic Gemini responses for tests."""
from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

from testing.gemini_mock.mock_genai import GenerationConfig, _flatten_prompt

_DEFAULT_MACRO_RESPONSE = '{"steps":["mock step 1","mock step 2"],"estimated_duration":10,"confidence":0.8}'
_DEFAULT_OBJECTIVES_RESPONSE = '{"objectives":["complete the mock task"]}'
_DEFAULT_AGENT_LOOP_RESPONSE = (
    '{"rationale":"Task complete via mock","action_type":"done","module":null,'
    '"parameters":{},"done":true,"result_summary":"Mock task completed successfully"}'
)
_DEFAULT_REFLECTION_RESPONSE = '{"achieved":true,"confidence":0.95,"critique":null}'
_DEFAULT_REPLAN_RESPONSE = '{"revised_objectives":[],"rationale":"no remaining objectives needed"}'
_DEFAULT_CLI_RESPONSE = (
    '{"plan":[{"action":"echo_status","command":"Write-Output \'mock cli step\'",'
    '"verify":"$true","expectedResult":"True","onFailure":"manual_intervention"}],'
    '"requiresAdmin":false,"destructive":false,"estimatedDuration":"1s"}'
)
_DEFAULT_DESKTOP_RESPONSE = '[{"action":"type","text":"mock desktop step"}]'
_DEFAULT_BROWSER_RESPONSE = (
    '{"action":"done","selector":"","value":"","reasoning":"Mock browser objective satisfied."}'
)
_DEFAULT_BROWSER_VERIFY_RESPONSE = '{"success": true, "reasoning": "Mock verification passed."}'
_DEFAULT_QA_VERIFIER_RESPONSE = '{"success": true, "reason": "Mock verification passed."}'
_DEFAULT_TEACHER_WORKFLOW_RESPONSE = (
    '{"steps":['
    '{"description":"Search the web for OpenAI","domain":"web","expected_outcome":"The OpenAI results page or an OpenAI information page is visible."},'
    '{"description":"Copy the first useful result summary","domain":"web","expected_outcome":"The requested summary text has been identified and copied from the page."},'
    '{"description":"Open Notepad and paste the copied text","domain":"desktop","expected_outcome":"Notepad shows the copied summary text."}'
    '],"estimated_duration":45,"confidence":0.85}'
)


class QueueBackend:
    """FIFO backend that records prompts and returns queued responses."""

    def __init__(
        self,
        default_response: str = _DEFAULT_MACRO_RESPONSE,
        strict: bool = False,
    ) -> None:
        self.default_response = default_response
        self.strict = strict
        self.calls: list[dict[str, Any]] = []
        self._queue: deque[str] = deque()
        self._lock = Lock()

    def _default_response_for_prompt(self, prompt_text: str) -> str:
        """Return a schema-compatible default response for the recorded prompt."""

        lowered = prompt_text.lower()
        # ObjectivesDecomposer system prompt
        if "task decomposition assistant" in lowered:
            return _DEFAULT_OBJECTIVES_RESPONSE
        # ReflectionEngine system prompt (both Gemini and OpenAI variants)
        if "achieved" in lowered and "critique" in lowered:
            return _DEFAULT_REFLECTION_RESPONSE
        # MacroPlanner.replan system prompt
        if "revised_objectives" in lowered:
            return _DEFAULT_REPLAN_RESPONSE
        # AgentLoop system prompt
        if "autonomous computer-use agent" in lowered:
            return _DEFAULT_AGENT_LOOP_RESPONSE
        if (
            "primary domain: web" in lowered
            and "notepad" in lowered
            and "copy" in lowered
            and "search" in lowered
        ):
            return _DEFAULT_TEACHER_WORKFLOW_RESPONSE
        if "quality assurance verifier for a browser automation agent" in lowered:
            return _DEFAULT_BROWSER_VERIFY_RESPONSE
        if "powershell automation expert" in lowered and '"plan"' in prompt_text:
            return _DEFAULT_CLI_RESPONSE
        if "you are a qa verifier for" in lowered and "return json" in lowered:
            return _DEFAULT_QA_VERIFIER_RESPONSE
        if "specialized browser automation agent" in lowered and "next action" in lowered:
            return _DEFAULT_BROWSER_RESPONSE
        if "you are a ui automation agent for the application" in lowered and "valid json array of action objects" in lowered:
            return _DEFAULT_DESKTOP_RESPONSE
        return self.default_response

    def push(self, response: str) -> "QueueBackend":
        """Append one response to the queue and return self."""
        with self._lock:
            self._queue.append(response)
        return self

    def push_many(self, responses: list[str]) -> "QueueBackend":
        """Append multiple responses to the queue in order."""
        for response in responses:
            self.push(response)
        return self

    def respond(self, prompt: Any, model_name: str, generation_config: GenerationConfig) -> str:
        """Return the next queued response while recording call metadata."""
        prompt_text = _flatten_prompt(prompt)
        with self._lock:
            self.calls.append(
                {
                    "prompt": prompt_text,
                    "model_name": model_name,
                    "mime_type": generation_config.response_mime_type,
                }
            )
            if self._queue:
                return self._queue.popleft()
        if self.strict:
            raise RuntimeError(f"QueueBackend queue exhausted after {len(self.calls)} call(s)")
        return self._default_response_for_prompt(prompt_text)

    def assert_call_count(self, expected: int) -> None:
        """Assert that the backend saw the expected number of calls."""
        actual = len(self.calls)
        assert actual == expected, f"Expected {expected} Gemini call(s), got {actual}"

    def assert_prompt_contains(self, index: int, substring: str) -> None:
        """Assert that a recorded prompt contains the expected substring."""
        assert index < len(self.calls), f"Call index {index} out of range for {len(self.calls)} call(s)"
        prompt = self.calls[index]["prompt"]
        assert substring in prompt, f"Prompt {index} did not contain {substring!r}: {prompt!r}"

    def reset(self) -> None:
        """Clear the queue and recorded calls."""
        with self._lock:
            self._queue.clear()
            self.calls.clear()
