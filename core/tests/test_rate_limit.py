import pytest

from app.rate_limit import BandwidthRateLimiter, SlidingWindowRateLimiter


def test_rate_limit_window() -> None:
    limiter = SlidingWindowRateLimiter()

    assert limiter.allow("visitor", 2)
    assert limiter.allow("visitor", 2)
    assert not limiter.allow("visitor", 2)
    assert limiter.allow("other", 2)


@pytest.mark.asyncio
async def test_bandwidth_limiter_shares_a_user_bucket() -> None:
    current = [0.0]
    delays: list[float] = []

    def clock() -> float:
        return current[0]

    async def sleep(delay: float) -> None:
        delays.append(delay)
        current[0] += delay

    limiter = BandwidthRateLimiter(
        100,
        burst_seconds=2,
        clock=clock,
        sleep=sleep,
    )

    await limiter.consume("user-1", 150)
    await limiter.consume("user-1", 100)

    assert delays == [pytest.approx(0.5)]
