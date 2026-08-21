from zipfile import ZipFile

import pytest

from scripts.build_exe import create_release_archive


def test_release_archive_contains_executable_at_root(tmp_path):
    package_dir = tmp_path / "trinity-pilot"
    package_dir.mkdir()
    (package_dir / "trinity-pilot.exe").write_bytes(b"fake executable")
    (package_dir / "_internal" / "runtime.dll").parent.mkdir()
    (package_dir / "_internal" / "runtime.dll").write_bytes(b"fake runtime")

    archive_path = tmp_path / "trinity-pilot-win64.zip"
    result = create_release_archive(package_dir, archive_path)

    assert result == archive_path
    with ZipFile(result) as archive:
        assert sorted(archive.namelist()) == [
            "_internal/runtime.dll",
            "trinity-pilot.exe",
        ]


def test_release_archive_requires_executable(tmp_path):
    package_dir = tmp_path / "trinity-pilot"
    package_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="trinity-pilot.exe"):
        create_release_archive(package_dir, tmp_path / "release.zip")
