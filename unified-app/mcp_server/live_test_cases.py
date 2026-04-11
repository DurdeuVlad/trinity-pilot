"""Canonical live test-case discovery and parsing."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


_TRINITY_ROOT = Path(__file__).resolve().parents[2]
_CASES_ROOT = _TRINITY_ROOT / "docs" / "live-test-cases"


@dataclass(slots=True)
class LiveTestCase:
    """Normalized canonical live test case."""

    id: str
    title: str
    domain: str
    difficulty: str
    goal: str
    user_prompt: str
    expected_outcome: list[str]
    observation_policy: dict[str, Any]
    stop_policy: dict[str, Any]
    danger_flags: list[str]
    artifact_checks: list[str]
    postmortem_questions: list[str]
    env_vars_required: list[str]
    platform: str
    path: str
    body: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveTestCaseLibrary:
    """Resolve and enumerate canonical live test cases."""

    def __init__(self, cases_root: Path | None = None) -> None:
        self.cases_root = (cases_root or _CASES_ROOT).resolve()

    def list_cases(self) -> list[dict[str, Any]]:
        """Return canonical case summaries."""
        cases: list[dict[str, Any]] = []
        for path in sorted(self.cases_root.rglob("TC-*.md")):
            case = self.load_case(path)
            cases.append(
                {
                    "id": case.id,
                    "title": case.title,
                    "domain": case.domain,
                    "difficulty": case.difficulty,
                    "goal": case.goal,
                    "path": case.path,
                }
            )
        return cases

    def resolve_case(self, identifier: str) -> LiveTestCase:
        """Resolve a case by id or filesystem path."""
        raw = (identifier or "").strip()
        if not raw:
            raise ValueError("case identifier is required")
        candidate = Path(raw)
        if candidate.exists():
            return self.load_case(candidate)
        normalized = raw.upper()
        matches = list(self.cases_root.rglob(f"{normalized}.md"))
        if not matches:
            raise FileNotFoundError(f"Live test case not found: {identifier}")
        return self.load_case(matches[0])

    def load_case(self, path: str | Path) -> LiveTestCase:
        """Parse a canonical case markdown file."""
        case_path = Path(path).expanduser().resolve()
        self._validate_case_path(case_path)
        text = case_path.read_text(encoding="utf-8")
        metadata, body = self._split_frontmatter(text)
        case = LiveTestCase(
            id=str(metadata.get("id", "")).strip(),
            title=str(metadata.get("title", "")).strip(),
            domain=str(metadata.get("domain", "")).strip().lower(),
            difficulty=str(metadata.get("difficulty", "")).strip(),
            goal=str(metadata.get("goal", "")).strip(),
            user_prompt=str(metadata.get("user_prompt", "")).strip(),
            expected_outcome=self._as_list(metadata.get("expected_outcome")),
            observation_policy=self._as_dict(metadata.get("observation_policy")),
            stop_policy=self._as_dict(metadata.get("stop_policy")),
            danger_flags=self._as_list(metadata.get("danger_flags")),
            artifact_checks=self._as_list(metadata.get("artifact_checks")),
            postmortem_questions=self._as_list(metadata.get("postmortem_questions")),
            env_vars_required=self._as_list(metadata.get("env_vars_required")),
            platform=str(metadata.get("platform", "")).strip(),
            path=str(case_path),
            body=body.strip(),
        )
        self._validate_case_metadata(case)
        return case

    @staticmethod
    def to_execution_domain(case_domain: str) -> str:
        """Map canonical case domains to app execution domains."""
        lowered = (case_domain or "").strip().lower()
        if lowered == "browser":
            return "web"
        if lowered == "cross":
            return "mixed"
        return lowered or "mixed"

    @staticmethod
    def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
        if not text.startswith("---\n"):
            raise ValueError("Live test case is missing YAML frontmatter")
        parts = text.split("\n---\n", 1)
        if len(parts) != 2:
            raise ValueError("Live test case frontmatter is not terminated")
        metadata_raw = parts[0][4:]
        body = parts[1]
        metadata = yaml.safe_load(metadata_raw) or {}
        if not isinstance(metadata, dict):
            raise ValueError("Live test case frontmatter must be a mapping")
        return metadata, body

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _validate_case_path(self, case_path: Path) -> None:
        try:
            case_path.relative_to(self.cases_root)
        except ValueError as exc:
            raise ValueError(
                f"Live test cases must live under the canonical library: {self.cases_root}"
            ) from exc
        if not case_path.is_file():
            raise FileNotFoundError(f"Live test case not found: {case_path}")
        if not case_path.name.startswith("TC-") or case_path.suffix.lower() != ".md":
            raise ValueError(f"Invalid canonical live test case filename: {case_path.name}")

    @staticmethod
    def _validate_case_metadata(case: LiveTestCase) -> None:
        required_scalars = {
            "id": case.id,
            "title": case.title,
            "domain": case.domain,
            "goal": case.goal,
            "user_prompt": case.user_prompt,
            "platform": case.platform,
        }
        missing = [name for name, value in required_scalars.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"Live test case is missing required field(s): {', '.join(missing)}")

        required_lists = {
            "expected_outcome": case.expected_outcome,
            "danger_flags": case.danger_flags,
            "artifact_checks": case.artifact_checks,
            "postmortem_questions": case.postmortem_questions,
        }
        empty_lists = [name for name, value in required_lists.items() if not value]
        if empty_lists:
            raise ValueError(f"Live test case is missing required list field(s): {', '.join(empty_lists)}")

        if not case.observation_policy:
            raise ValueError("Live test case is missing required field: observation_policy")
        if not case.stop_policy:
            raise ValueError("Live test case is missing required field: stop_policy")
