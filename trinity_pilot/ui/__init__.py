__all__ = ["MainWindow", "run_app"]


def __getattr__(name: str):
    if name in __all__:
        from trinity_pilot.ui.app import MainWindow, run_app  # noqa: F401
        import trinity_pilot.ui as _mod
        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
