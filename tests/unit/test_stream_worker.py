from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication

from trinity_pilot.ui.stream_worker import StreamWorker


def test_openai_stream_emits_deltas_and_completion():
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    chunks: list[str] = []
    completed: list[str] = []

    with patch("openai.OpenAI") as client_cls:
        client = MagicMock()
        client.responses.create.return_value = [
            SimpleNamespace(type="response.output_text.delta", delta="hello"),
            SimpleNamespace(type="response.output_text.delta", delta=" world"),
            SimpleNamespace(type="response.completed", delta="ignored"),
        ]
        client_cls.return_value = client

        worker = StreamWorker(
            provider="openai",
            api_key="fake-key",
            model="gpt-5.6-luna",
            prompt="say hello",
        )
        worker.chunk_received.connect(chunks.append)
        worker.stream_done.connect(completed.append)
        worker._run_openai()

    assert chunks == ["hello", " world"]
    assert completed == ["hello world"]
    client.responses.create.assert_called_once_with(
        model="gpt-5.6-luna",
        instructions=None,
        input="say hello",
        stream=True,
    )
