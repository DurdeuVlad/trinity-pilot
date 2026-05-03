"""Excel domain MCP server."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from trinity_core.runtime_mcp.base import TrinityMCPServer


class ExcelMCPServer(TrinityMCPServer):

    @property
    def domain(self) -> str:
        return "excel"

    @property
    def server_name(self) -> str:
        return "trinity-excel-toolset"

    @property
    def display_name(self) -> str:
        return "Trinity Excel Toolset"

    def instructions(self) -> str:
        return """\
Trinity Excel Toolset -- openpyxl-based .xlsx file automation.

CAPABILITIES: Read/write cells, manage sheets, apply formatting,
create charts, iterate rows/columns, save workbooks.

CONSTRAINTS:
- .xlsx format only (no .xls or .csv direct support)
- 1-based cell references (row=1, col=1 for cell A1)
- Explicit sheet names required; no implicit active sheet assumption
- File must be saved after batch writes -- unsaved changes are lost

GUIDANCE:
- Read cells or sheet names before writing to confirm file structure
- Batch writes before saving to minimise file I/O
- Use explicit sheet names, not sheet indices
- Verify cell values after writes to confirm correctness

FORBIDDEN:
- Do not write to cells without first reading the current structure
- Do not assume an active/default sheet exists -- always name it explicitly
- Do not skip saving after writes
"""

    def tool_guides(self) -> dict[str, str]:
        return {
            "general": "Read workbook structure first, then write and save.",
            "inspect": "Use read_cell, list_sheets, get_sheet_dimensions -- read-only.",
            "mutate": "Write cells in batch, then call save_workbook once.",
            "verify": "Re-read cells after save to confirm written values.",
            "recover": "Re-read the file; check sheet name and cell reference casing.",
        }

    def recovery_guides(self) -> dict[str, str]:
        return {
            "default": "Re-read file structure, verify sheet name and cell ref, retry.",
            "FILE_NOT_FOUND": "Workbook path does not exist. Verify path before opening.",
            "SHEET_NOT_FOUND": "Sheet name does not exist. Call list_sheets to see available sheets.",
            "CELL_REF_INVALID": "Cell reference out of range. Confirm row/col are 1-based integers.",
        }

    def forbidden_patterns(self) -> str:
        return """\
- Do not write to a file without first reading its current structure
- Do not use sheet indices -- always use explicit sheet names
- Do not skip save_workbook after writes
- Do not use .xls format; only .xlsx is supported
"""

    def constraint_summaries(self) -> list[str]:
        return [
            "openpyxl; .xlsx only",
            "1-based cell references",
            "Explicit sheet names required",
            "Must save after writes",
        ]

    def example_tasks(self) -> list[str]:
        return [
            "Read the value of cell B2 from Sheet1",
            "Write a list of values to column A starting at row 1",
            "List all sheet names in a workbook",
            "Save the workbook after batch updates",
        ]

    def domain_metadata(self) -> dict[str, Any]:
        return {
            "serial_execution": False,
            "parallel_safe": True,
            "underlying_tech": "openpyxl",
        }

    def register_tools(self, mcp: FastMCP) -> None:
        try:
            from trinity_core.tools.excel_tools import build_excel_tools
            trinity_tools = build_excel_tools()
        except ImportError:
            trinity_tools = {}
        self._register_trinity_tools(mcp, trinity_tools)
