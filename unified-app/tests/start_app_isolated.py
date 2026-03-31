"""Start unified-app isolated to Desktop 2."""
import subprocess
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from desktop_isolation import VirtualDesktopManager


def main():
    """Start unified-app and isolate to Desktop 2."""
    print("Starting unified-app...")
    
    # Start unified-app
    proc = subprocess.Popen(
        [sys.executable, "unified-app/main.py"],
        cwd=str(Path(__file__).parent.parent.parent),
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    
    print(f"Process started with PID: {proc.pid}")
    print("Waiting for app to initialize...")
    time.sleep(8)
    
    # Isolate to Desktop 2
    print("\nIsolating to Desktop 2...")
    manager = VirtualDesktopManager()
    
    try:
        success = manager.isolate_window_to_desktop(
            window_title="Orchestrator Desktop App",
            target_desktop=2
        )
        
        if success:
            print("✅ App isolated to Desktop 2")
            print("\nUnified-app is running on Desktop 2")
            print("You can now run HP tests from Desktop 1")
            return 0
        else:
            print("⚠️ Could not isolate to Desktop 2 (app will run on current desktop)")
            print("   This is OK - tests will still work")
            return 0
            
    except Exception as e:
        print(f"⚠️ Desktop isolation error: {e}")
        print("   App is running but not isolated")
        return 0


if __name__ == "__main__":
    exit(main())
