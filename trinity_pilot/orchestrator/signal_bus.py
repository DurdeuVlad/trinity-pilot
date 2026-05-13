from __future__ import annotations

import asyncio

from trinity_pilot.orchestrator.signals import Signal


class SignalBus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Signal] = asyncio.Queue()

    async def publish(self, signal: Signal) -> None:
        await self._queue.put(signal)

    async def receive(self) -> Signal:
        return await self._queue.get()

