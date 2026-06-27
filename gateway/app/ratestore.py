"""Shared store for rate-limit counters and replay nonces.

Uses Redis when ``SAT_REDIS_URL`` is set so limits/replay protection hold across
gateway replicas. The Redis connection is established **lazily and re-established
on failure** — so if Redis isn't ready when a replica boots (or briefly drops),
the replica falls back to in-process for those calls and automatically returns to
Redis once it's reachable (rather than degrading to in-memory forever).
"""
from __future__ import annotations

import time
from collections import OrderedDict, defaultdict, deque

from .config import get_settings

settings = get_settings()

try:  # redis is optional at import time
    import redis as _redis_lib
except Exception:  # pragma: no cover
    _redis_lib = None


class _Memory:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._nonces: "OrderedDict[str, float]" = OrderedDict()

    def allow(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def seen_nonce(self, nonce: str, ttl: float) -> bool:
        now = time.time()
        while self._nonces and next(iter(self._nonces.values())) < now - ttl:
            self._nonces.popitem(last=False)
        if nonce in self._nonces:
            return True
        self._nonces[nonce] = now
        if len(self._nonces) > 100_000:
            self._nonces.popitem(last=False)
        return False


class Store:
    """Redis-first with automatic reconnect and an in-process fallback."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._mem = _Memory()
        self._client = None
        self._next_try = 0.0

    def _redis(self):
        if not self._url or _redis_lib is None:
            return None
        if self._client is not None:
            return self._client
        now = time.monotonic()
        if now < self._next_try:          # back off between reconnect attempts
            return None
        try:
            client = _redis_lib.from_url(self._url, socket_timeout=1, socket_connect_timeout=1)
            client.ping()
            self._client = client
            return client
        except Exception:
            self._next_try = now + 5.0    # retry at most every 5s
            return None

    def _drop(self) -> None:
        self._client = None
        self._next_try = time.monotonic() + 5.0

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        r = self._redis()
        if r is None:
            return self._mem.allow(key, limit, window)
        rkey = f"sat:rl:{key}:{int(time.time() // window)}"
        try:
            n = r.incr(rkey)
            if n == 1:
                r.expire(rkey, int(window) + 1)
            return n <= limit
        except Exception:
            self._drop()
            return self._mem.allow(key, limit, window)

    def seen_nonce(self, nonce: str, ttl: float) -> bool:
        r = self._redis()
        if r is None:
            return self._mem.seen_nonce(nonce, ttl)
        try:
            ok = r.set(f"sat:nonce:{nonce}", "1", nx=True, ex=int(ttl) + 1)
            return not ok
        except Exception:
            self._drop()
            return self._mem.seen_nonce(nonce, ttl)


store = Store(settings.redis_url)
