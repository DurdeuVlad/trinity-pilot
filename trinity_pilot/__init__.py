"""Trinity Pilot — LLM-orchestrated desktop automation agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("trinity-pilot")
except PackageNotFoundError:
    # Source checkouts that have not been installed still need a stable value.
    __version__ = "0.1.0"
