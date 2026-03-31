"""ChaosLayer — wraps TrinityBridge with configurable failure injection.

Activated via environment variables for testing orchestrator resilience:

    CHAOS_MODE=random_fail CHAOS_PROB=0.4 python ...

Available modes:
    random_fail     — randomly returns an error result (default prob=0.3)
    timeout         — hangs longer than MAX_WALL_SECONDS to trigger timeout
    partial_result  — returns a result with no artifacts (partial output)
    corrupt_output  — returns malformed/empty output string

Usage (in tests):
    from orchestrator.chaos_layer import ChaosLayer, ChaosConfig
    bridge = ChaosLayer(real_bridge, ChaosConfig(mode="random_fail", probability=0.5))

Usage (via env):
    import os
    os.environ["CHAOS_MODE"] = "random_fail"
    bridge = ChaosLayer.from_env(real_bridge)
"""
from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal

ChaosMode = Literal["random_fail", "timeout", "partial_result", "corrupt_output", "off"]

_WALL_SECONDS_OVER_LIMIT = 300  # longer than agent_loop.MAX_WALL_SECONDS (240)


@dataclass
class ChaosConfig:
    mode: ChaosMode = "off"
    probability: float = 0.3      # for random_fail: chance of injecting failure
    seed: int | None = None       # if set, makes chaos deterministic for tests

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {self.probability}")

    @classmethod
    def from_env(cls) -> "ChaosConfig":
        mode = os.environ.get("CHAOS_MODE", "off").strip().lower()
        prob = float(os.environ.get("CHAOS_PROB", "0.3"))
        return cls(mode=mode, probability=prob)  # type: ignore[arg-type]


class ChaosLayer:
    """Drop-in TrinityBridge wrapper that injects failures for resilience testing."""

    def __init__(self, bridge: Any, config: ChaosConfig | None = None) -> None:
        self._bridge = bridge
        self._config = config or ChaosConfig()
        self._rng = random.Random(self._config.seed)
        self._call_count = 0

    @classmethod
    def from_env(cls, bridge: Any) -> "ChaosLayer":
        return cls(bridge, ChaosConfig.from_env())

    # ── Bridge interface passthrough ─────────────────────────────────────────

    async def initialize(self) -> None:
        await self._bridge.initialize()

    async def shutdown(self) -> None:
        await self._bridge.shutdown()

    async def execute_task(self, **kwargs: Any) -> Any:
        self._call_count += 1
        mode = self._config.mode

        if mode == "off":
            return await self._bridge.execute_task(**kwargs)

        if mode == "random_fail":
            if self._rng.random() < self._config.probability:
                return self._make_error_result("chaos: random_fail injected")
            return await self._bridge.execute_task(**kwargs)

        if mode == "timeout":
            await asyncio.sleep(_WALL_SECONDS_OVER_LIMIT)
            return await self._bridge.execute_task(**kwargs)

        if mode == "partial_result":
            result = await self._bridge.execute_task(**kwargs)
            return self._strip_artifacts(result)

        if mode == "corrupt_output":
            result = await self._bridge.execute_task(**kwargs)
            return self._corrupt_output(result)

        # Unknown mode — pass through without chaos
        return await self._bridge.execute_task(**kwargs)

    # ── Failure factories ─────────────────────────────────────────────────────

    @staticmethod
    def _make_error_result(reason: str) -> Any:
        result = SimpleNamespace()
        result.status = "error"
        result.output = f"[chaos error: {reason}]"
        result.error = reason
        result.execution_log = [{"event": "chaos_injection", "detail": reason}]
        result.artifacts = []
        result.metadata = {"chaos": True}
        return result

    @staticmethod
    def _strip_artifacts(result: Any) -> Any:
        """Return result with artifacts cleared (simulates partial backend output)."""
        try:
            result.artifacts = []
        except AttributeError:
            pass
        return result

    @staticmethod
    def _corrupt_output(result: Any) -> Any:
        """Return result with output replaced by malformed content."""
        try:
            result.output = ""
        except AttributeError:
            pass
        try:
            result.status = "error"
        except AttributeError:
            pass
        return result

    # ── Diagnostics ──────────────────────────────────────────────────────────

    @property
    def call_count(self) -> int:
        return self._call_count
