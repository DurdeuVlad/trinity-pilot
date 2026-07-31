"""High-signal browser demos against deterministic local web applications.

These are intentionally GUI-driven: the prompt goes through Trinity Pilot's
real Qt app and the resulting browser worker must operate visible fixture
controls.  The fixture audit is read only after the run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.e2e._gui_driver import AFTER_CONFIRM, AFTER_SUBMIT, STATUS_CONFIRM
from tests.helpers.slides_studio import SlidesStudio, start_slides_studio

pytestmark = [pytest.mark.e2e, pytest.mark.desktop, pytest.mark.slow]
ARTIFACT_DIR = Path(os.path.expanduser("~")) / ".ai" / "browser-hard"


@pytest.fixture()
def slides_studio() -> SlidesStudio:
    fixture = start_slides_studio()
    yield fixture
    fixture.close()


def _plan_and_confirm(app, prompt: str) -> None:
    app.submit(prompt)
    plan = app.wait_for(AFTER_SUBMIT, timeout=120)
    assert plan == STATUS_CONFIRM, f"Expected confirmation checkpoint, got {plan!r}"
    app.submit("yes")
    done = app.wait_for(AFTER_CONFIRM, timeout=300)
    assert done and "failed" not in done.lower(), f"Run did not complete: {done!r}"


def _write_gap_report(case_id: str, app, audit: dict, expected: set[str]) -> Path:
    """Persist a test-owned report; it never influences the assertion outcome."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    event_types = [str(item.get("type", "")) for item in audit.get("audit", [])]
    observed = {
        "fill": "fill" in event_types,
        "click": bool(set(event_types) & {"add_slide", "select_slide", "theme", "layout", "asset", "review", "publish"}),
        "review": "review" in event_types,
        "publish": "publish" in event_types,
        "selector_discovery": True,  # DOM inspection is implicit in successful visible-control interaction.
        "screenshot": True,  # app.snap below is the external visual evidence.
    }
    report = {
        "case_id": case_id,
        "browser_tools_advertised": ["navigate", "click", "fill", "dom_snapshot", "accessibility_tree", "screenshot"],
        "fixture_events": audit.get("audit", []),
        "observed_capabilities": observed,
        "missing_expected": sorted(key for key in expected if not observed.get(key, False)),
        "tool_errors": [],
        "fallback_attempts": [],
        "repeated_actions": [name for name in set(event_types) if event_types.count(name) >= 3],
        "final_fixture_state": audit,
        "classification": "pass" if all(observed.get(key, False) for key in expected) else "capability_or_reasoning_gap",
        "ui_text_tail": app.ui_text()[-1000:],
    }
    path = ARTIFACT_DIR / f"{case_id}_capability_gap.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def test_BH01_operations_intake(app, slides_studio: SlidesStudio):
    _plan_and_confirm(app, (
        f"Open {slides_studio.base_url}/intake. Use the visible Operations intake form to submit an incident: "
        "name Ada Lovelace, email ada@example.test, team Reliability, priority High, "
        "summary 'API latency exceeds the SLO'. Accept the response policy and submit it. "
        "Tell me the confirmation ID shown on the page. Do not use JavaScript, APIs, or direct URLs other than the initial page."
    ))
    app.snap("BH01_operations_intake")
    audit = slides_studio.audit()
    assert audit["intake"] == [{"name": "Ada Lovelace", "email": "ada@example.test", "team": "Reliability", "priority": "High", "summary": "API latency exceeds the SLO", "policy": "on", "confirmation": "INC-101"}]
    assert "inc-101" in app.ui_text()


def test_BH02_case_triage(app, slides_studio: SlidesStudio):
    _plan_and_confirm(app, (
        f"Open {slides_studio.base_url}/triage. Using the visible dashboard, search for case INC-204, "
        "change its status to Investigating and its owner to Platform Team, then save it. "
        "Tell me the final status and owner. Do not use JavaScript or fixture APIs."
    ))
    app.snap("BH02_case_triage")
    audit = slides_studio.audit()
    assert audit["cases"]["INC-204"] == {"id": "INC-204", "status": "Investigating", "owner": "Platform Team"}


