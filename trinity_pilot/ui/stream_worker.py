from __future__ import annotations

import google.genai as genai
from google.genai import types as genai_types
from PySide6.QtCore import QThread, Signal


class StreamWorker(QThread):
    """Streams a Gemini response in a background thread, emitting chunks to the UI."""

    chunk_received = Signal(str)
    stream_done = Signal(str)
    stream_error = Signal(str)

    def __init__(
        self,
        api_key: str,
        model: str,
        prompt: str,
        system: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self._model = model
        self._prompt = prompt
        self._system = system

    def run(self) -> None:
        try:
            client = genai.Client(api_key=self._api_key)
            config = (
                genai_types.GenerateContentConfig(system_instruction=self._system)
                if self._system
                else None
            )
            full_text = ""
            for chunk in client.models.generate_content_stream(
                model=self._model,
                contents=self._prompt,
                config=config,
            ):
                try:
                    text = chunk.text or ""
                except Exception:
                    text = ""
                if text:
                    full_text += text
                    self.chunk_received.emit(text)
            self.stream_done.emit(full_text)
        except Exception as exc:  # noqa: BLE001
            self.stream_error.emit(str(exc))
