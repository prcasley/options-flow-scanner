"""Main scan loop orchestrator."""

import asyncio
import logging
from datetime import datetime, date

import pytz

from .alerts import AlertManager
from .database import SignalDatabase
from .detector import Detector
from .polygon_client import PolygonClient

logger = logging.getLogger(__name__)

# US market holidays (fixed and observed dates for 2024-2027).
# Update annually or replace with a holiday calendar library.
US_MARKET_HOLIDAYS: set[date] = {
    # 2024
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19),
    date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19),
    date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28),
    date(2024, 12, 25),
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15),
    date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25),
    date(2027, 12, 24),
}


class Scanner:
    def __init__(self, config: dict, polygon: PolygonClient,
                 detector: Detector, alerts: AlertManager,
                 db: SignalDatabase, health=None, dispatcher=None):
        self.config = config
        self.polygon = polygon
        self.detector = detector
        self.alerts = alerts
        self.db = db
        self.health = health
        self.dispatcher = dispatcher
        self._running = False
        self._daily_summary_sent_date: str | None = None  # "YYYY-MM-DD" of last summary
        self._et = pytz.timezone(config.get("market", {}).get("timezone", "US/Eastern"))

    def _now_et(self) -> datetime:
        return datetime.now(self._et)

    def _is_market_hours(self) -> bool:
        now = self._now_et()
        mkt = self.config.get("market", {})
        open_time = now.replace(
            hour=mkt.get("open_hour", 9),
            minute=mkt.get("open_minute", 30),
            second=0, microsecond=0,
        )
        close_time = now.replace(
            hour=mkt.get("close_hour", 16),
            minute=mkt.get("close_minute", 0),
            second=0, microsecond=0,
        )
        # Weekdays only (0=Mon, 4=Fri)
        if now.weekday() > 4:
            return False
        # US market holidays
        if now.date() in US_MARKET_HOLIDAYS:
            return False
        return open_time <= now <= close_time

    async def run(self):
        """Main scan loop."""
        self._running = True
        if self.health:
            self.health.is_running = True
        interval = self.config.get("scan_interval_seconds", 60)
        logger.info("Scanner started. Interval: %ds", interval)

        while self._running:
            try:
                if self._is_market_hours():
                    await self._scan_cycle()
                else:
                    logger.debug("Market closed, waiting...")

                # Check for daily summary time
                await self._check_daily_summary()

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scan cycle error: %s", e, exc_info=True)
                if self.health:
                    self.health.last_error = str(e)
                await asyncio.sleep(interval)

        if self.health:
            self.health.is_running = False
        logger.info("Scanner stopped")

    async def stop(self):
        self._running = False

    async def _scan_cycle(self):
        """One full scan: watchlist + discovery."""
        logger.info("Starting scan cycle...")
        all_signals = []

        # 1. Scan watchlist
        watchlist = self.config.get("watchlist", [])
        for ticker in watchlist:
            if not self._running:
                break
            signals = await self._scan_ticker(ticker)
            all_signals.extend(signals)

        # 2. Discovery mode
        discovery = self.config.get("discovery", {})
        if discovery.get("enabled", True):
            discovered = await self._discover_tickers()
            max_disc = discovery.get("max_tickers", 50)
            # Remove watchlist dupes
            discovered = [t for t in discovered if t not in watchlist][:max_disc]
            for ticker in discovered:
                if not self._running:
                    break
                signals = await self._scan_ticker(ticker)
                all_signals.extend(signals)

        if all_signals:
            # Sort by risk score descending
            all_signals.sort(key=lambda s: (s.risk_score, s.estimated_premium),
                             reverse=True)
            logger.info("Found %d signals this cycle", len(all_signals))
            await self.alerts.send_signals(all_signals)
            if self.dispatcher:
                await self.dispatcher.dispatch_signals(all_signals)
            await self.db.insert_signals(all_signals)
        else:
            logger.info("No signals this cycle")

        # Update health metrics
        if self.health:
            self.health.scan_count += 1
            self.health.signal_count += len(all_signals)
            self.health.last_scan_time = datetime.now()

    async def _scan_ticker(self, ticker: str) -> list:
        """Scan a single ticker's options chain."""
        try:
            contracts = await self.polygon.get_options_snapshot(ticker)
            if not contracts:
                return []
            signals = self.detector.analyze_snapshot(ticker, contracts)
            if signals:
                logger.info("%s: %d signals detected", ticker, len(signals))
            return signals
        except Exception as e:
            logger.error("Error scanning %s: %s", ticker, e)
            return []

    async def _discover_tickers(self) -> list[str]:
        """Find tickers via gainers/losers for broad market scan."""
        try:
            tickers = await self.polygon.get_most_active()
            logger.info("Discovery found %d active tickers", len(tickers))
            return tickers
        except Exception as e:
            logger.error("Discovery error: %s", e)
            return []

    async def _check_daily_summary(self):
        """Send daily summary at configured time."""
        ds = self.config.get("daily_summary", {})
        if not ds.get("enabled", True):
            return

        now = self._now_et()
        target_hour = ds.get("hour", 16)
        target_min = ds.get("minute", 15)
        top_n = ds.get("top_n", 10)

        date_str = now.strftime("%Y-%m-%d")

        # Use date-based tracking: only send once per calendar day
        if (now.hour == target_hour and
                now.minute >= target_min and
                self._daily_summary_sent_date != date_str):
            self._daily_summary_sent_date = date_str
            logger.info("Sending daily summary for %s", date_str)
            try:
                signals = await self.db.get_today_signals(date_str)
                top_signals = signals[:top_n]
                await self.alerts.send_daily_summary(top_signals, date_str)
            except Exception as e:
                logger.error("Daily summary error: %s", e)
