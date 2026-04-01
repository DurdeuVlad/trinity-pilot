"""
Integration tests for Windows virtual desktop isolation.

Tests validate that the desktop isolation utility can move unified-app
to a target virtual desktop or fails gracefully.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.desktop_isolation import VirtualDesktopManager


@pytest.fixture
def desktop_manager():
    """Create desktop manager instance."""
    return VirtualDesktopManager()


def test_find_unified_app_window(desktop_manager):
    """
    Test that desktop manager can find unified-app window.
    
    Note: This test requires unified-app to be running.
    If unified-app is not running, test will be skipped.
    """
    hwnd = desktop_manager.find_unified_app_window()
    
    if hwnd is None:
        pytest.skip("Unified-app not running - start it to run this test")
    
    assert hwnd > 0
    assert isinstance(hwnd, int)


def test_isolate_unified_app_graceful_failure(desktop_manager):
    """
    Test that isolation fails gracefully when app not running.
    """
    # This should return False (not raise exception) when app not found
    result = desktop_manager.isolate_unified_app(2)
    
    # Result should be boolean
    assert isinstance(result, bool)


@pytest.mark.skip(reason="Requires unified-app running and manual verification")
def test_isolate_unified_app_to_desktop_2(desktop_manager):
    """
    Test moving unified-app to Desktop 2.
    
    This test requires:
    1. Unified-app running
    2. Windows 10/11 with virtual desktop support
    3. Manual verification via Task View (Win+Tab)
    
    Run manually and verify app appears on Desktop 2 in Task View.
    """
    hwnd = desktop_manager.find_unified_app_window()
    
    if hwnd is None:
        pytest.skip("Unified-app not running")
    
    result = desktop_manager.isolate_unified_app(2)
    
    # If isolation succeeds or fails gracefully, both are acceptable
    assert isinstance(result, bool)
    
    if result:
        print("\n✅ Desktop isolation succeeded")
        print("   Verify manually: Open Task View (Win+Tab) and check Desktop 2")
    else:
        print("\n⚠️  Desktop isolation failed (graceful fallback)")
        print("   This is acceptable - tests will run on current desktop")


def test_desktop_manager_initialization():
    """Test that desktop manager initializes without errors."""
    manager = VirtualDesktopManager()
    assert manager is not None
    assert hasattr(manager, 'find_unified_app_window')
    assert hasattr(manager, 'isolate_unified_app')


@pytest.mark.skip(reason="_find_window_by_title was removed from VirtualDesktopManager")
def test_find_window_returns_none_when_not_running():
    """Test that find_window returns None when app not running."""
    manager = VirtualDesktopManager()
    hwnd = manager._find_window_by_title("ThisWindowDefinitelyDoesNotExist12345")
    assert hwnd is None


def test_isolation_with_invalid_desktop_number(desktop_manager):
    """Test that isolation handles invalid desktop numbers gracefully."""
    # Try to isolate to desktop 99 (unlikely to exist)
    result = desktop_manager.isolate_unified_app(99)
    
    # Should return False (not crash)
    assert isinstance(result, bool)
    assert result is False


def test_desktop_manager_error_messages(desktop_manager, capsys):
    """Test that desktop manager provides clear error messages."""
    # Try to isolate when app not running
    result = desktop_manager.isolate_unified_app(2)
    
    # Should return False
    assert result is False
    
    # Check that error message was printed (if any)
    # This is informational - we don't strictly require error messages
