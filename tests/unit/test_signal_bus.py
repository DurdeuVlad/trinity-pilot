import asyncio

from trinity_pilot.orchestrator.signal_bus import SignalBus
from trinity_pilot.orchestrator.signals import ObjectiveStarted


def test_signal_bus_round_trips_signal():
    bus = SignalBus()
    signal = ObjectiveStarted(task_id="task-1", objective_id="obj-1")

    async def run():
        await bus.publish(signal)
        return await bus.receive()

    assert asyncio.run(run()) == signal
