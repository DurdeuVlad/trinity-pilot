"""Artifact mapping and normalization for backend MCP responses.

Maps backend-specific artifacts into unified-app consumable formats.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class ArtifactMapper:
    """Maps backend artifacts to unified formats."""

    @staticmethod
    def normalize_artifacts(
        backend_type: str, artifacts: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Normalize backend artifacts into unified-app artifact list.
        
        Args:
            backend_type: Backend type (cli, browser, desktop)
            artifacts: Raw artifacts from backend MCP server
            
        Returns:
            List of artifact paths/references
        """
        normalized = []

        for artifact in artifacts:
            artifact_type = artifact.get("artifact_type", "unknown")
            artifact_id = artifact.get("artifact_id", "unknown")
            path = artifact.get("path")

            if path:
                normalized.append(path)
            else:
                normalized.append(f"{backend_type}:{artifact_type}:{artifact_id}")

        return normalized

    @staticmethod
    def extract_metadata(
        backend_type: str, result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract and normalize metadata from backend result.
        
        Args:
            backend_type: Backend type (cli, browser, desktop)
            result: Raw result from backend MCP server
            
        Returns:
            Normalized metadata dictionary
        """
        metadata = result.get("metadata", {})

        normalized = {
            "backend": backend_type,
            "session_id": result.get("session_id"),
            "objective_id": result.get("objective_id"),
        }

        if backend_type == "cli":
            normalized["commands_executed"] = metadata.get("commands_executed", 0)
            normalized["files_modified"] = metadata.get("files_modified", [])

        elif backend_type == "browser":
            normalized["pages_visited"] = metadata.get("pages_visited", [])
            normalized["screenshots_captured"] = metadata.get("screenshots_captured", 0)

        elif backend_type == "desktop":
            normalized["windows_interacted"] = metadata.get("windows_interacted", [])
            normalized["uia_elements_accessed"] = metadata.get("uia_elements_accessed", 0)

        normalized.update(metadata)

        return normalized

    @staticmethod
    def map_failure_category(
        _backend_type: str, error: str, failure_category: str = None
    ) -> str:
        """
        Map backend failure to unified failure category.
        
        Args:
            _backend_type: Backend type (cli, browser, desktop) - reserved for future use
            error: Error message
            failure_category: Optional explicit failure category from backend
            
        Returns:
            Normalized failure category string
        """
        if failure_category:
            return failure_category

        error_lower = error.lower() if error else ""

        if "unavailable" in error_lower or "not found" in error_lower:
            return "backend_unavailable"
        elif "timeout" in error_lower:
            return "timeout"
        elif "blocked" in error_lower or "rejected" in error_lower:
            return "validator_rejection"
        elif "interrupted" in error_lower:
            return "interrupted"
        elif "terminated" in error_lower:
            return "terminated"
        else:
            return "execution_failure"
