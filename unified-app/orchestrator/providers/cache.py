"""Smart LLM response cache — caches only successful Gemini responses.

Architecture
------------
Three-layer design:
  L1  GeminiProvider.call() checks SmartCache before hitting the API.
  L2  SmartCache.get() → DiskCacheBackend (diskcache, SQLite-backed).
  L3  SmartCache.set() writes only after the success gate passes.

Success gate (write-time)
  - Response must be non-empty / non-whitespace.
  - Response must not match known Gemini refusal patterns.

AI-driven bypass (read-time)
  - Each cache entry carries failure_count (default 0).
  - Callers call report_failure(key) when a cached response caused a
    downstream error.  After BYPASS_THRESHOLD failures the entry is evicted
    and the next call hits the live API.
  - force_bypass=True on GeminiProvider.call() skips cache for one call.

Mock / test mode
  - Pass enabled=False to SmartCache (factory.py does this automatically
    when GEMINI_MOCK env var is set or api_key=="mock").
  - Use InMemoryCacheBackend for unit tests — zero disk I/O.

Environment variables
  GEMINI_CACHE_TTL_SECONDS          default TTL in seconds        (default 3600)
  GEMINI_CACHE_ACTION_TTL_SECONDS   TTL for non-JSON calls        (default 300)
  GEMINI_CACHE_BYPASS_THRESHOLD     failure_count before eviction (default 2)
  GEMINI_CACHE_MAX_SIZE_BYTES       max disk cache size           (default 500 MB)
  GEMINI_CACHE_DIR                  diskcache directory           (default _runtime/cache/gemini_responses)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# ── Configuration (env-overrideable) ──────────────────────────────────────────

DEFAULT_TTL: int = int(os.getenv("GEMINI_CACHE_TTL_SECONDS", "3600"))
ACTION_TTL: int = int(os.getenv("GEMINI_CACHE_ACTION_TTL_SECONDS", "300"))
BYPASS_THRESHOLD: int = int(os.getenv("GEMINI_CACHE_BYPASS_THRESHOLD", "2"))
MAX_CACHE_BYTES: int = int(os.getenv("GEMINI_CACHE_MAX_SIZE_BYTES", str(500 * 1024 * 1024)))
DEFAULT_CACHE_DIR: str = os.getenv(
    "GEMINI_CACHE_DIR",
    os.path.join("_runtime", "cache", "gemini_responses"),
)

# Gemini refusal patterns (lowercase — matched against lowercased response)
_REFUSAL_PATTERNS: tuple[str, ...] = (
    "i cannot",
    "as an ai",
    "i'm not able to",
    "i am not able to",
    "i don't have access to",
    "i'm sorry, but i",
    "sorry, i'm not able",
)


# ── Backend interface ──────────────────────────────────────────────────────────


class CacheBackend(ABC):
    """Abstract persistence layer for SmartCache."""

    @abstractmethod
    def get(self, key: str) -> dict | None:
        """Return the stored entry dict, or None if absent / expired."""
        ...

    @abstractmethod
    def set(self, key: str, value: dict, ttl: int) -> None:
        """Persist the entry.  ttl=0 means no expiry."""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove entry if present (no-op if absent)."""
        ...

    @abstractmethod
    def size_bytes(self) -> int:
        """Approximate storage size in bytes."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Evict all entries."""
        ...


# ── In-memory backend (tests / fallback) ──────────────────────────────────────


