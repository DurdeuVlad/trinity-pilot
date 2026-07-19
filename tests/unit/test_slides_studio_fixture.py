"""Contract tests for the Node-backed deterministic browser fixture."""
from __future__ import annotations

import json
import urllib.request

import pytest

from tests.helpers.slides_studio import start_slides_studio


def _post(base_url: str, path: str, value: dict) -> dict:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(value).encode("utf-8"),
        method="POST",
        headers={"content-type": "application/json", "x-slides-studio-ui": "1"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_slides_studio_tracks_visible_editor_state():
    try:
        fixture = start_slides_studio()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    try:
        _post(fixture.base_url, "/api/event", {"type": "fill", "id": "slide-1", "field": "title", "value": "SignalDesk"})
        _post(fixture.base_url, "/api/event", {"type": "theme", "id": "slide-1", "value": "dark"})
        second = _post(fixture.base_url, "/api/event", {"type": "add_slide"})
        _post(fixture.base_url, "/api/event", {"type": "fill", "id": second["id"], "field": "title", "value": "Problem"})
        _post(fixture.base_url, "/api/event", {"type": "review"})
        published = _post(fixture.base_url, "/api/event", {"type": "publish"})
        audit = fixture.audit()
        assert [item["title"] for item in audit["deck"]["slides"]] == ["SignalDesk", "Problem"]
        assert audit["deck"]["slides"][0]["theme"] == "dark"
        assert audit["deck"]["published"] is True
        assert published["shareToken"] == "SLIDES-SIGNALDESK-2026"
        assert [item["type"] for item in audit["audit"]][-2:] == ["review", "publish"]
    finally:
        fixture.close()
