"""
Cache Layer — Redis-backed with in-memory TTLCache fallback.

Architecture:
  Primary:  Redis (async via redis-py v5) — survives restarts, shared across
            all workers, TTL eviction handled server-side.
  Fallback: cachetools.TTLCache (in-memory) — used when Redis is unavailable
            or disabled. Transparent to callers; the app never crashes because
            the cache is down.

Lifecycle:
  Call ``await init_cache(redis_url, ttl)`` once at startup (in main.py lifespan)
  to connect to Redis. Call ``await close_cache()`` on shutdown.
  If init_cache is never called (e.g. in tests), the in-memory fallback is used
  automatically.

Usage (in retrievers):
  cached = await get_cached(key)
  await set_cached(key, value)

Key hashing:
  Raw claim/query strings can be arbitrarily long and may contain characters
  that are problematic in Redis key namespaces. cache.py enforces SHA-256
  hashing of every key internally — callers just pass plain strings.

Concurrency safety:
  The in-memory TTLCache is NOT thread-safe or coroutine-safe. An asyncio.Lock
  serialises all reads and writes to the fallback cache so two concurrent
  coroutines can never race on the same key.
  Redis is safe by design — each awaited call is atomic from the event loop's
  perspective.

All values are serialised as JSON so Redis stores human-readable strings and
any Python dict / list / primitive can be round-tripped safely.
"""

import json
import hashlib
import threading
from asyncio import Lock as AsyncLock
from typing import Any, Optional
from cachetools import TTLCache
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── In-memory fallback ────────────────────────────────────────────────────────
# Keeps the app functional if Redis is unreachable.
# 1000 items max, 1-hour TTL (matches original behaviour).
_fallback_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)

# asyncio.Lock serialises concurrent coroutine access to the TTLCache.
# One lock instance per module — shared across all callers in the same process.
_fallback_lock: AsyncLock = AsyncLock()

# ── Redis state ───────────────────────────────────────────────────────────────
_redis_client: Optional[Any] = None   # redis.asyncio.Redis instance
_cache_ttl: int = 3600                # Default TTL in seconds


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hash_key(raw_key: str) -> str:
    """
    SHA-256 hash a raw key string to a fixed-length, safe Redis key.

    This prevents:
    - Oversized keys from long claim/query strings
    - Special characters (spaces, colons, newlines) causing Redis key issues
    - Information leakage of raw claim text in Redis keyspace

    The prefix (up to the first ':') is preserved so keys remain identifiable
    in redis-cli inspection (e.g. ``wiki:<hash>``, ``serp:<hash>``).

    Args:
        raw_key: The raw cache key passed by the caller, e.g. ``wiki_SpaceX...``

    Returns:
        A normalised key like ``wiki:a3f9c1...`` (64 hex chars after the colon).
    """
    # Separate an optional prefix (everything before the first underscore)
    # e.g. "wiki_SpaceX Falcon 9" → prefix="wiki", body="SpaceX Falcon 9"
    parts = raw_key.split("_", 1)
    prefix = parts[0] if len(parts) > 1 else "cache"
    body = parts[1] if len(parts) > 1 else raw_key

    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


# ── Lifecycle helpers (called from main.py lifespan) ─────────────────────────

async def init_cache(redis_url: str, ttl_seconds: int = 3600) -> None:
    """
    Connect to Redis and configure the cache TTL.

    Falls back silently to the in-memory TTLCache if the connection fails —
    the application continues to work, just without cross-process caching.

    Args:
        redis_url:    Redis connection URL, e.g. ``redis://redis:6379/0``.
        ttl_seconds:  Default TTL for every cached entry (seconds).
    """
    global _redis_client, _cache_ttl, _fallback_cache, _fallback_lock

    _cache_ttl = ttl_seconds
    # Re-create the fallback with the configured TTL and a fresh asyncio.Lock
    _fallback_cache = TTLCache(maxsize=1000, ttl=ttl_seconds)
    _fallback_lock = AsyncLock()

    try:
        import redis.asyncio as aioredis  # noqa: PLC0415 — lazy import

        client = aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,   # All responses come back as str
            socket_connect_timeout=3,
            socket_timeout=3,
            retry_on_timeout=False,
        )
        # Validate the connection is actually reachable
        await client.ping()
        _redis_client = client
        logger.info(f"Redis cache connected: {redis_url} (TTL={ttl_seconds}s)")

    except Exception as exc:
        _redis_client = None
        logger.warning(
            f"Redis unavailable ({exc}) — falling back to in-memory TTLCache. "
            f"Cache will not persist across restarts."
        )


async def close_cache() -> None:
    """
    Close the Redis connection pool. Call on application shutdown.
    Safe to call even if Redis was never connected.
    """
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("Redis cache connection closed")
        except Exception as exc:
            logger.warning(f"Error closing Redis connection: {exc}")
        finally:
            _redis_client = None


# ── Public cache API ──────────────────────────────────────────────────────────

async def get_cached(key: str) -> Any | None:
    """
    Retrieve a value from cache (Redis primary, in-memory fallback).

    The raw key is SHA-256 hashed internally before any lookup. Callers
    can pass long, raw strings without worrying about key length or
    special characters.

    Returns the deserialised Python object, or None on cache miss / error.

    Args:
        key: Raw cache key string (will be hashed internally).

    Returns:
        Cached value or None.
    """
    hashed = _hash_key(key)

    if _redis_client is not None:
        try:
            raw = await _redis_client.get(hashed)
            if raw is not None:
                logger.debug(f"Redis cache HIT: {hashed}")
                return json.loads(raw)
            logger.debug(f"Redis cache MISS: {hashed}")
            return None
        except Exception as exc:
            logger.warning(
                f"Redis GET failed for key '{hashed}': {exc} — trying fallback"
            )
            # Fall through to in-memory fallback on Redis error

    # In-memory fallback — Lock protects against concurrent coroutine races
    async with _fallback_lock:
        value = _fallback_cache.get(hashed)
    if value is not None:
        logger.debug(f"In-memory cache HIT: {hashed}")
    return value


async def set_cached(key: str, value: Any, ttl: Optional[int] = None) -> None:
    """
    Store a value in cache with TTL eviction (Redis primary, in-memory fallback).

    The raw key is SHA-256 hashed internally before writing. Values are
    JSON-serialised before storing in Redis so they survive as readable strings.

    Args:
        key:   Raw cache key string (will be hashed internally).
        value: Python object to cache (must be JSON-serialisable).
        ttl:   Override TTL in seconds. Defaults to the configured cache TTL.
    """
    hashed = _hash_key(key)
    effective_ttl = ttl if ttl is not None else _cache_ttl

    if _redis_client is not None:
        try:
            serialised = json.dumps(value)
            await _redis_client.setex(hashed, effective_ttl, serialised)
            logger.debug(f"Redis cache SET: {hashed} (TTL={effective_ttl}s)")
            return
        except Exception as exc:
            logger.warning(
                f"Redis SET failed for key '{hashed}': {exc} — writing to fallback"
            )
            # Fall through to in-memory fallback on Redis error

    # In-memory fallback — Lock protects against concurrent coroutine races
    async with _fallback_lock:
        _fallback_cache[hashed] = value
    logger.debug(f"In-memory cache SET: {hashed}")
