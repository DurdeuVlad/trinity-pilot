"""Worker dispatch contract types.

Concrete worker implementations are MCP-server internals and must be imported
from their specific module only by the corresponding server.
"""
from trinity_pilot.workers.base import DomainWorker, WorkerBlocker, WorkerError

__all__ = [
    "DomainWorker",
    "WorkerError",
    "WorkerBlocker",
]
