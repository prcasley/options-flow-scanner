"""Tests for scanner/polygon_client.py — rate limiter and API client."""

import asyncio
import time

import pytest

from scanner.polygon_client import RateLimiter, PolygonClient


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_first_call_no_wait(self):
        """First call should go through immediately."""
        rl = RateLimiter(calls_per_minute=60)  # 1 per second
        start = time.monotonic()
        await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should be nearly instant

    @pytest.mark.asyncio
    async def test_rate_limiting_enforced(self):
        """Second call should wait the rate limit interval."""
        rl = RateLimiter(calls_per_minute=60)  # 1 per second interval
        await rl.acquire()

        start = time.monotonic()
        await rl.acquire()
        elapsed = time.monotonic() - start
        # Should have waited ~1 second
        assert elapsed >= 0.9

    @pytest.mark.asyncio
    async def test_interval_calculation(self):
        """5 calls/min should mean 12-second interval."""
        rl = RateLimiter(calls_per_minute=5)
        assert rl.interval == 12.0

    @pytest.mark.asyncio
    async def test_high_rate_limit(self):
        """High rate limit should allow rapid calls."""
        rl = RateLimiter(calls_per_minute=6000)  # 100/sec
        start = time.monotonic()
        for _ in range(5):
            await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.5  # Should be fast


class TestPolygonClientInit:
    def test_default_params(self):
        """Should initialize with default parameters."""
        client = PolygonClient(api_key="test_key")
        assert client.api_key == "test_key"
        assert client.max_retries == 3
        assert client.retry_delay == 15.0
        assert client._session is None

    def test_custom_params(self):
        """Should accept custom parameters."""
        client = PolygonClient(
            api_key="key",
            rate_limit_cpm=10,
            max_retries=5,
            retry_delay=30.0,
        )
        assert client.max_retries == 5
        assert client.retry_delay == 30.0
        assert client.rate_limiter.calls_per_minute == 10

    @pytest.mark.asyncio
    async def test_close_without_session(self):
        """Close should handle no active session gracefully."""
        client = PolygonClient(api_key="test")
        await client.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_session_creation(self):
        """Session should be created lazily on first request."""
        client = PolygonClient(api_key="test")
        assert client._session is None
        session = await client._get_session()
        assert session is not None
        assert not session.closed
        await client.close()
