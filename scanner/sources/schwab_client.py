"""Schwab / TD Ameritrade API client for real-time options data.

Authentication flow
-------------------
Schwab uses OAuth 2.0 (Authorization Code grant).  The first time you run
you must:

  1. Call ``SchwabClient.get_auth_url()`` and open the URL in a browser.
  2. Log in with your Schwab brokerage credentials and approve access.
  3. Copy the ``code`` query-parameter from the redirect URL.
  4. Pass that code to ``SchwabClient.exchange_code(code)`` which stores
     tokens in the configured ``token_file`` path.

Subsequent runs auto-refresh the access token from disk.

Free-tier perks over Polygon
-----------------------------
- Real-time quotes during regular and extended (pre/post) market hours.
- Level-2 bid/ask data included in options chain responses.
- No per-call rate limits beyond burst protection (120 req/min recommended).

API reference: https://developer.schwab.com/products/trader-api--individual-
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

# Schwab API base URLs
_AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
_API_BASE = "https://api.schwabapi.com/marketdata/v1"

# Default token file location (relative to CWD)
_DEFAULT_TOKEN_FILE = "data/schwab_tokens.json"

# Recommended burst rate ceiling
_DEFAULT_RATE_LIMIT_CPM = 120


class SchwabAuthError(Exception):
    """Raised when Schwab OAuth flow fails."""


class SchwabClient:
    """Async Schwab/TD Ameritrade API client with OAuth 2.0 and token refresh.

    Supports:
    - Real-time options chains (regular + extended hours)
    - Automatic access-token refresh using the stored refresh token
    - Normalised output matching the Polygon snapshot contract format
      so it slots directly into the existing Detector pipeline

    Usage::

        client = SchwabClient(
            client_id="YOUR_APP_KEY",
            client_secret="YOUR_APP_SECRET",
            redirect_uri="https://127.0.0.1",
        )
        # First run: obtain tokens
        print(client.get_auth_url())
        await client.exchange_code("code_from_redirect")

        # Subsequent runs: tokens are loaded from disk automatically
        contracts = await client.get_options_snapshot("AAPL")
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "https://127.0.0.1",
        token_file: str = _DEFAULT_TOKEN_FILE,
        rate_limit_cpm: int = _DEFAULT_RATE_LIMIT_CPM,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_file = Path(token_file)
        self.rate_limit_cpm = rate_limit_cpm
        self._interval = 60.0 / rate_limit_cpm
        self._last_call = 0.0
        self._lock = asyncio.Lock()

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expiry: float = 0.0  # Unix timestamp

        self._session: Optional[aiohttp.ClientSession] = None
        self._load_tokens()

    @property
    def name(self) -> str:
        return "schwab"

    # ── OAuth helpers ──

    def get_auth_url(self) -> str:
        """Return the Schwab authorization URL for the first-time OAuth flow."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "readonly",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> None:
        """Exchange an authorization code for access + refresh tokens.

        Call this once with the ``code`` obtained from the redirect URL
        after the user approves access in the browser.
        """
        session = await self._get_session()
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        try:
            async with session.post(
                _TOKEN_URL,
                data=payload,
                auth=aiohttp.BasicAuth(self.client_id, self.client_secret),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise SchwabAuthError(
                        f"Token exchange failed {resp.status}: {text}"
                    )
                data = await resp.json()
                self._store_tokens(data)
                logger.info("Schwab: tokens obtained and saved to %s", self.token_file)
        except aiohttp.ClientError as e:
            raise SchwabAuthError(f"Token exchange request failed: {e}") from e

    async def _refresh_access_token(self) -> None:
        """Use the refresh token to obtain a new access token."""
        if not self._refresh_token:
            raise SchwabAuthError(
                "No refresh token available. Run the OAuth flow first via get_auth_url()."
            )
        session = await self._get_session()
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        try:
            async with session.post(
                _TOKEN_URL,
                data=payload,
                auth=aiohttp.BasicAuth(self.client_id, self.client_secret),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise SchwabAuthError(f"Token refresh failed {resp.status}: {text}")
                data = await resp.json()
                self._store_tokens(data)
                logger.debug("Schwab: access token refreshed")
        except aiohttp.ClientError as e:
            raise SchwabAuthError(f"Token refresh request failed: {e}") from e

    def _store_tokens(self, data: dict) -> None:
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        expires_in = int(data.get("expires_in", 1800))
        self._token_expiry = time.time() + expires_in - 60  # 60s safety buffer

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_file, "w") as f:
            json.dump(
                {
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "token_expiry": self._token_expiry,
                },
                f,
                indent=2,
            )

    def _load_tokens(self) -> None:
        if not self.token_file.exists():
            return
        try:
            with open(self.token_file) as f:
                data = json.load(f)
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = float(data.get("token_expiry", 0))
            logger.debug("Schwab: tokens loaded from %s", self.token_file)
        except Exception as e:
            logger.warning(
                "Schwab: could not load tokens from %s: %s", self.token_file, e
            )

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if time.time() >= self._token_expiry:
            await self._refresh_access_token()
        if not self._access_token:
            raise SchwabAuthError(
                "Not authenticated. Call get_auth_url() and exchange_code() first."
            )
        return self._access_token

    # ── Session / rate limiting ──

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def _rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._last_call + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def _request(self, path: str, params: Optional[dict] = None) -> dict:
        """Authenticated GET request to the Schwab marketdata API."""
        token = await self._ensure_token()
        await self._rate_limit()
        session = await self._get_session()
        url = f"{_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with session.get(url, params=params or {}, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, dict) else {}
                if resp.status == 401:
                    logger.warning("Schwab: 401 — refreshing token and retrying")
                    self._token_expiry = 0  # force refresh
                    token = await self._ensure_token()
                    headers["Authorization"] = f"Bearer {token}"
                    async with session.get(
                        url, params=params or {}, headers=headers
                    ) as retry_resp:
                        if retry_resp.status == 200:
                            return await retry_resp.json()
                text = await resp.text()
                logger.error("Schwab API error %d: %s", resp.status, text[:200])
                return {}
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Schwab request failed: %s", e)
            return {}

    # ── Public API ──

    async def get_options_chain(
        self,
        underlying: str,
        contract_type: str = "ALL",
        expiry_date: Optional[str] = None,
        include_extended: bool = True,
    ) -> dict:
        """Fetch the full options chain from Schwab.

        Args:
            underlying: Ticker symbol (e.g. "AAPL").
            contract_type: "CALL", "PUT", or "ALL".
            expiry_date: Optional specific expiry (YYYY-MM-DD).
            include_extended: Whether to include extended-hours quotes.

        Returns:
            Raw Schwab API response dict.
        """
        params: dict = {
            "symbol": underlying,
            "contractType": contract_type.upper(),
            "includeUnderlyingQuote": "true",
            "strategy": "SINGLE",
        }
        if expiry_date:
            params["expirationDate"] = expiry_date
        if include_extended:
            params["optionType"] = "ALL"

        return await self._request("/chains", params)

    async def get_options_snapshot(
        self,
        underlying: str,
        include_extended: bool = True,
    ) -> list[dict]:
        """Fetch Schwab options chain and convert to Polygon snapshot format.

        The output is normalised to the same dict structure used by Polygon so
        the existing Detector pipeline works without modification.

        Args:
            underlying: Ticker symbol.
            include_extended: Include extended-hours quotes (pre/after market).

        Returns:
            List of contract dicts in Polygon snapshot format.
        """
        data = await self.get_options_chain(
            underlying, include_extended=include_extended
        )
        return self._normalise_chain(underlying, data)

    def _normalise_chain(self, underlying: str, data: dict) -> list[dict]:
        """Convert Schwab chain response to Polygon-compatible snapshot list."""
        results = []
        for side, ctype in [("callExpDateMap", "call"), ("putExpDateMap", "put")]:
            expiry_map = data.get(side, {})
            for expiry_key, strikes in expiry_map.items():
                # Schwab expiry key format: "YYYY-MM-DD:DTE"
                expiry = expiry_key.split(":")[0]
                for strike_str, contracts in strikes.items():
                    for contract in contracts:
                        results.append(
                            self._contract_to_snapshot(
                                underlying, expiry, ctype, float(strike_str), contract
                            )
                        )
        return results

    @staticmethod
    def _contract_to_snapshot(
        underlying: str,
        expiry: str,
        contract_type: str,
        strike: float,
        contract: dict,
    ) -> dict:
        """Map a single Schwab contract dict to Polygon snapshot format."""
        volume = int(contract.get("totalVolume", 0) or 0)
        oi = int(contract.get("openInterest", 0) or 0)
        last_price = float(contract.get("last", 0) or 0)
        iv = contract.get("volatility")
        delta = contract.get("delta")
        gamma = contract.get("gamma")
        theta = contract.get("theta")
        vega = contract.get("vega")
        bid = float(contract.get("bid", 0) or 0)
        ask = float(contract.get("ask", 0) or 0)
        return {
            "details": {
                "strike_price": strike,
                "expiration_date": expiry,
                "contract_type": contract_type,
                "underlying_ticker": underlying,
            },
            "day": {
                "volume": volume,
                "close": last_price,
                "open": float(contract.get("openPrice", 0) or 0),
                "high": float(contract.get("highPrice", 0) or 0),
                "low": float(contract.get("lowPrice", 0) or 0),
            },
            "open_interest": oi,
            "greeks": {
                "implied_volatility": float(iv) / 100.0 if iv is not None else None,
                "delta": float(delta) if delta is not None else None,
                "gamma": float(gamma) if gamma is not None else None,
                "theta": float(theta) if theta is not None else None,
                "vega": float(vega) if vega is not None else None,
            },
            "last_quote": {"bid": bid, "ask": ask},
            "source": "schwab",
        }

    async def get_most_active(self) -> list[str]:
        """Return movers from Schwab screener (top 25 by volume)."""
        data = await self._request(
            "/movers/%24SPX",
            {"sort": "VOLUME", "frequency": 1},
        )
        movers = data.get("screenerItems", [])
        return [m["symbol"] for m in movers if "symbol" in m][:25]

    async def get_quote(self, symbol: str) -> dict:
        """Fetch a real-time quote for an underlying or options contract."""
        return await self._request(f"/quotes/{symbol}")

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Extended-hours helpers ──

    @staticmethod
    def is_extended_hours() -> bool:
        """Return True if current ET time is in pre or after-market hours."""
        et_offset = timedelta(hours=-4)  # EDT; adjust for EST in winter if needed
        now_et = datetime.now(timezone.utc).replace(tzinfo=None) + et_offset
        hour = now_et.hour
        minute = now_et.minute
        # Pre-market: 4:00 AM – 9:30 AM ET
        if (4, 0) <= (hour, minute) < (9, 30):
            return True
        # After-market: 4:00 PM – 8:00 PM ET
        if (16, 0) <= (hour, minute) < (20, 0):
            return True
        return False
