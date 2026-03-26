"""Smart source rotation — picks the best data source automatically.

Selection logic
---------------
1. **Extended hours** (pre/post-market): prefer Schwab if authenticated,
   since Polygon free-tier only covers regular-hours snapshots.
2. **Rate-limit budget**: if Polygon has fewer than ``min_polygon_calls``
   remaining in the current minute window, fall back to YFinance or Schwab.
3. **Freshness / availability**: if a source raises an exception, the manager
   marks it unavailable for ``cooldown_seconds`` and moves to the next one.
4. **Priority order** (regular hours, all sources healthy):
   Polygon → Schwab → YFinance.

The manager exposes the same interface as individual clients so it can be
used as a drop-in replacement anywhere a data source is expected.
"""

import asyncio
import logging
import time
from typing import Optional

from .polygon_client import PolygonClient
from .schwab_client import SchwabClient
from .yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

# How long to avoid a source after it fails (seconds)
_DEFAULT_COOLDOWN = 120


class _SourceState:
    """Tracks availability and call counts for one source."""

    def __init__(self, name: str, cooldown: float = _DEFAULT_COOLDOWN):
        self.name = name
        self.cooldown = cooldown
        self._unavailable_until: float = 0.0
        self._calls_this_minute: int = 0
        self._minute_start: float = time.monotonic()

    @property
    def available(self) -> bool:
        return time.monotonic() >= self._unavailable_until

    def mark_failed(self) -> None:
        self._unavailable_until = time.monotonic() + self.cooldown
        logger.warning(
            "Source '%s' marked unavailable for %.0fs", self.name, self.cooldown
        )

    def mark_ok(self) -> None:
        self._unavailable_until = 0.0

    def increment_calls(self) -> int:
        """Track calls per minute; resets counter each minute."""
        now = time.monotonic()
        if now - self._minute_start >= 60:
            self._calls_this_minute = 0
            self._minute_start = now
        self._calls_this_minute += 1
        return self._calls_this_minute


class SourceManager:
    """Intelligently routes data requests across Polygon, Schwab, and YFinance.

    Args:
        polygon: Configured PolygonClient instance (required).
        schwab: Optional SchwabClient — used for extended hours and as
                a high-quality fallback.
        yfinance: Optional YFinanceClient — used as last-resort fallback.
        polygon_rate_limit_cpm: Polygon calls-per-minute cap (free tier = 5).
        min_polygon_calls_remaining: Switch away from Polygon when fewer than
            this many calls are left in the current minute window.
        cooldown_seconds: Seconds to avoid a source after it errors.
    """

    def __init__(
        self,
        polygon: PolygonClient,
        schwab: Optional[SchwabClient] = None,
        yfinance: Optional[YFinanceClient] = None,
        polygon_rate_limit_cpm: int = 5,
        min_polygon_calls_remaining: int = 1,
        cooldown_seconds: float = _DEFAULT_COOLDOWN,
    ):
        self.polygon = polygon
        self.schwab = schwab
        self.yfinance = yfinance
        self._polygon_cpm = polygon_rate_limit_cpm
        self._min_polygon_remaining = min_polygon_calls_remaining

        self._states = {
            "polygon": _SourceState("polygon", cooldown_seconds),
        }
        if schwab:
            self._states["schwab"] = _SourceState("schwab", cooldown_seconds)
        if yfinance:
            self._states["yfinance"] = _SourceState("yfinance", cooldown_seconds)

    @property
    def name(self) -> str:
        return "source_manager"

    # ── Source selection ──

    def _polygon_calls_remaining(self) -> int:
        state = self._states["polygon"]
        state.increment_calls()
        used = state._calls_this_minute
        return max(0, self._polygon_cpm - used)

    def _select_source(self, extended_hours: bool) -> Optional[str]:
        """Return the name of the best available source for the current moment."""
        polygon_ok = self._states["polygon"].available
        schwab_ok = "schwab" in self._states and self._states["schwab"].available
        yfinance_ok = "yfinance" in self._states and self._states["yfinance"].available

        # Extended hours: prefer Schwab if it's healthy
        if extended_hours and schwab_ok:
            return "schwab"

        # Regular hours: use Polygon unless rate-limited
        remaining = self._polygon_calls_remaining()
        if polygon_ok and remaining >= self._min_polygon_remaining:
            return "polygon"

        # Polygon rate-limited — fall back
        if schwab_ok:
            logger.info(
                "Polygon rate-limited (%d calls remaining) — switching to Schwab",
                remaining,
            )
            return "schwab"

        if yfinance_ok:
            logger.info(
                "Polygon rate-limited (%d calls remaining) — switching to YFinance",
                remaining,
            )
            return "yfinance"

        # Try Polygon anyway if all else fails
        if polygon_ok:
            return "polygon"

        logger.error("No data sources currently available!")
        return None

    def _client(self, source_name: str):
        mapping = {
            "polygon": self.polygon,
            "schwab": self.schwab,
            "yfinance": self.yfinance,
        }
        return mapping.get(source_name)

    # ── Public interface ──

    async def get_options_snapshot(self, underlying: str) -> list[dict]:
        """Fetch options snapshot using the best available source."""
        from .schwab_client import SchwabClient as _SC  # avoid circular at module level

        is_extended = _SC.is_extended_hours()
        source_name = self._select_source(is_extended)
        if not source_name:
            return []

        client = self._client(source_name)
        state = self._states[source_name]

        try:
            logger.debug("Fetching %s options via '%s'", underlying, source_name)
            results = await client.get_options_snapshot(underlying)
            state.mark_ok()
            return results
        except Exception as e:
            logger.error("Source '%s' failed for %s: %s", source_name, underlying, e)
            state.mark_failed()

            # Attempt fallback immediately
            fallback = self._select_source(is_extended)
            if fallback and fallback != source_name:
                client2 = self._client(fallback)
                try:
                    logger.info(
                        "Retrying %s with fallback source '%s'", underlying, fallback
                    )
                    results = await client2.get_options_snapshot(underlying)
                    self._states[fallback].mark_ok()
                    return results
                except Exception as e2:
                    logger.error("Fallback '%s' also failed: %s", fallback, e2)
                    self._states[fallback].mark_failed()
            return []

    async def get_most_active(self) -> list[str]:
        """Return most-active tickers from the primary available source."""
        for source_name in ("polygon", "schwab", "yfinance"):
            if source_name not in self._states:
                continue
            if not self._states[source_name].available:
                continue
            client = self._client(source_name)
            try:
                tickers = await client.get_most_active()
                self._states[source_name].mark_ok()
                return tickers
            except Exception as e:
                logger.error("get_most_active failed on '%s': %s", source_name, e)
                self._states[source_name].mark_failed()
        return []

    def source_status(self) -> dict[str, bool]:
        """Return availability status for all registered sources."""
        return {name: state.available for name, state in self._states.items()}

    async def close(self):
        """Close all managed client sessions."""
        tasks = [self.polygon.close()]
        if self.schwab:
            tasks.append(self.schwab.close())
        if self.yfinance:
            tasks.append(self.yfinance.close())
        await asyncio.gather(*tasks, return_exceptions=True)
