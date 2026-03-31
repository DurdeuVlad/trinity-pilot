"""Basic runtime profile wrapper for app startup."""
from __future__ import annotations

import cProfile
import pstats

from main import main


def run_profile() -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    try:
        main()
    finally:
        profiler.disable()
        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative")
        stats.print_stats(30)


if __name__ == "__main__":
    run_profile()
