#!/usr/bin/env python3
"""Automated standalone executable build script for Trinity Pilot using PyInstaller."""
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ARCHIVE_NAME = "trinity-pilot-win64.zip"


def create_release_archive(package_dir: Path, archive_path: Path) -> Path:
    """Create the documented release archive with the executable at its root."""
    executable = package_dir / "trinity-pilot.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Expected packaged executable at {executable}")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in package_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir).as_posix())
    return archive_path


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
    if not dist_dir.exists():
        print("\nBuild completed but target dist directory was not found.")
        sys.exit(1)

    archive_path = repo_root / "dist" / ARCHIVE_NAME
    try:
        create_release_archive(dist_dir, archive_path)
    except FileNotFoundError as exc:
        print(f"\nBuild completed but release packaging failed: {exc}")
        sys.exit(1)

    print(
        "\nBuild successful!\n"
        f"  Executable directory: {dist_dir.resolve()}\n"
        f"  Release archive: {archive_path.resolve()}"
    )


if __name__ == "__main__":
    main()
