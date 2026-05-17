from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

BANNED_TOKENS = ("temporal" + "io", "Task" + "Workflow", "worker" + "_runner")
ACTIVE_SUFFIXES = (".py", ".toml", ".sh", ".ps1", ".bat", ".cmd", ".md")
HISTORICAL_PARTS = {"docs", "changelog.md", "changeLog.md", "CHANGELOG.md"}
DEFAULT_ACTIVE_ROOTS = ("trinity_pilot", "tests", "pyproject.toml", "setup.sh")
DEFAULT_HISTORICAL_ROOTS = ("docs", "CHANGELOG.md")
NEGATIVE_GUARD_FILES = {"test_no_temporal_imports.py"}


@dataclass
class PreflightFinding:
    path: str
    line: int
    token: str
    classification: str
    text: str


@dataclass
class PreflightResult:
    passed: bool
    scanned_paths: list[str] = field(default_factory=list)
    findings: list[PreflightFinding] = field(default_factory=list)
    historical_findings: list[PreflightFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["finding_count"] = len(self.findings)
        data["historical_finding_count"] = len(self.historical_findings)
        return data


def _iter_files(root: Path, entries: Iterable[str]) -> Iterable[Path]:
    for entry in entries:
        path = root / entry
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix in ACTIVE_SUFFIXES or path.name in {"pyproject.toml", "CHANGELOG.md"}:
                yield path
            continue
        for child in path.rglob("*"):
            if child.is_file() and child.suffix in ACTIVE_SUFFIXES:
                yield child


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan_file(root: Path, path: Path, classification: str) -> list[PreflightFinding]:
    findings: list[PreflightFinding] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return findings
    for idx, line in enumerate(lines, start=1):
        for token in BANNED_TOKENS:
            if token.lower() in line.lower():
                findings.append(
                    PreflightFinding(
                        path=_rel(root, path),
                        line=idx,
                        token=token,
                        classification=classification,
                        text=line.strip()[:240],
                    )
                )
    return findings


def run_active_path_preflight(
    root: str | Path = ".",
    *,
    active_roots: Iterable[str] = DEFAULT_ACTIVE_ROOTS,
    historical_roots: Iterable[str] = DEFAULT_HISTORICAL_ROOTS,
) -> PreflightResult:
    repo = Path(root).resolve()
    historical_paths = {p.resolve() for p in _iter_files(repo, historical_roots)}
    active_paths = []
    findings: list[PreflightFinding] = []
    historical_findings: list[PreflightFinding] = []

    for path in sorted(_iter_files(repo, active_roots)):
        if path.resolve() in historical_paths:
            continue
        if path.name in NEGATIVE_GUARD_FILES:
            continue
        active_paths.append(_rel(repo, path))
        findings.extend(_scan_file(repo, path, "active"))

    for path in sorted(historical_paths):
        historical_findings.extend(_scan_file(repo, path, "historical"))

    return PreflightResult(
        passed=not findings,
        scanned_paths=active_paths,
        findings=findings,
        historical_findings=historical_findings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args(argv)
    result = run_active_path_preflight(args.root)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
