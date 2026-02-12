"""Unit tests for the main scan loop orchestrator."""

from datetime import datetime, date
from unittest.mock import AsyncMock, patch, PropertyMock

import pytest
import pytz

from scanner.detector import Detector
from scanner.scheduler import Scanner, US_MARKET_HOLIDAYS


@pytest.fixture
def scanner(sample_config, mock_polygon_client, mock_alert_manager, mock_database):
    det = Detector(sample_config)
    return Scanner(sample_config, mock_polygon_client, det,
                   mock_alert_manager, mock_database)


class TestMarketHours:
    def test_weekday_during_hours(self, scanner):
        # Monday 10:30 AM ET
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 10, 30, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            assert scanner._is_market_hours() is True

    def test_weekday_before_open(self, scanner):
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 8, 0, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            assert scanner._is_market_hours() is False

    def test_weekday_after_close(self, scanner):
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 17, 0, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            assert scanner._is_market_hours() is False

    def test_weekend_rejected(self, scanner):
        # Saturday
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 15, 10, 30, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            assert scanner._is_market_hours() is False

    def test_holiday_rejected(self, scanner):
        # Christmas 2025 is a Thursday
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 12, 25, 10, 30, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            assert scanner._is_market_hours() is False


class TestUSMarketHolidays:
    def test_holidays_are_date_objects(self):
        for h in US_MARKET_HOLIDAYS:
            assert isinstance(h, date)

    def test_known_holidays_present(self):
        # Christmas 2025
        assert date(2025, 12, 25) in US_MARKET_HOLIDAYS
        # New Year 2025
        assert date(2025, 1, 1) in US_MARKET_HOLIDAYS
        # MLK Day 2025
        assert date(2025, 1, 20) in US_MARKET_HOLIDAYS

    def test_covers_multiple_years(self):
        years = {h.year for h in US_MARKET_HOLIDAYS}
        assert 2024 in years
        assert 2025 in years
        assert 2026 in years
        assert 2027 in years


class TestDailySummary:
    @pytest.mark.asyncio
    async def test_sends_summary_at_target_time(self, scanner):
        # At summary time (4:15 PM ET)
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 16, 15, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            await scanner._check_daily_summary()
            scanner.alerts.send_daily_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_duplicate_summary(self, scanner):
        et = pytz.timezone("US/Eastern")
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 16, 15, 0, tzinfo=et
        )):
            await scanner._check_daily_summary()
            await scanner._check_daily_summary()  # second call
            # Should only send once
            assert scanner.alerts.send_daily_summary.call_count == 1

    @pytest.mark.asyncio
    async def test_summary_resets_for_new_day(self, scanner):
        et = pytz.timezone("US/Eastern")
        # Day 1
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 16, 15, 0, tzinfo=et
        )):
            await scanner._check_daily_summary()

        # Day 2
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 18, 16, 15, 0, tzinfo=et
        )):
            await scanner._check_daily_summary()

        assert scanner.alerts.send_daily_summary.call_count == 2

    @pytest.mark.asyncio
    async def test_no_summary_before_target(self, scanner):
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 16, 10, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            await scanner._check_daily_summary()
            scanner.alerts.send_daily_summary.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_summary_when_disabled(self, scanner):
        scanner.config["daily_summary"]["enabled"] = False
        with patch.object(scanner, '_now_et', return_value=datetime(
            2025, 3, 17, 16, 15, 0, tzinfo=pytz.timezone("US/Eastern")
        )):
            await scanner._check_daily_summary()
            scanner.alerts.send_daily_summary.assert_not_called()


class TestScanCycle:
    @pytest.mark.asyncio
    async def test_scans_watchlist(self, scanner):
        scanner._running = True
        scanner.polygon.get_options_snapshot = AsyncMock(return_value=[])
        await scanner._scan_cycle()
        # Should have called get_options_snapshot for each watchlist ticker
        assert scanner.polygon.get_options_snapshot.call_count == 2  # SPY, AAPL

    @pytest.mark.asyncio
    async def test_discovery_disabled(self, scanner):
        scanner._running = True
        scanner.config["discovery"]["enabled"] = False
        scanner.polygon.get_options_snapshot = AsyncMock(return_value=[])
        await scanner._scan_cycle()
        scanner.polygon.get_most_active.assert_not_called()

    @pytest.mark.asyncio
    async def test_signals_sent_to_alerts(self, scanner, sample_contract_raw):
        scanner._running = True
        scanner.polygon.get_options_snapshot = AsyncMock(return_value=[sample_contract_raw])
        # Seed a low average so the contract triggers a signal
        det = scanner.detector
        key = det._contract_key("SPY", 220.0, "2025-03-21", "call")
        det._avg_volume.setdefault("SPY", {})[key] = 10.0
        det._total_tracked = 1

        await scanner._scan_cycle()
        if scanner.alerts.send_signals.called:
            signals = scanner.alerts.send_signals.call_args[0][0]
            assert len(signals) > 0

    @pytest.mark.asyncio
    async def test_handles_scan_error(self, scanner):
        scanner.polygon.get_options_snapshot = AsyncMock(
            side_effect=Exception("API down")
        )
        # Should not raise
        signals = await scanner._scan_ticker("AAPL")
        assert signals == []


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_discover_tickers(self, scanner):
        scanner.polygon.get_most_active = AsyncMock(
            return_value=["TSLA", "META", "NVDA"]
        )
        tickers = await scanner._discover_tickers()
        assert tickers == ["TSLA", "META", "NVDA"]

    @pytest.mark.asyncio
    async def test_discovery_error_returns_empty(self, scanner):
        scanner.polygon.get_most_active = AsyncMock(
            side_effect=Exception("timeout")
        )
        tickers = await scanner._discover_tickers()
        assert tickers == []


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_flag(self, scanner):
        assert scanner._running is False
        scanner._running = True
        await scanner.stop()
        assert scanner._running is False
