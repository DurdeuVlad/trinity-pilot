"""Validate gemini_mock against other repo modules that use Gemini differently."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Callable

from testing.gemini_mock.activator import activate, deactivate
from testing.gemini_mock.backends.queue_backend import QueueBackend

REPO_ROOT = Path(__file__).resolve().parents[2]
DOM_AGENT_ROOT = REPO_ROOT / "dom-based-web-agent-poc"
POC_VISION_ROOT = REPO_ROOT / "poc-vision-and-click-module"


def _with_sys_path(path: Path) -> None:
    """Prepend one module root to sys.path if it is not already present."""
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def _purge_modules(prefixes: tuple[str, ...]) -> None:
    """Remove imported modules that match the given prefixes."""
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            sys.modules.pop(name, None)


def _run_check(label: str, check: Callable[[], None]) -> bool:
    """Run one validation check and print a PASS/FAIL line."""
    try:
        check()
    except Exception as exc:  # pragma: no cover - script output is the validation artifact
        print(f"FAIL {label}: {exc}")
        return False
    print(f"PASS {label}")
    return True


def _check_google_api_core_stub() -> None:
    """Confirm google.api_core exceptions are importable and catchable."""
    from google.api_core import exceptions as google_exceptions

    assert issubclass(google_exceptions.ResourceExhausted, Exception)
    assert issubclass(google_exceptions.Unauthenticated, Exception)
    try:
        raise google_exceptions.ResourceExhausted("quota")
    except google_exceptions.ResourceExhausted:
        return
    raise AssertionError("ResourceExhausted was not catchable")


def _check_dom_agent_import() -> None:
    """Import the dom-agent reasoner through its real package path."""
    _with_sys_path(DOM_AGENT_ROOT)
    _purge_modules(("src.dom_agent.ai_reasoner",))
    module = importlib.import_module("src.dom_agent.ai_reasoner")
    reasoner = module.AIReasoner(api_key="fake-key")
    assert reasoner.model is not None


def _check_upload_file_contract() -> None:
    """Verify upload_file returns a mock file reference with expected attributes."""
    import google.generativeai as genai

    file_ref = genai.upload_file("/tmp/example.png")
    assert hasattr(file_ref, "name")
    assert hasattr(file_ref, "uri")


def _check_poc_vision_detect() -> None:
    """Run the poc-vision detector through its real detect() entry point."""
    _with_sys_path(POC_VISION_ROOT)
    os.environ["GOOGLE_API_KEY"] = "fake-key"
    _purge_modules(("app.config", "app.detectors.vlm_gemini"))
    backend = QueueBackend()
    backend.push('[{"type":"Edit","label":"Name","bbox":[1,2,3,4],"confidence":0.9}]')
    activate(backend=backend)
    config = importlib.import_module("app.config")
    config.GEMINI_API_KEY = "fake-key"
    detector = importlib.import_module("app.detectors.vlm_gemini")
    detections = detector.detect("missing-file.png")
    assert detections == [
        {
            "method": "GEMINI",
            "type": "Edit",
            "label": "Name",
            "bbox": [1, 2, 3, 4],
            "confidence": 0.9,
        }
    ]


def _check_candidates_chain() -> None:
    """Confirm the nested candidates/content/parts text chain is available."""
    import google.generativeai as genai

    backend = QueueBackend()
    backend.push("candidate text")
    activate(backend=backend)
    response = genai.GenerativeModel("gemini-test").generate_content(["prompt", genai.upload_file("image.png")])
    assert response.text == "candidate text"
    assert response.candidates[0].content.parts[0].text == "candidate text"


def main() -> None:
    """Run all cross-module validation checks and exit non-zero on failure."""
    backend = QueueBackend()
    activate(backend=backend)
    checks = [
        ("google.api_core exceptions available", _check_google_api_core_stub),
        ("dom-agent ai_reasoner import works", _check_dom_agent_import),
        ("upload_file returns MockFile contract", _check_upload_file_contract),
        ("poc-vision detect() works with mock", _check_poc_vision_detect),
        ("MockResponse candidates chain is accessible", _check_candidates_chain),
    ]
    passed = 0
    try:
        for label, check in checks:
            passed += int(_run_check(label, check))
    finally:
        deactivate()
    total = len(checks)
    print(f"Results: {passed}/{total} passed")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
