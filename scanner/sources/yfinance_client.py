"""Yahoo Finance data source client using yfinance.

Provides options chain data as a fallback or supplement to Polygon.
No API key required — uses Yahoo Finance public data.
Rate limit: be courteous; ~10 req/min recommended.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _to_polygon_snapshot(ticker: str, row, expiry: str, contract_type: str) -> dict:
    """Convert a yfinance options row to Polygon-compatible snapshot dict."""
    volume = int(row.get("volume", 0) or 0)
    oi = int(row.get("openInterest", 0) or 0)
    last_price = float(row.get("lastPrice", 0) or 0)
    iv = row.get("impliedVolatility")
    strike = float(row.get("strike", 0) or 0)
    return {
        "details": {
            "strike_price": strike,
            "expiration_date": expiry,
            "contract_type": contract_type,
        },
        "day": {
            "volume": volume,
            "close": last_price,
        },
        "open_interest": oi,
        "greeks": {"implied_volatility": float(iv) if iv is not None else None},
    }


class YFinanceClient:
    """Options data client backed by Yahoo Finance (yfinance library).

    This client is suitable as a fallback when Polygon rate limits are hit,
    or for after-hours data where Polygon free-tier data is limited.
    """

    def __init__(self, rate_limit_per_minute: int = 10):
        self.rate_limit_per_minute = rate_limit_per_minute

    @property
    def name(self) -> str:
        return "yfinance"

    async def get_options_snapshot(
        self,
        underlying: str,
        expiry: Optional[str] = None,
    ) -> list[dict]:
        """Fetch options chain for *underlying* and convert to Polygon format.

        Args:
            underlying: Ticker symbol (e.g. "AAPL").
            expiry: Optional specific expiry (YYYY-MM-DD). If None, fetches
                    the nearest available expiry.

        Returns:
            List of contract dicts in Polygon snapshot format.
        """
        try:
            import yfinance as yf  # lazy import — optional dependency
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
            return []

        try:
            ticker_obj = yf.Ticker(underlying)
            expiries = ticker_obj.options
            if not expiries:
                logger.warning("No options expiries found for %s", underlying)
                return []

            # Use requested expiry or nearest
            target = expiry if expiry in expiries else expiries[0]
            chain = ticker_obj.option_chain(target)

            results = []
            for _, row in chain.calls.iterrows():
                results.append(_to_polygon_snapshot(underlying, row, target, "call"))
            for _, row in chain.puts.iterrows():
                results.append(_to_polygon_snapshot(underlying, row, target, "put"))

            logger.debug(
                "YFinance: fetched %d contracts for %s (%s)",
                len(results),
                underlying,
                target,
            )
            return results

        except Exception as e:
            logger.error("YFinance error for %s: %s", underlying, e)
            return []

    async def get_most_active(self) -> list[str]:
        """Return a curated list of high-volume tickers for discovery.

        Yahoo Finance does not expose a free most-active API endpoint, so we
        return a static list of highly-liquid underlyings that almost always
        have options activity.  Override by subclassing if you have a better
        source.
        """
        return [
            "SPY",
            "QQQ",
            "IWM",
            "AAPL",
            "MSFT",
            "NVDA",
            "TSLA",
            "AMZN",
            "META",
            "GOOGL",
            "AMD",
            "INTC",
            "NFLX",
            "BABA",
            "GS",
            "JPM",
        ]

    async def get_expiries(self, underlying: str) -> list[str]:
        """Return available expiry dates for *underlying*."""
        try:
            import yfinance as yf

            return list(yf.Ticker(underlying).options)
        except Exception as e:
            logger.error("YFinance expiries error for %s: %s", underlying, e)
            return []

    async def close(self):
        pass  # No persistent session to clean up
