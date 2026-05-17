from trinity_pilot.audit.preflight import run_active_path_preflight


def test_active_scan_lists_scanned_paths(tmp_path):
    (tmp_path / "trinity_pilot").mkdir()
    (tmp_path / "trinity_pilot" / "app.py").write_text("print('ok')\n", encoding="utf-8")

    result = run_active_path_preflight(tmp_path, active_roots=["trinity_pilot"], historical_roots=[])

    assert result.passed is True
    assert result.scanned_paths == ["trinity_pilot/app.py"]


def test_active_banned_token_fails(tmp_path):
    (tmp_path / "trinity_pilot").mkdir()
    token = "Task" + "Workflow"
    (tmp_path / "trinity_pilot" / "app.py").write_text(f"{token}\n", encoding="utf-8")

    result = run_active_path_preflight(tmp_path, active_roots=["trinity_pilot"], historical_roots=[])

    assert result.passed is False
    assert result.findings[0].token == token
    assert result.findings[0].line == 1


def test_historical_finding_is_non_blocking(tmp_path):
    (tmp_path / "docs").mkdir()
    token = "temporal" + "io"
    (tmp_path / "docs" / "old.md").write_text(f"old {token} note\n", encoding="utf-8")

    result = run_active_path_preflight(tmp_path, active_roots=[], historical_roots=["docs"])

    assert result.passed is True
    assert result.historical_findings[0].classification == "historical"


def test_preflight_json_serialization(tmp_path):
    (tmp_path / "setup.sh").write_text("echo ok\n", encoding="utf-8")

    data = run_active_path_preflight(tmp_path, active_roots=["setup.sh"], historical_roots=[]).to_dict()

    assert data["passed"] is True
    assert data["finding_count"] == 0