class InMemoryCacheBackend(CacheBackend):
    """Thread-safe in-memory backend.  Does not survive process restart."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[dict, float]] = {}

    def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        data, expires_at = entry
        if expires_at and time.time() > expires_at:
            del self._store[key]
            return None
        return data

    def set(self, key: str, value: dict, ttl: int) -> None:
        expires_at = time.time() + ttl if ttl > 0 else 0.0
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def size_bytes(self) -> int:
        return sum(len(json.dumps(v)) for v, _ in self._store.values())

    def clear(self) -> None:
        self._store.clear()


# ── Disk backend (production) ──────────────────────────────────────────────────


class DiskCacheBackend(CacheBackend):
    """diskcache-backed persistent store.  Safe for concurrent async access."""

    def __init__(
        self,
        directory: str = DEFAULT_CACHE_DIR,
        max_size: int = MAX_CACHE_BYTES,
    ) -> None:
        try:
            import diskcache  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "diskcache is required for DiskCacheBackend. "
                "Install it with: pip install diskcache"
            ) from exc

        os.makedirs(directory, exist_ok=True)
        self._cache = diskcache.Cache(directory, size_limit=max_size)

    def get(self, key: str) -> dict | None:
        raw = self._cache.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self._cache.delete(key)
            return None

    def set(self, key: str, value: dict, ttl: int) -> None:
        kwargs: dict = {"expire": ttl} if ttl > 0 else {}
        self._cache.set(key, json.dumps(value), **kwargs)

    def delete(self, key: str) -> None:
        self._cache.delete(key)

    def size_bytes(self) -> int:
        return int(self._cache.volume())

    def clear(self) -> None:
        self._cache.clear()


# ── Smart cache ────────────────────────────────────────────────────────────────


class SmartCache:
    """Cache for LLM responses with success gate and AI-driven bypass.

    Usage::

        cache = SmartCache()

        # Before calling the LLM:
        response, key = cache.get(messages, model="models/gemini-2.0-flash")
        if response is None:
            response = await llm.generate(messages)
            cache.set(key, response, model="models/gemini-2.0-flash")

        # When downstream code indicates the response was bad:
        cache.report_failure(key)
    """

    def __init__(
        self,
        *,
        backend: CacheBackend | None = None,
        schema_version: str = "v1",
        default_ttl: int = DEFAULT_TTL,
        action_ttl: int = ACTION_TTL,
        bypass_threshold: int = BYPASS_THRESHOLD,
        enabled: bool = True,
    ) -> None:
        self.schema_version = schema_version
        self.default_ttl = default_ttl
        self.action_ttl = action_ttl
        self.bypass_threshold = bypass_threshold
        self.enabled = enabled
        self._backend = backend if backend is not None else InMemoryCacheBackend()
        self._stats: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "bypasses": 0,
            "evictions": 0,
        }

    # ── Key derivation ────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().strip())

    def make_key(self, messages: list[dict], model: str) -> str:
        """Deterministic cache key from full messages list + model + schema version."""
        normalized = self._normalize(json.dumps(messages, sort_keys=True))
        raw = f"{normalized}|{model}|{self.schema_version}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── Success gate ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_cacheable(response: str) -> bool:
        """Return True iff the response passes all write-gate checks."""
        if not response or not response.strip():
            return False
        lower = response.lower()
        return not any(pattern in lower for pattern in _REFUSAL_PATTERNS)

    # ── Public API ────────────────────────────────────────────────────────────

    def get(
        self,
        messages: list[dict],
        model: str,
        *,
        force_bypass: bool = False,
    ) -> tuple[str | None, str]:
        """Check cache.  Returns (response, cache_key).

        response is None on miss, bypass, or disabled cache.
        cache_key is always returned for use in set() / report_failure().
        """
        key = self.make_key(messages, model)

        if not self.enabled:
            return None, key

        if force_bypass:
            self._stats["bypasses"] += 1
            logger.debug("cache bypass (force_bypass=True): key=%.12s", key)
            return None, key

        entry = self._backend.get(key)
        if entry is None:
            self._stats["misses"] += 1
            logger.debug("cache miss: key=%.12s", key)
            return None, key

        failure_count = entry.get("failure_count", 0)
        if failure_count >= self.bypass_threshold:
            self._backend.delete(key)
            self._stats["evictions"] += 1
            self._stats["misses"] += 1
            logger.debug(
                "cache evict on read (failure_count=%d >= threshold=%d): key=%.12s",
                failure_count,
                self.bypass_threshold,
                key,
            )
            return None, key

        self._stats["hits"] += 1
        logger.debug("cache hit (failure_count=%d): key=%.12s", failure_count, key)
        return entry["response"], key

    def set(
        self,
        key: str,
        response: str,
        model: str,
        *,
        ttl: int | None = None,
        is_action_call: bool = False,
    ) -> bool:
        """Write response to cache after passing success gate.

        Returns True if the response was cached, False if rejected by the gate.
        """
        if not self.enabled:
            return False

        if not self._is_cacheable(response):
            logger.debug("cache write rejected (gate failed): key=%.12s", key)
            return False

        effective_ttl = ttl if ttl is not None else (
            self.action_ttl if is_action_call else self.default_ttl
        )
        entry = {
            "response": response,
            "model": model,
            "cached_at": time.time(),
            "prompt_hash": key,
            "failure_count": 0,
            "schema_version": self.schema_version,
        }
        self._backend.set(key, entry, effective_ttl)
        logger.debug("cache write (ttl=%ds): key=%.12s", effective_ttl, key)
        return True

    def report_failure(self, key: str) -> None:
        """Signal that a cached response caused a downstream failure.

        Increments failure_count.  Evicts the entry if failure_count reaches
        bypass_threshold so the next call hits the live API.
        """
        if not self.enabled:
            return

        entry = self._backend.get(key)
        if entry is None:
            return

        entry["failure_count"] = entry.get("failure_count", 0) + 1
        logger.debug(
            "cache report_failure: failure_count → %d: key=%.12s",
            entry["failure_count"],
            key,
        )

        if entry["failure_count"] >= self.bypass_threshold:
            self._backend.delete(key)
            self._stats["evictions"] += 1
            logger.debug(
                "cache evict after report_failure (count=%d >= threshold=%d): key=%.12s",
                entry["failure_count"],
                self.bypass_threshold,
                key,
            )
        else:
            self._backend.set(key, entry, self.default_ttl)

    def get_stats(self) -> dict:
        """Return cache statistics snapshot."""
        return {
            **self._stats,
            "size_bytes": self._backend.size_bytes(),
            "enabled": self.enabled,
            "bypass_threshold": self.bypass_threshold,
            "default_ttl": self.default_ttl,
        }

    def clear(self) -> None:
        """Evict all entries and reset statistics."""
        self._backend.clear()
        self._stats = {"hits": 0, "misses": 0, "bypasses": 0, "evictions": 0}


# ── Factory helper ─────────────────────────────────────────────────────────────


def make_cache(*, enabled: bool = True, directory: str = DEFAULT_CACHE_DIR) -> SmartCache:
    """Create a SmartCache with the best available backend.

    Falls back to InMemoryCacheBackend if diskcache is not installed.
    Always returns a disabled cache when enabled=False (mock / test mode).
    """
    if not enabled:
        return SmartCache(enabled=False, backend=InMemoryCacheBackend())

    try:
        backend: CacheBackend = DiskCacheBackend(directory=directory)
        logger.debug("SmartCache using DiskCacheBackend at %s", directory)
    except ImportError:
        backend = InMemoryCacheBackend()
        logger.warning(
            "diskcache not installed — SmartCache falling back to in-memory backend. "
            "Install with: pip install diskcache"
        )

    return SmartCache(enabled=True, backend=backend)
