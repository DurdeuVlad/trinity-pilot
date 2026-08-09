#!/usr/bin/env python3
"""Automated standalone executable build script for Trinity Pilot using PyInstaller."""
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    print("Building Trinity Pilot standalone executable...")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "pyinstaller.spec"]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error: PyInstaller build failed with exit code {e.returncode}")
        sys.exit(e.returncode)

    dist_dir = repo_root / "dist" / "trinity-pilot"
    if dist_dir.exists():
        print(f"\nBuild successful! Executable directory created at:\n  {dist_dir.resolve()}")
    else:
        print("\nBuild completed but target dist directory was not found.")


if __name__ == "__main__":
    main()
