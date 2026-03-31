"""Chaos Injector - Environmental stress injection for battle testing.

Supports four fault modes:
- network: Disable/re-enable network adapter (requires Administrator)
- cpu: Launch stress subprocess consuming 90%+ CPU
- kill: Terminate approved processes
- disk: Fill disk to specified capacity
"""
import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

import psutil

_RUNTIME_DIR = Path(__file__).parent.parent / "_runtime"
_LOG_FILE = _RUNTIME_DIR / "logs" / "chaos_injector.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("chaos_injector")

# Approved kill targets (from spec §8)
APPROVED_KILL_TARGETS = [
    "chrome.exe",
    "firefox.exe",
    "msedge.exe",
    "notepad.exe",
    "powershell.exe",
    "cmd.exe",
    "python.exe"  # Only subprocesses, not main app
]

# Forbidden kill targets (from spec §8)
FORBIDDEN_KILL_TARGETS = [
    "explorer.exe",
    "svchost.exe",
    "dwm.exe",
    "lsass.exe",
    "csrss.exe",
    "wininit.exe"
]


def inject_network_chaos(offset_ms: int = 0) -> bool:
    """Disable and re-enable network adapter (requires Administrator)."""
    if sys.platform != "win32":
        logger.warning("Network chaos mode only supported on Windows")
        return False
    
    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            logger.error("Network chaos mode requires Administrator privileges")
            sys.exit(2)
    except Exception:
        logger.error("Could not check admin privileges")
        return False
    
    time.sleep(offset_ms / 1000.0)
    
    logger.info("Injecting network chaos: disabling adapter")
    try:
        # Disable network adapter
        subprocess.run(
            ["netsh", "interface", "set", "interface", "Ethernet", "admin=disable"],
            check=True,
            capture_output=True
        )
        logger.info("Network adapter disabled")
        
        time.sleep(2)
        
        # Re-enable network adapter
        subprocess.run(
            ["netsh", "interface", "set", "interface", "Ethernet", "admin=enable"],
            check=True,
            capture_output=True
        )
        logger.info("Network adapter re-enabled")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Network chaos failed: {e}")
        return False


def inject_cpu_chaos(offset_ms: int = 0, duration_s: int = 30) -> subprocess.Popen:
    """Launch CPU stress subprocess."""
    time.sleep(offset_ms / 1000.0)
    
    logger.info(f"Injecting CPU chaos: stress for {duration_s}s")
    
    # Python CPU stress script
    stress_code = f"""
import time
end_time = time.time() + {duration_s}
while time.time() < end_time:
    _ = sum(i * i for i in range(10000))
"""
    
    proc = subprocess.Popen(
        [sys.executable, "-c", stress_code],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    logger.info(f"CPU stress process started: PID {proc.pid}")
    return proc


def inject_kill_chaos(target_name: str, offset_ms: int = 0) -> bool:
    """Kill approved process by name."""
    if target_name not in APPROVED_KILL_TARGETS:
        logger.error(f"Target '{target_name}' not in approved kill list")
        return False
    
    if target_name in FORBIDDEN_KILL_TARGETS:
        logger.error(f"Target '{target_name}' is FORBIDDEN")
        return False
    
    time.sleep(offset_ms / 1000.0)
    
    logger.info(f"Injecting kill chaos: terminating {target_name}")
    killed = False
    
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if proc.info["name"] == target_name:
                # Don't kill main app or battle runner
                if proc.pid == psutil.Process().pid or proc.pid <= 4:
                    continue
                
                proc.terminate()
                logger.info(f"Terminated {target_name} (PID {proc.info['pid']})")
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"Could not kill process: {e}")
    
    if not killed:
        logger.warning(f"No {target_name} processes found to kill")
    
    return killed


def inject_disk_chaos(offset_ms: int = 0, target_pct: int = 90) -> list[Path]:
    """Fill disk to target percentage."""
    time.sleep(offset_ms / 1000.0)
    
    disk_fill_dir = _RUNTIME_DIR / "output" / "battle" / "disk_fill"
    disk_fill_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Injecting disk chaos: filling to {target_pct}%")
    
    # Get current disk usage
    usage = psutil.disk_usage(str(disk_fill_dir))
    current_pct = usage.percent
    
    if current_pct >= target_pct:
        logger.info(f"Disk already at {current_pct}%, no fill needed")
        return []
    
    # Calculate bytes to write
    bytes_to_write = int((target_pct - current_pct) / 100 * usage.total)
    chunk_size = 10 * 1024 * 1024  # 10 MB chunks
    
    files_created = []
    bytes_written = 0
    
    try:
        while bytes_written < bytes_to_write:
            file_path = disk_fill_dir / f"fill_{len(files_created)}.dat"
            with open(file_path, "wb") as f:
                f.write(b"\x00" * min(chunk_size, bytes_to_write - bytes_written))
            files_created.append(file_path)
            bytes_written += chunk_size
            
            if len(files_created) % 10 == 0:
                logger.info(f"Written {bytes_written / (1024**3):.2f} GB")
    except Exception as e:
        logger.error(f"Disk fill failed: {e}")
    
    logger.info(f"Disk chaos complete: created {len(files_created)} files")
    return files_created


def cleanup_disk_chaos():
    """Delete all disk fill files."""
    disk_fill_dir = _RUNTIME_DIR / "output" / "battle" / "disk_fill"
    if not disk_fill_dir.exists():
        return
    
    logger.info("Cleaning up disk chaos files")
    for file_path in disk_fill_dir.glob("fill_*.dat"):
        try:
            file_path.unlink()
        except Exception as e:
            logger.warning(f"Could not delete {file_path}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Chaos Injector for battle testing")
    parser.add_argument("--mode", required=True, choices=["network", "cpu", "kill", "disk"])
    parser.add_argument("--offset-ms", type=int, default=0, help="Delay before injection (ms)")
    parser.add_argument("--target", help="Target process name for kill mode")
    parser.add_argument("--duration", type=int, default=30, help="Duration for cpu mode (seconds)")
    parser.add_argument("--disk-pct", type=int, default=90, help="Target disk percentage for disk mode")
    
    args = parser.parse_args()
    
    logger.info(f"Starting chaos injector: mode={args.mode}, offset={args.offset_ms}ms")
    
    try:
        if args.mode == "network":
            success = inject_network_chaos(args.offset_ms)
            return 0 if success else 1
        
        elif args.mode == "cpu":
            proc = inject_cpu_chaos(args.offset_ms, args.duration)
            proc.wait()
            logger.info("CPU stress complete")
            return 0
        
        elif args.mode == "kill":
            if not args.target:
                logger.error("--target required for kill mode")
                return 1
            success = inject_kill_chaos(args.target, args.offset_ms)
            return 0 if success else 1
        
        elif args.mode == "disk":
            files = inject_disk_chaos(args.offset_ms, args.disk_pct)
            logger.info(f"Disk chaos complete: {len(files)} files created")
            return 0
    
    except KeyboardInterrupt:
        logger.info("Chaos injector interrupted")
        return 130
    except Exception as e:
        logger.error(f"Chaos injector failed: {e}")
        return 1
    finally:
        # Cleanup
        if args.mode == "disk":
            cleanup_disk_chaos()


if __name__ == "__main__":
    sys.exit(main())
