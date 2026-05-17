"""Live audit helpers for Trinity Pilot confidence runs."""

__all__ = [
    "FlightRecorder",
    "check_live_prerequisites",
    "run_active_path_preflight",
    "validate_record",
]


def __getattr__(name: str):
    if name in {"FlightRecorder", "validate_record"}:
        from trinity_pilot.audit.flight_record import FlightRecorder, validate_record

        return {"FlightRecorder": FlightRecorder, "validate_record": validate_record}[name]
    if name == "run_active_path_preflight":
        from trinity_pilot.audit.preflight import run_active_path_preflight

        return run_active_path_preflight
    if name == "check_live_prerequisites":
        from trinity_pilot.audit.prerequisites import check_live_prerequisites

        return check_live_prerequisites
    raise AttributeError(name)
