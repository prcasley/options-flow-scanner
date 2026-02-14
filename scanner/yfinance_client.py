"""Yahoo Finance data client — free replacement for Polygon.io."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceClient:
    """Fetches options data via yfinance (free, no API key needed)."""

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    async def get_options_snapshot(self, ticker: str) -> list[dict]:
        """Get options chain for a ticker, formatted like Polygon snapshots."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                self._executor, self._fetch_options_sync, ticker
            )
            return result
        except Exception as e:
            logger.error("Error fetching %s options: %s", ticker, e)
            return []

    def _fetch_options_sync(self, ticker: str) -> list[dict]:
        """Synchronous fetch — runs in thread pool."""
        tk = yf.Ticker(ticker)

        try:
            expirations = tk.options
        except Exception as e:
            logger.warning("%s: no options available (%s)", ticker, e)
            return []

        if not expirations:
            logger.debug("%s: no expirations found", ticker)
            return []

        contracts = []
        # Scan first 4 expirations to keep it fast
        for exp in expirations[:4]:
            try:
                chain = tk.option_chain(exp)
            except Exception as e:
                logger.debug("%s exp %s: chain fetch failed: %s", ticker, exp, e)
                continue

            for _, row in chain.calls.iterrows():
                snap = self._row_to_snapshot(ticker, row, exp, "call")
                if snap:
                    contracts.append(snap)

            for _, row in chain.puts.iterrows():
                snap = self._row_to_snapshot(ticker, row, exp, "put")
                if snap:
                    contracts.append(snap)

        logger.debug("%s: fetched %d contracts", ticker, len(contracts))
        return contracts

    def _row_to_snapshot(self, ticker: str, row, expiry: str,
                         contract_type: str) -> Optional[dict]:
        """Convert a yfinance DataFrame row to Polygon-style snapshot dict."""
        try:
            volume = int(row.get("volume", 0) or 0)
            oi = int(row.get("openInterest", 0) or 0)
            last_price = float(row.get("lastPrice", 0) or 0)
            strike = float(row.get("strike", 0) or 0)
            iv = float(row.get("impliedVolatility", 0) or 0)

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
                "greeks": {
                    "implied_volatility": iv,
                },
                "open_interest": oi,
            }
        except Exception as e:
            logger.debug("Row conversion error: %s", e)
            return None

    async def get_most_active(self) -> list[str]:
        """Return curated list of high-volume options tickers."""
        return [
            "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA",
            "AMZN", "META", "GOOGL", "AMD", "AVGO", "NFLX", "JPM",
            "BAC", "XLF", "GLD", "SLV", "TLT", "COIN", "MARA",
            "PLTR", "SOFI", "RIVN", "ARM", "SMCI", "MU", "INTC",
        ]

    async def close(self):
        """Cleanup."""
        self._executor.shutdown(wait=False)
