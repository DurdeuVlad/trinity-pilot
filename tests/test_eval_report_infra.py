from __future__ import annotations

from eval_report import section_infra_diagnostics


def test_section_infra_diagnostics_mixed_checkpoints() -> None:
    multirun = {
        "T1": {
            "n_runs": 2,
            "runs": [
                {
                    "run": 1,
                    "checkpoints": {
                        "vm_boot_ok": True,
                        "code_sync_ok": True,
                        "guest_preflight_ok": True,
                        "app_launched": True,
                        "window_connected": True,
                        "prompt_submitted": True,
                        "execution_started": True,
                        "app_crashed": True,
                        "graceful_close": True,
                    },
                },
                {
                    "run": 2,
                    "checkpoints": {
                        "vm_boot_ok": True,
                        "code_sync_ok": False,
                        "guest_preflight_ok": True,
                        "app_launched": True,
                        "window_connected": False,
                        "prompt_submitted": False,
                        "execution_started": False,
                        "app_crashed": False,
                        "graceful_close": False,
                    },
                },
            ],
        }
    }

    section = section_infra_diagnostics(multirun)

    assert "## Infrastructure Pipeline Diagnostics" in section
    assert "T1 (Run 1)" in section
    assert "T1 (Run 2)" in section
    assert section.count("✅") >= 9
    assert section.count("❌") >= 5
    assert "Code Sync" in section
    assert "No App Crash" in section
