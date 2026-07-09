"""Unit tests for MCP tool metadata manifests and filtering."""
from __future__ import annotations

from trinity_pilot.mcp import browser_server
from trinity_pilot.mcp import desktop_automation_server
from trinity_pilot.mcp import desktop_server
from trinity_pilot.mcp import sensor_server
from trinity_pilot.mcp import terminal_server
from trinity_pilot.mcp.tool_registry import VALID_TOOL_KINDS, sensor_only_tools, validate_manifest

MANIFESTS = (
    browser_server.TOOL_MANIFEST,
    desktop_server.TOOL_MANIFEST,
    terminal_server.TOOL_MANIFEST,
    desktop_automation_server.TOOL_MANIFEST,
    sensor_server.TOOL_MANIFEST,
)

EXPECTED_TOOL_NAMES = {
    browser_server.SERVER_NAME: {
        "browser_navigate",
        "navigate",
        "click",
        "fill",
        "read_page",
        "dom_snapshot",
        "accessibility_tree",
        "current_url",
        "page_title",
        "get_cookies",
        "list_open_tabs",
        "network_log",
        "get_element_text",
        "get_element_attribute",
        "finish",
        "report_blocking",
    },
    desktop_server.SERVER_NAME: {
        "desktop_run",
        "uia_tree",
        "focused_element",
        "window_hierarchy",
        "get_element_value",
        "app_state",
        "launch_app",
        "focus_window",
        "type_text",
        "press_hotkey",
        "press_key",
        "write_file",
        "wait",
        "finish",
        "report_blocking",
    },
    terminal_server.SERVER_NAME: {
        "terminal_run",
        "read_stdout",
        "current_directory",
        "env_vars",
        "last_exit_code",
        "command_history",
        "list_created_files",
        "run_command",
        "write_file",
        "finish",
        "report_blocking",
    },
    desktop_automation_server.SERVER_NAME: {
        "click",
        "move_to",
        "type_text",
        "press_key",
        "focus_window",
        "sleep",
    },
    sensor_server.SERVER_NAME: {
        "screenshot",
        "find_window",
        "locate_on_screen",
        "window_list",
        "process_list",
        "clipboard_read",
        "file_stat",
    },
}


def test_all_manifest_entries_have_valid_kind_and_name():
    for manifest in MANIFESTS:
        validate_manifest(manifest)
        for tool in manifest:
            assert tool.name.strip()
            assert tool.server.strip()
            assert tool.kind in VALID_TOOL_KINDS


def test_manifests_cover_exposed_mcp_tools_by_explicit_name():
    for manifest in MANIFESTS:
        server = manifest[0].server
        assert {tool.name for tool in manifest} == EXPECTED_TOOL_NAMES[server]


def test_sensor_only_view_preserves_sensors_from_multiple_servers_only():
    view = sensor_only_tools(
        (
            browser_server.TOOL_MANIFEST,
            terminal_server.TOOL_MANIFEST,
            desktop_server.TOOL_MANIFEST,
        )
    )

    assert view
    assert {tool.kind for tool in view} == {"sensor"}
    assert {"trinity-pilot-browser", "trinity-pilot-terminal"} <= {tool.server for tool in view}
    assert "navigate" not in {tool.name for tool in view}
    assert "run_command" not in {tool.name for tool in view}
    assert "finish" not in {tool.name for tool in view}
    assert "terminal_run" not in {tool.name for tool in view}


def test_domain_specific_browser_sensor_stays_out_of_central_sensor_server():
    browser_sensor_names = {
        tool.name for tool in browser_server.TOOL_MANIFEST if tool.kind == "sensor"
    }
    central_sensor_names = {tool.name for tool in sensor_server.TOOL_MANIFEST}

    assert "dom_snapshot" in browser_sensor_names
    assert "dom_snapshot" not in central_sensor_names


def test_desktop_automation_server_exposes_no_sensor_tools():
    assert desktop_automation_server.TOOL_MANIFEST
    assert {
        tool.kind for tool in desktop_automation_server.TOOL_MANIFEST
    } == {"action"}
