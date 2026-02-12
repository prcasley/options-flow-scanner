"""Async Polygon.io API client with rate limiting."""

import asyncio
import logging
import time
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Polygon REST base
BASE_URL = "https://api.polygon.io"


class RateLimiter:
    """Token-bucket rate limiter for Polygon free tier."""

    def __init__(self, calls_per_minute: int):
        self.calls_per_minute = calls_per_minute
        self.interval = 60.0 / calls_per_minute
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            wait = self._last_call + self.interval - now
            if wait > 0:
                logger.debug("Rate limit: waiting %.1fs", wait)
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


class PolygonClient:
    def __init__(self, api_key: str, rate_limit_cpm: int = 5,
                 max_retries: int = 3, retry_delay: float = 15.0):
        self.api_key = api_key
        self.rate_limiter = RateLimiter(rate_limit_cpm)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, path: str, params: Optional[dict] = None) -> dict:
        """Make a rate-limited GET request with retries."""
        if params is None:
            params = {}
        params["apiKey"] = self.api_key

        url = f"{BASE_URL}{path}"
        session = await self._get_session()

        for attempt in range(1, self.max_retries + 1):
            await self.rate_limiter.acquire()
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 429:
                        logger.warning("Rate limited (429), retry %d/%d",
                                       attempt, self.max_retries)
                        await asyncio.sleep(self.retry_delay)
                        continue
                    text = await resp.text()
                    logger.error("API error %d: %s (attempt %d)",
                                 resp.status, text[:200], attempt)
                    if resp.status >= 500:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    return {}
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.error("Request failed: %s (attempt %d)", e, attempt)
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay)

        logger.error("All retries exhausted for %s", path)
        return {}

    # ── Polygon Endpoints ──

    async def get_options_snapshot(self, underlying: str) -> list[dict]:
        """Get all options contracts snapshot for a ticker.
        Uses: GET /v3/snapshot/options/{underlyingAsset}
        """
        all_results = []
        path = f"/v3/snapshot/options/{underlying}"
        params = {"limit": 250}

        data = await self._request(path, params)
        all_results.extend(data.get("results", []))

        # Paginate if there's a next_url (respect rate limits)
        next_url = data.get("next_url")
        while next_url:
            await self.rate_limiter.acquire()
            session = await self._get_session()
            try:
                sep = "&" if "?" in next_url else "?"
                full_url = f"{next_url}{sep}apiKey={self.api_key}"
                async with session.get(full_url) as resp:
                    if resp.status == 200:
                        page = await resp.json()
                        all_results.extend(page.get("results", []))
                        next_url = page.get("next_url")
                    else:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                break

        return all_results

    async def get_gainers_losers(self, direction: str = "gainers") -> list[dict]:
        """Get top stock gainers/losers for discovery mode.
        Uses: GET /v2/snapshot/locale/us/markets/stocks/{direction}
        """
        data = await self._request(
            f"/v2/snapshot/locale/us/markets/stocks/{direction}"
        )
        return data.get("tickers", [])

    async def get_most_active(self) -> list[str]:
        """Get most active tickers from gainers + losers."""
        gainers = await self.get_gainers_losers("gainers")
        losers = await self.get_gainers_losers("losers")
        tickers = set()
        for item in gainers + losers:
            t = item.get("ticker", "")
            if t:
                tickers.add(t)
        return list(tickers)

    async def get_previous_close(self, ticker: str) -> dict:
        """Get previous day's data for a ticker.
        Uses: GET /v2/aggs/ticker/{ticker}/prev
        """
        data = await self._request(f"/v2/aggs/ticker/{ticker}/prev")
        results = data.get("results", [])
        return results[0] if results else {}

    async def get_options_chain(self, underlying: str,
                                 expiry_gte: Optional[str] = None,
                                 expiry_lte: Optional[str] = None,
                                 contract_type: Optional[str] = None) -> list[dict]:
        """Get options contracts reference data.
        Uses: GET /v3/reference/options/contracts
        """
        params: dict[str, Any] = {
            "underlying_ticker": underlying,
            "limit": 250,
        }
        if expiry_gte:
            params["expiration_date.gte"] = expiry_gte
        if expiry_lte:
            params["expiration_date.lte"] = expiry_lte
        if contract_type:
            params["contract_type"] = contract_type

        data = await self._request("/v3/reference/options/contracts", params)
        return data.get("results", [])
