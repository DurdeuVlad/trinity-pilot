"""VM Bridge MCP Server — VirtualBox control for automated VM setup.

Exposes tools to drive a VirtualBox VM from an AI agent:
- Screenshot via VBoxManage or .NET CopyFromScreen (multi-monitor safe)
- Keyboard injection at hardware level (bypasses OS focus)
- VM state inspection and control
- Window capture by title (any monitor)

Run: python -m trinity_pilot.mcp.vm_bridge_server
"""
from __future__ import annotations

import base64
import asyncio
import io
import os
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

mcp = FastMCP(
    name="vm-bridge",
    version="0.1.0",
)

VBOXMANAGE = os.environ.get(
    "VBOXMANAGE_PATH",
    r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _vbox(*args: str, timeout: int = 30) -> dict:
    """Run VBoxManage with args. Returns {ok, stdout, stderr, returncode}."""
    try:
        r = subprocess.run(
            [VBOXMANAGE, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": r.returncode == 0,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "returncode": r.returncode,
        }
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": f"VBoxManage not found at {VBOXMANAGE}", "returncode": -1}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "Timed out", "returncode": -1}


def _capture_region(x: int, y: int, width: int, height: int) -> bytes:
    """Capture a screen region using PIL ImageGrab (supports all monitors)."""
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# VM state tools
# ---------------------------------------------------------------------------

@mcp.tool()
def vm_info(vm_name: str) -> dict:
    """Get VM state and key properties.

    Args:
        vm_name: Name of the VirtualBox VM.

    Returns:
        dict with state, vrde_port, vdi_mtime, and raw machinereadable lines.
    """
    r = _vbox("showvminfo", vm_name, "--machinereadable")
    if not r["ok"]:
        return {"ok": False, "error": r["stderr"]}

    props: dict[str, str] = {}
    for line in r["stdout"].splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip().strip('"')

    result: dict[str, Any] = {
        "ok": True,
        "state": props.get("VMState", "unknown"),
        "vrde_port": props.get("vrdeport", "unknown"),
        "vrde_enabled": props.get("vrde", "disabled"),
        "video_adapter": props.get("graphicscontroller", "unknown"),
        "raw": props,
    }

    # Check VDI last write time
    try:        # Find VDI via disk path in props
        for k, v in props.items():
            if v.endswith(".vdi") and Path(v).exists():
                result["vdi_mtime"] = Path(v).stat().st_mtime
                result["vdi_path"] = v
                break
    except Exception:
        pass

    return result


@mcp.tool()
def vm_controlvm(vm_name: str, command: str, args: list[str] | None = None) -> dict:
    """Run a VBoxManage controlvm command.

    Args:
        vm_name: Name of the VirtualBox VM.
        command: controlvm subcommand, e.g. "pause", "resume", "poweroff", "vrde".
        args: Additional arguments for the command.

    Returns:
        dict with ok, stdout, stderr.

    Examples:
        vm_controlvm("TrinityPilot-Test", "resume")
        vm_controlvm("TrinityPilot-Test", "vrde", ["on"])
        vm_controlvm("TrinityPilot-Test", "pause")
    """
    cmd_args = ["controlvm", vm_name, command] + (args or [])
    return _vbox(*cmd_args)


@mcp.tool()
def vm_snapshot(vm_name: str, snapshot_name: str, description: str = "") -> dict:
    """Take a VM snapshot.

    Args:
        vm_name: Name of the VirtualBox VM.
        snapshot_name: Name for the new snapshot.
        description: Optional description.

    Returns:
        dict with ok, stdout, stderr.
    """
    args = ["snapshot", vm_name, "take", snapshot_name]
    if description:
        args += ["--description", description]
    return _vbox(*args, timeout=120)


@mcp.tool()
def vm_list() -> dict:
    """List registered VirtualBox VMs; an empty list is valid."""
    result = _vbox("list", "vms")
    if not result["ok"]:
        return {"ok": False, "vms": [], "error": result["stderr"]}
    vms = []
    for line in result["stdout"].splitlines():
        if '"' in line:
            name = line.split('"')[1]
            vms.append({"name": name, "raw": line})
    return {"ok": True, "vms": vms}


@mcp.tool()
def vm_startvm(vm_name: str, type: str = "headless") -> dict:
    return _vbox("startvm", vm_name, "--type", type, timeout=120)


@mcp.tool()
def vm_restore_snapshot(vm_name: str, snapshot_name: str) -> dict:
    return _vbox("snapshot", vm_name, "restore", snapshot_name, timeout=120)


@mcp.tool()
def vm_list_snapshots(vm_name: str) -> dict:
    result = _vbox("snapshot", vm_name, "list", "--machinereadable")
    if not result["ok"]:
        return {"ok": False, "snapshots": [], "error": result["stderr"]}
    snapshots = [line.split('=', 1)[1].strip('"') for line in result["stdout"].splitlines() if line.startswith("SnapshotName")]
    return {"ok": True, "snapshots": snapshots}


@mcp.tool()
def vm_delete_snapshot(vm_name: str, snapshot_name: str) -> dict:
    return _vbox("snapshot", vm_name, "delete", snapshot_name, timeout=120)


# ---------------------------------------------------------------------------
# Keyboard injection tools
# ---------------------------------------------------------------------------

@mcp.tool()
def vm_type(vm_name: str, text: str) -> dict:
    """Type text into a running VM at hardware level (bypasses OS focus).

    Uses VBoxManage keyboardputstring. Safe to use even when the VM window
    is not focused on the host.

    Args:
        vm_name: Name of the VirtualBox VM.
        text: Text to type.

    Returns:
        dict with ok, stdout, stderr.
    """
    return _vbox("controlvm", vm_name, "keyboardputstring", text)


@mcp.tool()
def vm_key(vm_name: str, scancodes: list[str]) -> dict:
    """Inject raw keyboard scancodes into a running VM at hardware level.

    Use this for special keys that keyboardputstring cannot send (Enter, Ctrl+Alt+Del, etc.).

    Args:
        vm_name: Name of the VirtualBox VM.
        scancodes: List of hex scancode bytes, e.g. ["1c", "9c"] for Enter press+release.

    Common scancodes:
        Enter:       ["1c", "9c"]
        Escape:      ["01", "81"]
        Up arrow:    ["e0", "48", "e0", "c8"]
        Down arrow:  ["e0", "50", "e0", "d0"]
        Tab:         ["0f", "8f"]
        Ctrl+Alt+Del: ["1d", "38", "e0", "53", "e0", "d3", "b8", "9d"]
        Space:       ["39", "b9"]

    Returns:
        dict with ok, stdout, stderr.
    """
    return _vbox("controlvm", vm_name, "keyboardputscancode", *scancodes)


@mcp.tool()
async def vm_unlock(vm_name: str, password: str) -> dict:
    """Attempt to unlock a Windows VM from the lock screen.

    Sends: Up arrow (wake lock screen) → waits → types password → Enter.
    Works even when VM display appears black over VRDE/VBoxManage screenshotpng.

    Args:
        vm_name: Name of the VirtualBox VM.
        password: Windows user password to type.

    Returns:
        dict with steps describing what was sent.
    """
    steps = []

    # Wake lock screen with Up arrow (swipe up gesture equivalent)
    r = _vbox("controlvm", vm_name, "keyboardputscancode", "e0", "48", "e0", "c8")
    steps.append({"action": "up_arrow", "ok": r["ok"]})
    await asyncio.sleep(2)

    # Type password
    r = _vbox("controlvm", vm_name, "keyboardputstring", password)
    steps.append({"action": "type_password", "ok": r["ok"]})
    await asyncio.sleep(0.5)

    # Press Enter
    r = _vbox("controlvm", vm_name, "keyboardputscancode", "1c", "9c")
    steps.append({"action": "enter", "ok": r["ok"]})

    return {"ok": all(s["ok"] for s in steps), "steps": steps}


@mcp.tool()
def vm_send_ctrl_alt_del(vm_name: str) -> dict:
    """Send Ctrl+Alt+Del to a running VM at hardware level.

    Useful for waking the Windows login screen or triggering the security screen.

    Args:
        vm_name: Name of the VirtualBox VM.

    Returns:
        dict with ok, stdout, stderr.
    """
    return _vbox(
        "controlvm", vm_name, "keyboardputscancode",
        "1d", "38", "e0", "53", "e0", "d3", "b8", "9d",
    )


# ---------------------------------------------------------------------------
# Screenshot tools
# ---------------------------------------------------------------------------

@mcp.tool()
def vm_screenshot_vbox(vm_name: str) -> dict:
    """Take a VM screenshot via VBoxManage screenshotpng.

    Note: This returns a black image for VMs using VMSVGA without Guest Additions
    or when the lock screen is shown. Use vm_screenshot_window() instead in those cases.

    Args:
        vm_name: Name of the VirtualBox VM.

    Returns:
        dict with ok, image_b64 (PNG base64), width, height, or error.
    """
    import tempfile
    tmp = Path(tempfile.gettempdir()) / f"vbox_{vm_name}_screenshot.png"
    r = _vbox("controlvm", vm_name, "screenshotpng", str(tmp))
    if not r["ok"]:
        return {"ok": False, "error": r["stderr"]}
    if not tmp.exists():
        return {"ok": False, "error": "Screenshot file not created"}

    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    return {
        "ok": True,
        "image_b64": base64.b64encode(data).decode(),
        "note": "May be black if VMSVGA without Guest Additions or at lock screen",
    }


@mcp.tool()
def screenshot_window(title_contains: str) -> dict:
    """Capture the screen region occupied by a window matching the title.

    Works across all monitors including secondary monitors with negative X coords.
    If the window is behind other windows, it will still capture that screen region
    (the topmost content at those coordinates).

    Args:
        title_contains: Substring to match against window titles (case-insensitive).

    Returns:
        dict with ok, image_b64, width, height, x, y, window_title.
    """
    try:
        import win32gui

        found = []

        def _enum(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if title_contains.lower() in t.lower():
                    rect = win32gui.GetWindowRect(hwnd)
                    found.append((hwnd, t, rect))

        win32gui.EnumWindows(_enum, None)

        if not found:
            return {"ok": False, "error": f"No window matching '{title_contains}'"}

        hwnd, title, rect = found[0]
        x, y, x2, y2 = rect
        w, h = x2 - x, y2 - y

        if w <= 0 or h <= 0:
            return {"ok": False, "error": f"Window '{title}' has zero size (minimized?)"}

        data = _capture_region(x, y, w, h)
        return {
            "ok": True,
            "image_b64": base64.b64encode(data).decode(),
            "width": w,
            "height": h,
            "x": x,
            "y": y,
            "window_title": title,
        }
    except ImportError:
        return {"ok": False, "error": "win32gui not available — pip install pywin32"}


@mcp.tool()
def screenshot_region(x: int, y: int, width: int, height: int) -> dict:
    """Capture a screen region using virtual desktop coordinates.

    Works across all monitors. Supports negative X (left monitors) and
    X values beyond the primary monitor width (right monitors).

    Args:
        x: Left edge in virtual desktop coords (can be negative).
        y: Top edge in virtual desktop coords.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        dict with ok, image_b64, width, height.
    """
    try:
        data = _capture_region(x, y, width, height)
        return {
            "ok": True,
            "image_b64": base64.b64encode(data).decode(),
            "width": width,
            "height": height,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Network check
# ---------------------------------------------------------------------------

@mcp.tool()
def ping_vm(ip: str, count: int = 3) -> dict:
    """Ping a VM IP address to check if it's network-reachable.

    Args:
        ip: IP address to ping.
        count: Number of ping packets.

    Returns:
        dict with ok (True if at least 1 reply), packets_sent, packets_received.
    """
    r = subprocess.run(
        ["ping", "-n", str(count), ip],
        capture_output=True, text=True, timeout=15,
    )
    received = 0
    for line in r.stdout.splitlines():
        if "Received = " in line:
            try:
                received = int(line.split("Received = ")[1].split(",")[0])
            except Exception:
                pass
    return {
        "ok": received > 0,
        "packets_sent": count,
        "packets_received": received,
        "stdout": r.stdout.strip(),
    }


if __name__ == "__main__":
    mcp.run()
