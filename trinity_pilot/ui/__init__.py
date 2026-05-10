__all__ = [
    "MainWindow",
    "run_app",
    "ChatWidget",
    "ChatState",
    "ThinkingIndicator",
    "ObjectiveChipsWidget",
    "StreamWorker",
]


def __getattr__(name: str):
    if name in __all__:
        import trinity_pilot.ui as _mod
        from trinity_pilot.ui.app import MainWindow, run_app  # noqa: F401
        from trinity_pilot.ui.chat_widget import ChatState, ChatWidget  # noqa: F401
        from trinity_pilot.ui.objective_chips import ObjectiveChipsWidget  # noqa: F401
        from trinity_pilot.ui.stream_worker import StreamWorker  # noqa: F401
        from trinity_pilot.ui.thinking_indicator import ThinkingIndicator  # noqa: F401
        return getattr(_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
