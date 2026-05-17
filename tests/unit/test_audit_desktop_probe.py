from trinity_pilot.audit.desktop_probe import verify_visible_text


def test_visible_text_probe_pass():
    result = verify_visible_text("hello audit", uia_text="window says hello audit")

    assert result.passed is True
    assert result.visible_text_match is True
    assert result.file_only_delivery is False


def test_file_only_artifact_fails(tmp_path):
    output = tmp_path / "typed.txt"
    output.write_text("hello audit", encoding="utf-8")

    result = verify_visible_text("hello audit", file_paths=[output], observed_actions=["write_file"])

    assert result.passed is False
    assert result.file_only_delivery is True
    assert "insufficient" in result.reason


def test_missing_ui_evidence_fails():
    result = verify_visible_text("hello audit")

    assert result.passed is False
    assert result.evidence_source == "none"