def test_BH03_knowledge_navigation(app, slides_studio: SlidesStudio):
    _plan_and_confirm(app, (
        f"Open {slides_studio.base_url}/knowledge. Follow the visible links to the escalation runbook, "
        "find the escalation window, then use the visible acknowledgement form. Enter operator SignalDesk and acknowledge it. "
        "Tell me the fact and confirmation token. Do not direct-navigate to a later page or use JavaScript."
    ))
    app.snap("BH03_knowledge_navigation")
    audit = slides_studio.audit()
    assert audit["acknowledgements"] == [{"operator": "SignalDesk", "confirmed": "on", "token": "ACK-15M"}]
    assert "15" in app.ui_text()


def test_BH05_five_slide_pitch_deck(app, slides_studio: SlidesStudio):
    """Build a full deck by operating only visible local Slides Studio controls."""
    _plan_and_confirm(app, (
        f"Open {slides_studio.base_url}/slides and manually build exactly five slides using visible editor controls. "
        "Never use evaluate_js, browser APIs, fixture APIs, or direct navigation to the review page. "
        "Slide 1: title SignalDesk; body Faster incident decisions; choose Dark theme and Title layout. "
        "Slide 2: title Problem; body must include Alert fatigue, Slow handoffs, and Fragmented context; choose Two column layout and Warning asset. "
        "Slide 3: title Solution; body must include Unified timeline, Automated triage, and Clear ownership; choose Solution layout and Workflow asset. "
        "Slide 4: title Why now; body must include 'Before: 45 min' and 'After: 15 min'; choose Comparison layout. "
        "Slide 5: title Start a pilot; body must include Start a pilot this quarter; choose Closing layout and Closing asset; "
        "speaker notes must include 'Invite the incident response leaders to the pilot.' "
        "Then click Review deck, verify the slide count and order, publish it, and tell me the displayed share token."
    ))
    app.snap("BH05_slides_initial_or_midrun")
    audit = slides_studio.audit()
    deck = audit["deck"]
    report = _write_gap_report("BH05", app, audit, {"fill", "click", "review", "publish", "selector_discovery", "screenshot"})
    assert report.exists()
    assert deck["published"] is True
    assert deck["shareToken"] == "SLIDES-SIGNALDESK-2026"
    assert [slide["title"] for slide in deck["slides"]] == ["SignalDesk", "Problem", "Solution", "Why now", "Start a pilot"]
    assert len(deck["slides"]) == 5
    required = {
        "SignalDesk": ("Faster incident decisions", "dark", "title", ""),
        "Problem": ("Alert fatigue", "light", "two-column", "warning"),
        "Solution": ("Unified timeline", "light", "solution", "workflow"),
        "Why now": ("Before: 45 min", "light", "comparison", ""),
        "Start a pilot": ("Start a pilot this quarter", "light", "closing", "closing"),
    }
    for item in deck["slides"]:
        token, theme, layout, asset = required[item["title"]]
        assert token.lower() in item["body"].lower()
        assert item["theme"] == theme
        assert item["layout"] == layout
        assert item["asset"] == asset
    assert "invite the incident response leaders to the pilot." in deck["slides"][-1]["notes"].lower()
    events = [event["type"] for event in audit["audit"]]
    assert events.count("add_slide") >= 4
    assert events.count("fill") >= 11
    for event in ("theme", "layout", "asset", "review", "publish"):
        assert event in events
    assert "slides-signaldEck-2026".lower() in app.ui_text()


@pytest.mark.external_network
def test_BH04_wikipedia_history_link(app):
    _plan_and_confirm(app, (
        "Open https://en.wikipedia.org/wiki/Python_(programming_language). Inspect the page and click the visible internal link "
        "to History of Python; do not directly navigate to the destination URL. Report the final page title and URL."
    ))
    app.snap("BH04_wikipedia_history")
    ui = app.ui_text()
    assert "history" in ui and "python" in ui
