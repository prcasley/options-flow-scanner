"""Tests for scanner/scheduler.py — scan loop orchestration."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from scanner.scheduler import Scanner
from scanner.models import Signal


def _make_signal(**overrides) -> Signal:
    defaults = dict(
        timestamp=datetime(2026, 2, 14, 10, 30, 0),
        ticker="SPY",
        strike=600.0,
        expiry="2026-03-21",
        contract_type="call",
        volume=5000,
        open_interest=200,
        estimated_premium=2_500_000,
        risk_score=5,
        signal_types=["volume spike"],
        description="test",
        volume_ratio=10.0,
        oi_ratio=25.0,
        last_price=5.0,
    )
    defaults.update(overrides)
    return Signal(**defaults)


@pytest.fixture
def config():
    return {
        "scan_interval_seconds": 60,
        "watchlist": ["SPY", "AAPL"],
        "discovery": {"enabled": False, "max_tickers": 50},
        "market": {
            "open_hour": 9,
            "open_minute": 30,
            "close_hour": 16,
            "close_minute": 0,
            "timezone": "US/Eastern",
        },
        "daily_summary": {"enabled": False},
    }


@pytest.fixture
def mock_components():
    polygon = AsyncMock()
    detector = MagicMock()
    alerts = AsyncMock()
    db = AsyncMock()
    return polygon, detector, alerts, db


class TestMarketHours:
    def test_weekday_during_market_hours(self, config, mock_components):
        """Should return True during market hours on a weekday."""
        scanner = Scanner(config, *mock_components)
        # Wednesday Feb 14, 2026, 10:30 AM ET
        et = pytz.timezone("US/Eastern")
        mock_time = et.localize(datetime(2026, 2, 11, 10, 30, 0))  # Wednesday
        with patch.object(scanner, '_now_et', return_value=mock_time):
            assert scanner._is_market_hours() is True

    def test_weekday_before_market_open(self, config, mock_components):
        """Should return False before market opens."""
        scanner = Scanner(config, *mock_components)
        et = pytz.timezone("US/Eastern")
        mock_time = et.localize(datetime(2026, 2, 11, 8, 0, 0))  # 8 AM Wed
        with patch.object(scanner, '_now_et', return_value=mock_time):
            assert scanner._is_market_hours() is False

    def test_weekday_after_market_close(self, config, mock_components):
        """Should return False after market closes."""
        scanner = Scanner(config, *mock_components)
        et = pytz.timezone("US/Eastern")
        mock_time = et.localize(datetime(2026, 2, 11, 17, 0, 0))  # 5 PM Wed
        with patch.object(scanner, '_now_et', return_value=mock_time):
            assert scanner._is_market_hours() is False

    def test_weekend_returns_false(self, config, mock_components):
        """Should return False on weekends."""
        scanner = Scanner(config, *mock_components)
        et = pytz.timezone("US/Eastern")
        # Saturday Feb 14, 2026 is actually a Saturday
        mock_time = et.localize(datetime(2026, 2, 14, 12, 0, 0))  # Saturday noon
        with patch.object(scanner, '_now_et', return_value=mock_time):
            assert scanner._is_market_hours() is False

    def test_market_open_boundary(self, config, mock_components):
        """Exactly at 9:30 should count as market hours."""
        scanner = Scanner(config, *mock_components)
        et = pytz.timezone("US/Eastern")
        mock_time = et.localize(datetime(2026, 2, 11, 9, 30, 0))  # Exactly 9:30
        with patch.object(scanner, '_now_et', return_value=mock_time):
            assert scanner._is_market_hours() is True

    def test_market_close_boundary(self, config, mock_components):
        """Exactly at 16:00 should count as market hours."""
        scanner = Scanner(config, *mock_components)
        et = pytz.timezone("US/Eastern")
        mock_time = et.localize(datetime(2026, 2, 11, 16, 0, 0))
        with patch.object(scanner, '_now_et', return_value=mock_time):
            assert scanner._is_market_hours() is True


class TestScanCycle:
    @pytest.mark.asyncio
    async def test_scan_cycle_scans_watchlist(self, config, mock_components):
        """Should scan all tickers in the watchlist."""
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.return_value = [{"fake": "data"}]
        detector.analyze_snapshot.return_value = []

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        await scanner._scan_cycle()

        assert polygon.get_options_snapshot.call_count == 2  # SPY, AAPL
        assert detector.analyze_snapshot.call_count == 2

    @pytest.mark.asyncio
    async def test_scan_cycle_with_signals(self, config, mock_components):
        """When signals are found, they should be sent and stored."""
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.return_value = [{"fake": "data"}]

        sig = _make_signal()
        detector.analyze_snapshot.return_value = [sig]

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        await scanner._scan_cycle()

        alerts.send_signals.assert_called_once()
        db.insert_signals.assert_called_once()
        # The signals sent should be sorted by risk score
        sent_signals = alerts.send_signals.call_args[0][0]
        assert len(sent_signals) >= 1

    @pytest.mark.asyncio
    async def test_scan_cycle_no_signals(self, config, mock_components):
        """When no signals found, alerts should not be sent."""
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.return_value = [{"fake": "data"}]
        detector.analyze_snapshot.return_value = []

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        await scanner._scan_cycle()

        alerts.send_signals.assert_not_called()
        db.insert_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_cycle_api_returns_empty(self, config, mock_components):
        """Empty API response should be handled gracefully."""
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.return_value = []

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        await scanner._scan_cycle()

        detector.analyze_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_scan_cycle_api_error(self, config, mock_components):
        """API errors should be caught per-ticker, not crash the cycle."""
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.side_effect = Exception("API down")

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        # Should not raise
        await scanner._scan_cycle()


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discovery_enabled(self, config, mock_components):
        """Discovery mode should scan additional tickers."""
        config["discovery"]["enabled"] = True
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.return_value = [{"fake": "data"}]
        polygon.get_most_active.return_value = ["NVDA", "TSLA", "SPY"]
        detector.analyze_snapshot.return_value = []

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        await scanner._scan_cycle()

        # Watchlist (SPY, AAPL) + discovered (NVDA, TSLA — SPY is deduped)
        assert polygon.get_options_snapshot.call_count == 4

    @pytest.mark.asyncio
    async def test_discovery_dedupes_watchlist(self, config, mock_components):
        """Discovered tickers already in watchlist should be skipped."""
        config["discovery"]["enabled"] = True
        polygon, detector, alerts, db = mock_components
        polygon.get_options_snapshot.return_value = []
        polygon.get_most_active.return_value = ["SPY", "AAPL"]  # All in watchlist
        detector.analyze_snapshot.return_value = []

        scanner = Scanner(config, polygon, detector, alerts, db)
        scanner._running = True
        await scanner._scan_cycle()

        # Only watchlist tickers scanned, no discovered ones added
        assert polygon.get_options_snapshot.call_count == 2


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_flag(self, config, mock_components):
        """stop() should set _running to False."""
        scanner = Scanner(config, *mock_components)
        scanner._running = True
        await scanner.stop()
        assert scanner._running is False
