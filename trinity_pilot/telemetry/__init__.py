"""Trinity Pilot telemetry — unified NDJSON trace logging."""

from trinity_pilot.telemetry.trace import emit, export_attempts_json, is_enabled

__all__ = ["emit", "export_attempts_json", "is_enabled"]
