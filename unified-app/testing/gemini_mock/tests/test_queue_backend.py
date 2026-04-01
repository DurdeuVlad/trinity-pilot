from __future__ import annotations

from testing.gemini_mock.backends.queue_backend import QueueBackend
from testing.gemini_mock.mock_genai import GenerationConfig


def test_queue_backend_consumes_fifo_and_records_calls() -> None:
    backend = QueueBackend(default_response="default")
    config = GenerationConfig(response_mime_type="application/json")

    backend.push("first").push("second")

    assert backend.respond("prompt 1", "model", config) == "first"
    assert backend.respond("prompt 2", "model", config) == "second"
    backend.assert_call_count(2)
    backend.assert_prompt_contains(1, "prompt 2")


def test_queue_backend_returns_default_when_queue_empty() -> None:
    backend = QueueBackend(default_response="default")

    assert backend.respond("prompt", "model", GenerationConfig()) == "default"


def test_queue_backend_returns_cli_plan_default_for_cli_planner_prompt() -> None:
    backend = QueueBackend()
    prompt = (
        "You are a PowerShell automation expert. Generate a JSON plan with PowerShell commands.\n"
        "Generate a JSON plan:\n"
        "{\n"
        '  "plan": []\n'
        "}\n"
    )

    response = backend.respond(prompt, "gemini-2.5-flash", GenerationConfig())

    assert '"plan"' in response
    assert '"command"' in response
    assert '"steps"' not in response


def test_queue_backend_returns_browser_action_default_for_browser_planner_prompt() -> None:
    backend = QueueBackend()
    prompt = (
        "You are a specialized Browser Automation Agent.\n"
        "OUTPUT FORMAT:\n"
        "{\n"
        '  "action": "click" | "type" | "navigate" | "scroll" | "press_key" | "done" | "fail",\n'
        '  "selector": "string",\n'
        '  "value": "string",\n'
        '  "reasoning": "short explanation"\n'
        "}\n"
        "Analyze the screenshot and the tree above. What is the next action?"
    )

    response = backend.respond(prompt, "gemini-2.5-flash", GenerationConfig())

    assert '"action"' in response
    assert '"reasoning"' in response
    assert '"steps"' not in response


def test_queue_backend_returns_desktop_plan_default_for_generic_planner_prompt() -> None:
    backend = QueueBackend()
    prompt = (
        "You are a UI Automation Agent for the application: Notepad.\n"
        "Goal: Translate the User Command into a JSON sequence of actions.\n"
        "Rules:\n"
        "1. Return ONLY a valid JSON array of action objects.\n"
    )

    response = backend.respond(prompt, "gemini-2.5-flash", GenerationConfig())

    assert response.startswith("[")
    assert '"action"' in response
    assert '"text"' in response


def test_queue_backend_returns_success_payload_for_verifier_prompt() -> None:
    backend = QueueBackend()
    prompt = (
        "You are a QA verifier for Notepad.\n"
        'Expected Outcome: "Notepad contains text"\n'
        "Current Application State:\n"
        "Return JSON: { \"success\": true/false, \"reason\": \"explanation\" }\n"
    )

    response = backend.respond(prompt, "gemini-2.5-flash", GenerationConfig())

    assert '"success"' in response
    assert '"reason' in response
    assert '"steps"' not in response


def test_queue_backend_returns_teacher_workflow_plan_for_mixed_demo_prompt() -> None:
    backend = QueueBackend()
    prompt = (
        "Break down the following task into 3-7 atomic steps that can be automated.\n"
        "Task: Search the web for OpenAI, copy the first useful result summary, and paste it into Notepad.\n"
        "Primary domain: web\n"
        "Return JSON with keys: steps, estimated_duration, confidence."
    )

    response = backend.respond(prompt, "gemini-2.5-flash", GenerationConfig())

    assert '"description":"Search the web for OpenAI"' in response
    assert '"domain":"desktop"' in response
    assert '"expected_outcome"' in response


def test_queue_backend_strict_mode_raises_when_exhausted() -> None:
    backend = QueueBackend(strict=True)

    try:
        backend.respond("prompt", "model", GenerationConfig())
    except RuntimeError as exc:
        assert "queue exhausted" in str(exc)
    else:
        raise AssertionError("strict QueueBackend should raise when empty")
