"""TC-S6: Compatibility shims and deprecation helpers for trinity_core contract migration.

Deprecated contract elements (cutover from legacy to v1 normalized contract):

TRINITY-COMPAT-001: capabilities top-level 'thread_safe' key
  - Old path:  caps["thread_safe"]
  - New path:  caps["constraints"]["thread_safe"]
  - Scheduled removal: after TC-S3 conformance is verified by all consumers.

TRINITY-COMPAT-002: capabilities top-level 'async' key
  - Old path:  caps["async"]
  - New path:  caps["constraints"]["async"]
  - Scheduled removal: after TC-S3 conformance is verified by all consumers.

TRINITY-COMPAT-003: capabilities top-level 'platforms' key
  - Old path:  caps["platforms"]
  - New path:  caps["constraints"]["platforms"]
  - Scheduled removal: after TC-S3 conformance is verified by all consumers.

TRINITY-COMPAT-004: TaskResult error field as primary failure descriptor
  - Old pattern: consumers inspect result.error for failure routing
  - New pattern: consumers use result.code and result.category for machine routing;
    result.error is preserved as the human-readable legacy field.
  - Scheduled removal: no removal planned; error is kept for observability.

Cutover gate criteria (all must pass before removing shims):
1. All consumers use caps["constraints"]["thread_safe"] instead of caps["thread_safe"].
2. All consumers use result.code and result.category instead of string-parsing result.error.
3. pytest trinity_core/tests -k capabilities passes with all adapters conforming to schema v1.
4. pytest trinity_core/tests -k error passes with all adapter error shape tests green.
5. No test references caps["thread_safe"], caps["async"], or caps["platforms"] directly.
"""

from __future__ import annotations

import warnings


def warn_deprecated(identifier: str, message: str, stacklevel: int = 2) -> None:
    """Emit a DeprecationWarning with a stable identifier prefix."""
    warnings.warn(
        f"[{identifier}] {message}",
        DeprecationWarning,
        stacklevel=stacklevel + 1,
    )
