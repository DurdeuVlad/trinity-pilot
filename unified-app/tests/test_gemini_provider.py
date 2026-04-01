from __future__ import annotations

import asyncio
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from orchestrator.providers.gemini_provider import GeminiProvider


def test_gemini_provider_close_closes_async_and_sync_clients() -> None:
    seen = {"async_close": False, "sync_close": False}

    class _FakeAioClient:
        async def aclose(self) -> None:
            seen["async_close"] = True

    class _FakeClient:
        def __init__(self) -> None:
            self.aio = _FakeAioClient()

        def close(self) -> None:
            seen["sync_close"] = True

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = _FakeClient()

    asyncio.run(provider.close())

    assert seen == {"async_close": True, "sync_close": True}
