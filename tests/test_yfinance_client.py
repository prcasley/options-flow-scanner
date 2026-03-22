"""Unit tests for the YFinance data source client."""

from unittest.mock import MagicMock, patch

import pytest

from scanner.sources.yfinance_client import YFinanceClient, _to_polygon_snapshot


class TestToPolygonSnapshot:
    def test_basic_conversion(self):
        row = {
            "volume": 1000,
            "openInterest": 500,
            "lastPrice": 2.5,
            "impliedVolatility": 0.4,
            "strike": 150.0,
        }
        result = _to_polygon_snapshot("AAPL", row, "2025-06-20", "call")
        assert result["details"]["strike_price"] == 150.0
        assert result["details"]["expiration_date"] == "2025-06-20"
        assert result["details"]["contract_type"] == "call"
        assert result["day"]["volume"] == 1000
        assert result["day"]["close"] == 2.5
        assert result["open_interest"] == 500
        assert result["greeks"]["implied_volatility"] == pytest.approx(0.4)

    def test_none_values_handled(self):
        row = {
            "volume": None,
            "openInterest": None,
            "lastPrice": None,
            "impliedVolatility": None,
            "strike": 100.0,
        }
        result = _to_polygon_snapshot("SPY", row, "2025-03-21", "put")
        assert result["day"]["volume"] == 0
        assert result["open_interest"] == 0
        assert result["day"]["close"] == 0.0
        assert result["greeks"]["implied_volatility"] is None


class TestYFinanceClient:
    def test_name(self):
        client = YFinanceClient()
        assert client.name == "yfinance"

    @pytest.mark.asyncio
    async def test_get_most_active_returns_list(self):
        client = YFinanceClient()
        tickers = await client.get_most_active()
        assert isinstance(tickers, list)
        assert len(tickers) > 0
        assert "SPY" in tickers

    @pytest.mark.asyncio
    async def test_get_options_snapshot_no_yfinance(self):
        """If yfinance is not installed, should return empty list gracefully."""
        client = YFinanceClient()
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = await client.get_options_snapshot("AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_options_snapshot_yfinance_error(self):
        """Exceptions from yfinance should be caught and return empty list."""
        client = YFinanceClient()
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = Exception("network error")
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = await client.get_options_snapshot("AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_options_snapshot_no_expiries(self):
        client = YFinanceClient()
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value.options = []
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = await client.get_options_snapshot("AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_options_snapshot_returns_contracts(self):
        import pandas as pd

        client = YFinanceClient()

        calls_df = pd.DataFrame(
            [
                {
                    "strike": 150.0,
                    "volume": 500,
                    "openInterest": 1000,
                    "lastPrice": 3.0,
                    "impliedVolatility": 0.3,
                }
            ]
        )
        puts_df = pd.DataFrame(
            [
                {
                    "strike": 140.0,
                    "volume": 200,
                    "openInterest": 800,
                    "lastPrice": 2.0,
                    "impliedVolatility": 0.25,
                }
            ]
        )

        mock_chain = MagicMock()
        mock_chain.calls = calls_df
        mock_chain.puts = puts_df

        mock_ticker = MagicMock()
        mock_ticker.options = ["2025-06-20"]
        mock_ticker.option_chain.return_value = mock_chain

        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = await client.get_options_snapshot("AAPL")

        assert len(result) == 2
        ctypes = {r["details"]["contract_type"] for r in result}
        assert ctypes == {"call", "put"}

    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        client = YFinanceClient()
        await client.close()  # should not raise
