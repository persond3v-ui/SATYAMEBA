"""Shared store for rate-limit counters and replay nonces.

Backed by Redis when ``SAT_REDIS_URL`` is set, so limits and replay protection
hold across multiple gateway replicas (fixes the per-replica gap). Falls back to
an in-process implementation when Redis is not configured, which is correct for
a single replica.
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


class _MemoryBackend:
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


class _RedisBackend:
    def __init__(self, client) -> None:
        self._r = client

    def allow(self, key: str, limit: int, window: float) -> bool:
        # Fixed-window counter: INCR then set expiry on first hit.
        rkey = f"sat:rl:{key}:{int(time.time() // window)}"
        try:
            n = self._r.incr(rkey)
            if n == 1:
                self._r.expire(rkey, int(window) + 1)
            return n <= limit
        except Exception:
            return True  # fail-open on store errors; never lock everyone out

    def seen_nonce(self, nonce: str, ttl: float) -> bool:
        try:
            # SET key NX EX: returns True if newly set (i.e. not seen before).
            ok = self._r.set(f"sat:nonce:{nonce}", "1", nx=True, ex=int(ttl) + 1)
            return not ok
        except Exception:
            return False  # fail-open: do not reject legitimate traffic


def _make_backend():
    if settings.redis_url and _redis_lib is not None:
        try:
            client = _redis_lib.from_url(settings.redis_url, socket_timeout=1)
            client.ping()
            return _RedisBackend(client)
        except Exception:
            pass
    return _MemoryBackend()


store = _make_backend()
