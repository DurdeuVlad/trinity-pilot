"""CLI domain MCP server."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from trinity_core.runtime_mcp.base import TrinityMCPServer
from trinity_core.tools.cli_tools import build_cli_tools


class CLIMCPServer(TrinityMCPServer):

    @property
    def domain(self) -> str:
        return "cli"

    @property
    def server_name(self) -> str:
        return "trinity-cli-toolset"

    @property
    def display_name(self) -> str:
        return "Trinity CLI Toolset"

    def instructions(self) -> str:
        from trinity_core.runtime_mcp.domains._cli_reference import CLI_REFERENCE
        return f"""\
Trinity CLI Toolset -- Windows subprocess execution.

CAPABILITIES: Run shell commands (PowerShell, cmd, executables), write text files,
read files, list directories, inspect process state, execute scripts.

CONSTRAINTS:
- Serial execution; each command is independent (no persistent shell state)
- Windows subprocess model; PATH and env inherited from parent process
- Commands run with the same privileges as the Trinity process

GUIDANCE:
- Prefer read-only commands first when filesystem or process state is unknown
- Use write_text_file for multiline file creation instead of hand-rolled PowerShell
- Use wait tools instead of polling manually in repeated command calls
- Quote paths containing spaces; use absolute paths when possible
- Prefer idempotent commands; avoid destructive operations unless required

FORBIDDEN:
- Do not use interactive stdin commands (they will hang)
- Do not use CLI tools to recover browser or desktop objectives
- Do not blindly repeat a failed command without inspecting state first

{CLI_REFERENCE}
"""

    def tool_guides(self) -> dict[str, str]:
        return {
            "general": "Start with a read-only command to inspect state before mutating.",
            "inspect": "Use dir, type, Get-Content, Get-ChildItem to read without side effects.",
            "mutate": "Use write_text_file for text files, Move-Item for moves, and verify with a follow-up read.",
            "wait": "Use timeout or sleep sparingly; prefer polling with condition checks.",
            "verify": "Re-run the read command after mutation to confirm state change.",
            "recover": "Inspect error output, change command or params, retry once.",
        }

    def recovery_guides(self) -> dict[str, str]:
        return {
            "default": "Read error output, adjust command or params, retry once.",
            "COMMAND_FAILED": "Inspect stderr, check command spelling and args, retry with fix.",
            "CLI_COMMAND_FAILED": "If a file write failed or raw text was rejected as a command, retry with write_text_file.",
            "TIMEOUT": "Command timed out. Check if process hung; consider background execution.",
            "PERMISSION_DENIED": "Insufficient privileges. Check path, user context, or use elevated shell.",
            "FILE_NOT_FOUND": "Path does not exist. Verify with dir/Get-ChildItem before retrying.",
        }

    def forbidden_patterns(self) -> str:
        return """\
- Do not run interactive commands that require stdin input (they will hang indefinitely)
- Do not use CLI tools to simulate browser or desktop actions
- Do not blindly repeat the same failing command without diagnosis
- Do not use destructive commands (rm, del, format) unless the objective explicitly requires them
"""

    def constraint_summaries(self) -> list[str]:
        return [
            "Windows subprocess; no persistent shell session",
            "Serial execution -- one command at a time",
            "No interactive stdin support",
            "PATH and env inherited from Trinity process",
        ]

    def example_tasks(self) -> list[str]:
        return [
            "List files in a directory",
            "Read the contents of a configuration file",
            "Run a Python script and capture its output",
            "Create a text manifest or report file",
            "Check if a process is running",
        ]

    def domain_metadata(self) -> dict[str, Any]:
        return {
            "serial_execution": True,
            "parallel_safe": False,
            "underlying_tech": "subprocess / PowerShell",
        }

    def register_tools(self, mcp: FastMCP) -> None:
        self._register_trinity_tools(mcp, build_cli_tools())
