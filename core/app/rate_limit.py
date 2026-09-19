from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > window_seconds:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True


class BandwidthRateLimiter:
    """Shared token bucket for limiting aggregate bytes per user."""

    def __init__(
        self,
        bytes_per_second: float,
        burst_seconds: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.bytes_per_second = max(1.0, float(bytes_per_second))
        self.burst_bytes = max(
            1.0,
            self.bytes_per_second * max(0.0, float(burst_seconds)),
        )
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}

    async def consume(self, key: str, amount: int) -> None:
        remaining = max(0, int(amount))
        if remaining == 0:
            return

        while remaining > 0:
            delay = 0.0
            async with self._lock:
                now = self._clock()
                tokens, updated_at = self._buckets.get(
                    key, (self.burst_bytes, now)
                )
                tokens = min(
                    self.burst_bytes,
                    tokens + max(0.0, now - updated_at) * self.bytes_per_second,
                )
                granted = min(float(remaining), tokens)
                if granted >= 1:
                    granted_bytes = int(granted)
                    remaining -= granted_bytes
                    tokens -= granted_bytes
                    self._buckets[key] = (tokens, now)
                    continue

                needed = min(float(remaining), self.burst_bytes) - tokens
                delay = max(0.001, needed / self.bytes_per_second)
                self._buckets[key] = (tokens, now)

            await self._sleep(delay)
