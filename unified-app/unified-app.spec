# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

block_cipher = None

app_root = Path(SPECPATH).resolve()
project_root = app_root.parent
cli_root = project_root / "cli-automation-poc"
browser_root = project_root / "browser-gui-automation"
desktop_root = project_root / "api-accessibility-poc"
audit_root = project_root / "audit-debugger" / "src"

for import_path in (app_root, project_root, cli_root, browser_root, desktop_root, audit_root):
    text = str(import_path)
    if text not in sys.path:
        sys.path.insert(0, text)

dist_name = os.environ.get("UNIFIED_APP_DIST_NAME", "UnifiedApp-0.0.0-dev")

cli_hiddenimports = [
    "cli_backend",
    "cli_executor",
    "cli_io_models",
    "cli_logger",
    "cli_planner",
    "cli_retry_handler",
    "cli_validator",
    "smart_orchestrator",
]

desktop_hiddenimports = [
    "desktop_io_models",
    "gdi_highlight",
    "generic_backend",
    "generic_executor",
    "generic_planner",
    "generic_reader",
    "generic_smart_orchestrator",
    "ui_utils",
]

browser_datas, browser_binaries, browser_hiddenimports = collect_all("browser_agent")
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
pywinauto_datas, pywinauto_binaries, pywinauto_hiddenimports = collect_all("pywinauto")
comtypes_datas, comtypes_binaries, comtypes_hiddenimports = collect_all("comtypes")
audit_datas, audit_binaries, audit_hiddenimports = collect_all("audit_debugger")

datas = [
    (str(app_root / "docs"), "docs"),
]
datas += browser_datas
datas += playwright_datas
datas += pywinauto_datas
datas += comtypes_datas
datas += audit_datas
datas += copy_metadata("google-generativeai")
datas += copy_metadata("PyQt6")
datas += copy_metadata("playwright")
datas += copy_metadata("pywinauto")
datas += copy_metadata("python-dotenv")
datas += copy_metadata("sqlalchemy")

binaries = []
binaries += browser_binaries
binaries += playwright_binaries
binaries += pywinauto_binaries
binaries += comtypes_binaries
binaries += audit_binaries

hiddenimports = sorted(
    set(
        collect_submodules("orchestrator")
        + collect_submodules("ui")
        + collect_submodules("trinity_core")
        + cli_hiddenimports
        + desktop_hiddenimports
        + browser_hiddenimports
        + playwright_hiddenimports
        + pywinauto_hiddenimports
        + comtypes_hiddenimports
        + audit_hiddenimports
    )
)

a = Analysis(
    [str(app_root / "main.py")],
    pathex=[
        str(app_root),
        str(project_root),
        str(cli_root),
        str(browser_root),
        str(desktop_root),
        str(audit_root),
    ],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["testing", "testing.gemini_mock"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OrchestratorDesktopApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=dist_name,
)
