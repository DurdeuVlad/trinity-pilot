"""Unit tests for SmartCache — the Gemini response cache layer.

Tests cover:
  - Cache hit / miss paths
  - Success gate (empty, refusal, valid)
  - failure_count tracking and eviction via report_failure
  - force_bypass flag
  - disabled cache (mock mode)
  - get_stats() accuracy
  - GeminiProvider integration (mock API)
  - TTL behaviour (via InMemoryCacheBackend expiry)
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.providers.cache import (
    InMemoryCacheBackend,
    SmartCache,
    make_cache,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is 2 + 2?"},
]
MODEL = "models/gemini-2.0-flash"
VALID_RESPONSE = '{"answer": "4"}'
EMPTY_RESPONSE = ""
WHITESPACE_RESPONSE = "   \n  "
REFUSAL_RESPONSE = "I cannot help with that as an AI assistant."


def make_smart_cache(backend=None, **kwargs) -> SmartCache:
    """Create a SmartCache backed by InMemory for test isolation."""
    return SmartCache(backend=backend if backend is not None else InMemoryCacheBackend(), **kwargs)


# ── SmartCache.get / set ───────────────────────────────────────────────────────


class TestCacheGetSet:
    def test_miss_on_first_call(self):
        cache = make_smart_cache()
        response, key = cache.get(MESSAGES, MODEL)
        assert response is None
        assert isinstance(key, str) and len(key) == 64  # SHA-256 hex

    def test_hit_on_second_call(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        response, _ = cache.get(MESSAGES, MODEL)
        assert response == VALID_RESPONSE

    def test_same_messages_same_key(self):
        cache = make_smart_cache()
        _, key1 = cache.get(MESSAGES, MODEL)
        _, key2 = cache.get(MESSAGES, MODEL)
        assert key1 == key2

    def test_different_messages_different_key(self):
        cache = make_smart_cache()
        other = [{"role": "user", "content": "Something else entirely"}]
        _, key1 = cache.get(MESSAGES, MODEL)
        _, key2 = cache.get(other, MODEL)
        assert key1 != key2

    def test_different_model_different_key(self):
        cache = make_smart_cache()
        _, key1 = cache.get(MESSAGES, MODEL)
        _, key2 = cache.get(MESSAGES, "models/gemini-1.5-pro")
        assert key1 != key2

    def test_set_returns_true_for_valid_response(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        result = cache.set(key, VALID_RESPONSE, MODEL)
        assert result is True

    def test_set_returns_false_for_empty_response(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        result = cache.set(key, EMPTY_RESPONSE, MODEL)
        assert result is False

    def test_set_returns_false_for_whitespace_response(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        result = cache.set(key, WHITESPACE_RESPONSE, MODEL)
        assert result is False

    def test_empty_response_not_cached(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, EMPTY_RESPONSE, MODEL)
        # Should still be a miss
        response, _ = cache.get(MESSAGES, MODEL)
        assert response is None

    def test_refusal_response_not_cached(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        result = cache.set(key, REFUSAL_RESPONSE, MODEL)
        assert result is False
        response, _ = cache.get(MESSAGES, MODEL)
        assert response is None

    def test_various_refusal_patterns(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        refusals = [
            "As an AI, I cannot do that.",
            "I'm not able to assist with this.",
            "I am not able to provide that information.",
            "I don't have access to real-time data.",
            "I'm sorry, but I can't help.",
        ]
        for refusal in refusals:
            result = cache.set(key, refusal, MODEL)
            assert result is False, f"Should reject refusal: {refusal!r}"


# ── Success gate ───────────────────────────────────────────────────────────────


class TestSuccessGate:
    def test_valid_json_response_cached(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        assert cache.set(key, VALID_RESPONSE, MODEL) is True

    def test_valid_text_response_cached(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        assert cache.set(key, "The capital of France is Paris.", MODEL) is True

    def test_single_word_cached(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        # Short but valid
        assert cache.set(key, "OK", MODEL) is True


# ── Failure tracking and AI-driven bypass ────────────────────────────────────


class TestFailureTracking:
    def test_report_failure_increments_count(self):
        cache = make_smart_cache(bypass_threshold=3)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        # Should still be a hit after one failure (threshold is 3)
        cache.report_failure(key)
        response, _ = cache.get(MESSAGES, MODEL)
        assert response == VALID_RESPONSE

    def test_report_failure_evicts_at_threshold(self):
        cache = make_smart_cache(bypass_threshold=2)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        # Two failures → should evict
        cache.report_failure(key)
        cache.report_failure(key)
        response, _ = cache.get(MESSAGES, MODEL)
        assert response is None

    def test_report_failure_on_missing_key_is_noop(self):
        cache = make_smart_cache()
        # Should not raise
        cache.report_failure("nonexistent_key_" + "a" * 50)

    def test_eviction_increments_stat(self):
        cache = make_smart_cache(bypass_threshold=2)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        cache.report_failure(key)
        cache.report_failure(key)
        stats = cache.get_stats()
        assert stats["evictions"] == 1

    def test_read_evicts_at_threshold(self):
        """Lazy eviction: entry with failure_count >= threshold is evicted on read."""
        backend = InMemoryCacheBackend()
        cache = make_smart_cache(backend=backend, bypass_threshold=2)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        # Manually set failure_count to threshold in backend
        entry = backend.get(key)
        entry["failure_count"] = 2
        backend.set(key, entry, 3600)
        # Next read should evict and return None
        response, _ = cache.get(MESSAGES, MODEL)
        assert response is None
        stats = cache.get_stats()
        assert stats["evictions"] >= 1


# ── Force bypass ───────────────────────────────────────────────────────────────


class TestForceBypass:
    def test_force_bypass_skips_cache(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        # Bypass should return None even though cached
        response, _ = cache.get(MESSAGES, MODEL, force_bypass=True)
        assert response is None

    def test_force_bypass_increments_bypass_stat(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        cache.get(MESSAGES, MODEL, force_bypass=True)
        stats = cache.get_stats()
        assert stats["bypasses"] == 1

    def test_force_bypass_does_not_evict(self):
        """After force_bypass, the entry should still be there for non-bypassed reads."""
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        cache.get(MESSAGES, MODEL, force_bypass=True)
        # Normal read should still hit
        response, _ = cache.get(MESSAGES, MODEL)
        assert response == VALID_RESPONSE


# ── Disabled cache (mock mode) ─────────────────────────────────────────────────


class TestDisabledCache:
    def test_disabled_cache_always_misses(self):
        cache = make_smart_cache(enabled=False)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        response, _ = cache.get(MESSAGES, MODEL)
        assert response is None

    def test_disabled_cache_set_returns_false(self):
        cache = make_smart_cache(enabled=False)
        _, key = cache.get(MESSAGES, MODEL)
        assert cache.set(key, VALID_RESPONSE, MODEL) is False

    def test_disabled_cache_report_failure_is_noop(self):
        cache = make_smart_cache(enabled=False)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        cache.report_failure(key)  # Should not raise


# ── get_stats ──────────────────────────────────────────────────────────────────


class TestGetStats:
    def test_initial_stats_are_zero(self):
        cache = make_smart_cache()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["bypasses"] == 0
        assert stats["evictions"] == 0

    def test_miss_increments_miss(self):
        cache = make_smart_cache()
        cache.get(MESSAGES, MODEL)
        assert cache.get_stats()["misses"] == 1

    def test_hit_increments_hit(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        cache.get(MESSAGES, MODEL)
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1  # the first get was a miss

    def test_bypass_increments_bypass(self):
        cache = make_smart_cache()
        cache.get(MESSAGES, MODEL, force_bypass=True)
        assert cache.get_stats()["bypasses"] == 1

    def test_stats_include_enabled_flag(self):
        cache = make_smart_cache(enabled=False)
        assert cache.get_stats()["enabled"] is False

    def test_clear_resets_stats(self):
        cache = make_smart_cache()
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        cache.get(MESSAGES, MODEL)
        cache.clear()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0


# ── make_cache factory ─────────────────────────────────────────────────────────


class TestMakeCacheFactory:
    def test_make_cache_disabled_returns_disabled(self):
        cache = make_cache(enabled=False)
        assert cache.enabled is False

    def test_make_cache_enabled_creates_working_cache(self):
        """make_cache(enabled=True) returns a functional SmartCache instance."""
        import tempfile
        tmpdir = tempfile.mkdtemp()
        cache = make_cache(enabled=True, directory=tmpdir)
        assert cache.enabled is True
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL)
        response, _ = cache.get(MESSAGES, MODEL)
        # Close diskcache before cleanup to release Windows file locks
        if hasattr(cache._backend, "_cache"):
            cache._backend._cache.close()
        assert response == VALID_RESPONSE


# ── GeminiProvider integration ─────────────────────────────────────────────────


class TestGeminiProviderIntegration:
    """Test GeminiProvider with a mocked Gemini client and SmartCache."""

    def _make_provider(self, **cache_kwargs):
        """Create GeminiProvider with mocked google-genai and SmartCache."""
        from orchestrator.providers.gemini_provider import GeminiProvider
        cache = make_smart_cache(**cache_kwargs)

        # GeminiProvider will use the mock from testing.gemini_mock which is already active
        provider = GeminiProvider(api_key="test-key", cache=cache)

        # Inject fresh mock client
        mock_response = MagicMock()
        mock_response.text = VALID_RESPONSE
        provider._client = MagicMock()
        provider._client.aio = MagicMock()
        provider._client.aio.models = MagicMock()
        provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        return provider, cache

    def test_first_call_hits_api(self):
        provider, cache = self._make_provider()

        async def run():
            return await provider.call(MESSAGES)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(run())
            assert result == VALID_RESPONSE
            provider._client.aio.models.generate_content.assert_called_once()
        finally:
            loop.close()

    def test_second_call_served_from_cache(self):
        provider, cache = self._make_provider()

        async def run():
            await provider.call(MESSAGES)        # miss → API
            return await provider.call(MESSAGES)  # hit → cache

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(run())
            assert result == VALID_RESPONSE
            # API should only be called once
            assert provider._client.aio.models.generate_content.call_count == 1
        finally:
            loop.close()

    def test_force_bypass_calls_api_twice(self):
        provider, cache = self._make_provider()

        async def run():
            await provider.call(MESSAGES)                         # miss → API
            return await provider.call(MESSAGES, force_bypass=True)  # bypass → API

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
            assert provider._client.aio.models.generate_content.call_count == 2
        finally:
            loop.close()

    def test_report_cache_failure_evicts_at_threshold(self):
        provider, cache = self._make_provider(bypass_threshold=2)

        async def run():
            await provider.call(MESSAGES)   # miss → API, stores in cache
            await provider.call(MESSAGES)   # hit → cache
            provider.report_cache_failure()  # failure 1
            provider.report_cache_failure()  # failure 2 → evict
            return await provider.call(MESSAGES)  # miss → API again

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
            # API called on first call + after eviction = 2
            assert provider._client.aio.models.generate_content.call_count == 2
        finally:
            loop.close()

    def test_report_cache_failure_without_cache_is_noop(self):
        from orchestrator.providers.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="test-key", cache=None)
        provider.report_cache_failure()  # Should not raise

    def test_cache_stats_property(self):
        provider, cache = self._make_provider()

        async def run():
            await provider.call(MESSAGES)
            await provider.call(MESSAGES)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
            stats = provider.cache_stats
            assert stats is not None
            assert stats["hits"] == 1
            assert stats["misses"] == 1
        finally:
            loop.close()

    def test_cache_stats_none_without_cache(self):
        from orchestrator.providers.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="test-key", cache=None)
        assert provider.cache_stats is None

    def test_no_cache_on_mock_api_key(self):
        """factory.make_provider with api_key='mock' should return MockProvider (no cache)."""
        from orchestrator.providers.factory import make_provider
        provider = make_provider("gemini", "mock")
        # MockProvider has no cache attribute
        assert not hasattr(provider, "cache") or getattr(provider, "cache", None) is None


# ── TTL expiry ──────────────────────────────────────────────────────────────────


class TestTTLExpiry:
    def test_expired_entry_treated_as_miss(self):
        backend = InMemoryCacheBackend()
        cache = SmartCache(backend=backend, default_ttl=1)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL, ttl=1)
        # Entry is fresh
        response, _ = cache.get(MESSAGES, MODEL)
        assert response == VALID_RESPONSE
        # Simulate TTL expiry by manipulating the backend store directly
        entry, _ = backend._store[key]
        backend._store[key] = (entry, time.time() - 1)  # expired
        response, _ = cache.get(MESSAGES, MODEL)
        assert response is None

    def test_action_ttl_applied_when_is_action_call_true(self):
        """is_action_call=True should use action_ttl, not default_ttl."""
        backend = InMemoryCacheBackend()
        cache = SmartCache(backend=backend, default_ttl=3600, action_ttl=300)
        _, key = cache.get(MESSAGES, MODEL)
        cache.set(key, VALID_RESPONSE, MODEL, is_action_call=True)
        _, expiry = backend._store[key]
        # Expiry should be ~300s from now (within 5s tolerance)
        expected = time.time() + 300
        assert abs(expiry - expected) < 5
