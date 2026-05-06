from pathlib import Path

import pytest

from mcp_server.live_test_cases import LiveTestCaseLibrary


def test_resolve_case_by_id_uses_canonical_docs() -> None:
    library = LiveTestCaseLibrary()

    case = library.resolve_case("TC-BROWSER-01")

    assert case.id == "TC-BROWSER-01"
    assert case.domain == "browser"
    assert case.path.endswith("trinity-pilot\\docs\\live-test-cases\\browser\\TC-BROWSER-01.md")
    assert "microsoft/vscode" in case.user_prompt
    assert "flight_report_present" in case.artifact_checks


def test_case_execution_domain_mapping() -> None:
    assert LiveTestCaseLibrary.to_execution_domain("browser") == "web"
    assert LiveTestCaseLibrary.to_execution_domain("cross") == "mixed"
    assert LiveTestCaseLibrary.to_execution_domain("cli") == "cli"


def test_case_library_rejects_non_canonical_paths(tmp_path: Path) -> None:
    rogue_case = tmp_path / "TC-ROGUE-01.md"
    rogue_case.write_text(
        "---\n"
        "id: TC-ROGUE-01\n"
        "title: Rogue\n"
        "domain: cli\n"
        "difficulty: easy\n"
        "goal: test\n"
        "user_prompt: test\n"
        "expected_outcome:\n"
        "  - done\n"
        "observation_policy:\n"
        "  mode: live\n"
        "stop_policy:\n"
        "mode: bounded_drift\n"
        "danger_flags:\n"
        "  - none\n"
        "artifact_checks:\n"
        "  - report\n"
        "postmortem_questions:\n"
        "  - why\n"
        "platform: windows\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical library"):
        LiveTestCaseLibrary().resolve_case(str(rogue_case))
