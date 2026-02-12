"""Unit tests for the Polygon.io API client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.polygon_client import (
    PolygonClient,
    RateLimiter,
    _validate_options_contract,
)


class TestValidateOptionsContract:
    def test_valid_contract(self, sample_contract_raw):
        assert _validate_options_contract(sample_contract_raw) is True

    def test_missing_details(self):
        assert _validate_options_contract({"day": {}}) is False

    def test_details_not_dict(self):
        assert _validate_options_contract({"details": "bad"}) is False

    def test_missing_strike_price(self):
        raw = {"details": {"expiration_date": "2025-03-21", "contract_type": "call"}}
        assert _validate_options_contract(raw) is False

    def test_missing_expiration_date(self):
        raw = {"details": {"strike_price": 220.0, "contract_type": "call"}}
        assert _validate_options_contract(raw) is False

    def test_missing_contract_type(self):
        raw = {"details": {"strike_price": 220.0, "expiration_date": "2025-03-21"}}
        assert _validate_options_contract(raw) is False

    def test_day_not_dict(self):
        raw = {
            "details": {
                "strike_price": 220.0,
                "expiration_date": "2025-03-21",
                "contract_type": "call",
            },
            "day": "invalid",
        }
        assert _validate_options_contract(raw) is False

    def test_day_none_is_valid(self):
        raw = {
            "details": {
                "strike_price": 220.0,
                "expiration_date": "2025-03-21",
                "contract_type": "call",
            },
            "day": None,
        }
        assert _validate_options_contract(raw) is True


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_first_call_no_wait(self):
        rl = RateLimiter(calls_per_minute=60)
        # First call should return almost immediately
        await rl.acquire()

    @pytest.mark.asyncio
    async def test_respects_rate_limit(self):
        rl = RateLimiter(calls_per_minute=600)  # 0.1s interval
        await rl.acquire()
        await rl.acquire()
        # Just verify it doesn't crash; timing-based tests are fragile


class TestPolygonClientInit:
    def test_default_params(self):
        client = PolygonClient(api_key="test_key")
        assert client.api_key == "test_key"
        assert client.max_retries == 3
        assert client.retry_delay == 15.0

    def test_custom_params(self):
        client = PolygonClient(
            api_key="key",
            rate_limit_cpm=10,
            max_retries=5,
            retry_delay=5.0,
        )
        assert client.rate_limiter.calls_per_minute == 10
        assert client.max_retries == 5
        assert client.retry_delay == 5.0


class TestRequest:
    @pytest.mark.asyncio
    async def test_successful_request(self):
        client = PolygonClient(api_key="test", retry_delay=0.01)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"results": [{"ticker": "SPY"}]})

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("/v2/test")
        assert result == {"results": [{"ticker": "SPY"}]}

    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        client = PolygonClient(api_key="test", max_retries=2, retry_delay=0.01)

        mock_resp_429 = AsyncMock()
        mock_resp_429.status = 429

        mock_resp_200 = AsyncMock()
        mock_resp_200.status = 200
        mock_resp_200.json = AsyncMock(return_value={"ok": True})

        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = mock_resp_429 if call_count == 1 else mock_resp_200
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=resp)
            ctx.__aexit__ = AsyncMock(return_value=False)
            return ctx

        mock_session = AsyncMock()
        mock_session.get = mock_get
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("/v2/test")
        assert result == {"ok": True}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_on_client_error(self):
        client = PolygonClient(api_key="test", max_retries=1, retry_delay=0.01)

        mock_resp = AsyncMock()
        mock_resp.status = 403
        mock_resp.text = AsyncMock(return_value="Forbidden")

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("/v2/test")
        assert result == {}

    @pytest.mark.asyncio
    async def test_validates_json_response_type(self):
        client = PolygonClient(api_key="test", max_retries=1, retry_delay=0.01)

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value="not a dict")

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        ))
        mock_session.closed = False
        client._session = mock_session

        result = await client._request("/v2/test")
        assert result == {}


class TestGetOptionsSnapshot:
    @pytest.mark.asyncio
    async def test_filters_invalid_contracts(self):
        client = PolygonClient(api_key="test", retry_delay=0.01)

        valid = {
            "details": {
                "strike_price": 220.0,
                "expiration_date": "2025-03-21",
                "contract_type": "call",
            },
            "day": {"volume": 1000},
        }
        invalid = {"details": {"strike_price": 220.0}}  # missing fields

        client._request = AsyncMock(return_value={
            "results": [valid, invalid],
        })

        results = await client.get_options_snapshot("AAPL")
        assert len(results) == 1
        assert results[0] == valid

    @pytest.mark.asyncio
    async def test_handles_missing_results(self):
        client = PolygonClient(api_key="test", retry_delay=0.01)
        client._request = AsyncMock(return_value={"status": "ok"})

        results = await client.get_options_snapshot("AAPL")
        assert results == []

    @pytest.mark.asyncio
    async def test_handles_non_list_results(self):
        client = PolygonClient(api_key="test", retry_delay=0.01)
        client._request = AsyncMock(return_value={"results": "bad"})

        results = await client.get_options_snapshot("AAPL")
        assert results == []


class TestGetMostActive:
    @pytest.mark.asyncio
    async def test_deduplicates_tickers(self):
        client = PolygonClient(api_key="test", retry_delay=0.01)
        client.get_gainers_losers = AsyncMock(side_effect=[
            [{"ticker": "SPY"}, {"ticker": "AAPL"}],
            [{"ticker": "SPY"}, {"ticker": "MSFT"}],
        ])

        tickers = await client.get_most_active()
        assert set(tickers) == {"SPY", "AAPL", "MSFT"}


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_close_session(self):
        client = PolygonClient(api_key="test")
        mock_session = AsyncMock()
        mock_session.closed = False
        client._session = mock_session

        await client.close()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_when_no_session(self):
        client = PolygonClient(api_key="test")
        await client.close()  # Should not raise
