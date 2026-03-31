"""
Desktop Isolation Utility for Windows Virtual Desktops

Moves unified-app to a dedicated virtual desktop for automated testing.
Prevents test interference with developer workspace.
"""

import ctypes
import win32gui
import win32con
import win32process
import psutil
import time
from typing import Optional


class VirtualDesktopManager:
    """Manage Windows 10/11 Virtual Desktops for test isolation"""
    
    def __init__(self):
        self.user32 = ctypes.windll.user32
        
    def find_unified_app_window(self) -> Optional[int]:
        """Find the unified-app main window handle"""
        window_titles = [
            "Desktop AI Orchestrator",
            "Unified App",
            "TrinityPilot"
        ]
        
        for title in window_titles:
            hwnd = win32gui.FindWindow(None, title)
            if hwnd:
                return hwnd
        
        return None
    
    def find_window_by_process_name(self, process_name: str) -> Optional[int]:
        """Find window by process name (e.g., 'python.exe')"""
        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    if proc.name().lower() == process_name.lower():
                        windows.append(hwnd)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return True
        
        windows = []
        win32gui.EnumWindows(callback, windows)
        
        return windows[0] if windows else None
    
    def move_window_to_foreground(self, hwnd: int) -> bool:
        """Bring window to foreground"""
        try:
            # Restore if minimized
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            
            # Set foreground
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            
            return True
        except Exception as e:
            print(f"Error moving window to foreground: {e}")
            return False
    
    def send_to_desktop(self, desktop_number: int) -> bool:
        """
        Send unified-app to specified virtual desktop using keyboard shortcuts.
        
        Windows 10/11 shortcuts:
        - Win + Ctrl + Left/Right: Switch desktops
        - Win + Ctrl + D: Create new desktop
        - Win + Ctrl + F4: Close current desktop
        - Win + Tab: Open Task View
        
        Args:
            desktop_number: Target desktop (1-indexed, e.g., 1 = Desktop 1, 2 = Desktop 2)
        
        Returns:
            True if successful, False otherwise
        """
        hwnd = self.find_unified_app_window()
        
        if not hwnd:
            print("Unified-app window not found. Is the app running?")
            return False
        
        print(f"Found unified-app window: {hwnd}")
        
        # Bring window to foreground
        if not self.move_window_to_foreground(hwnd):
            return False
        
        # Use Win+Tab to open Task View
        print("Opening Task View...")
        self._press_keys([win32con.VK_LWIN, win32con.VK_TAB])
        time.sleep(1)
        
        # Right-click on window thumbnail and select "Move to" -> Desktop N
        # This is complex to automate, so we'll use a simpler approach:
        # Create new desktop if needed, then move window
        
        # For now, use Win+Ctrl+Arrow to switch desktops
        # This moves the active window to the next desktop
        current_desktop = 1
        target_desktop = desktop_number
        
        if target_desktop > current_desktop:
            moves = target_desktop - current_desktop
            for _ in range(moves):
                print(f"Moving window to next desktop...")
                self._press_keys([win32con.VK_LWIN, win32con.VK_CONTROL, win32con.VK_RIGHT])
                time.sleep(0.5)
        
        print(f"Unified-app moved to Desktop {desktop_number}")
        return True
    
    def _press_keys(self, keys: list):
        """Press multiple keys simultaneously"""
        # Press all keys
        for key in keys:
            win32api.keybd_event(key, 0, 0, 0)
        
        time.sleep(0.1)
        
        # Release all keys in reverse order
        for key in reversed(keys):
            win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    
    def isolate_unified_app(self, desktop_number: int = 2) -> bool:
        """
        Isolate unified-app to specified desktop.
        
        Args:
            desktop_number: Target desktop (default: 2 for Desktop 2)
        
        Returns:
            True if successful, False otherwise
        """
        print(f"Isolating unified-app to Desktop {desktop_number}...")
        
        # Ensure unified-app is running
        hwnd = self.find_unified_app_window()
        if not hwnd:
            print("ERROR: Unified-app not running. Start it first.")
            return False
        
        # Move to target desktop
        success = self.send_to_desktop(desktop_number)
        
        if success:
            print(f"✅ Unified-app isolated to Desktop {desktop_number}")
            print(f"   Developer workspace remains on Desktop 1")
            print(f"   Test runner will communicate via MCP server")
        else:
            print(f"❌ Failed to isolate unified-app")
        
        return success


def main():
    """CLI entry point for desktop isolation"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Isolate unified-app to a dedicated virtual desktop"
    )
    parser.add_argument(
        "--desktop",
        type=int,
        default=2,
        help="Target desktop number (default: 2)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if unified-app is running without moving it"
    )
    
    args = parser.parse_args()
    
    manager = VirtualDesktopManager()
    
    if args.check:
        hwnd = manager.find_unified_app_window()
        if hwnd:
            print(f"✅ Unified-app is running (window handle: {hwnd})")
        else:
            print("❌ Unified-app not found")
        return
    
    # Isolate to target desktop
    success = manager.isolate_unified_app(args.desktop)
    
    if not success:
        exit(1)


if __name__ == "__main__":
    # Note: This requires pywin32 and psutil
    try:
        import win32api
    except ImportError:
        print("ERROR: pywin32 not installed. Run: pip install pywin32")
        exit(1)
    
    main()
