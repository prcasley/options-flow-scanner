"""Tests for the backtesting engine."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.backtest import Backtester, BacktestResult, BacktestStats
from scanner.models import Signal


def _make_signal(ticker="AAPL", strike=220.0, contract_type="call",
                 volume=5000, risk_score=4, premium=1_000_000,
                 days_ago=0, signal_types=None):
    return Signal(
        timestamp=datetime(2025, 3, 15, 10, 30) - timedelta(days=days_ago),
        ticker=ticker,
        strike=strike,
        expiry="2025-03-21",
        contract_type=contract_type,
        volume=volume,
        open_interest=1000,
        estimated_premium=premium,
        risk_score=risk_score,
        signal_types=signal_types or ["volume spike"],
        description=f"{ticker} test signal",
        volume_ratio=10.0,
        oi_ratio=4.0,
        last_price=3.0,
    )


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db._db = MagicMock()
    return db


@pytest.fixture
def backtester(mock_db):
    return Backtester(mock_db)


class TestBacktester:
    async def test_run_returns_backtest_result(self, backtester, mock_db):
        """run() should return a BacktestResult."""
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db._db.execute = AsyncMock(return_value=cursor)

        result = await backtester.run()
        assert isinstance(result, BacktestResult)
        assert isinstance(result.stats, BacktestStats)

    async def test_run_with_no_db(self, mock_db):
        """Should return empty result when db is not initialized."""
        mock_db._db = None
        bt = Backtester(mock_db)
        result = await bt.run()
        assert result.stats.total_signals == 0
        assert result.signals == []

    async def test_run_with_signals(self, backtester, mock_db):
        """Should process signals fetched from db."""
        rows = [
            (
                "2025-03-15T10:30:00",
                "AAPL", 220.0, "2025-03-21", "call",
                5000, 1000, 1_000_000.0, 4,
                "volume spike|bullish sweep",
                10.0, 4.0, "AAPL test signal", 3.0,
            ),
            (
                "2025-03-14T10:30:00",
                "TSLA", 180.0, "2025-03-21", "put",
                3000, 800, 500_000.0, 3,
                "volume spike",
                8.0, 3.5, "TSLA test signal", 2.0,
            ),
        ]
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=rows)
        mock_db._db.execute = AsyncMock(return_value=cursor)

        result = await backtester.run()
        assert result.stats.total_signals == 2
        assert len(result.signals) == 2

    def test_apply_filters_risk(self, backtester):
        """Signals outside risk range should be filtered."""
        signals = [
            _make_signal(risk_score=2),
            _make_signal(risk_score=4),
            _make_signal(risk_score=5),
        ]
        filtered = backtester._apply_filters(signals, min_risk=4, max_risk=5,
                                              signal_types=None, min_premium=0)
        assert len(filtered) == 2
        assert all(s.risk_score >= 4 for s in filtered)

    def test_apply_filters_premium(self, backtester):
        """Signals below min premium should be filtered."""
        signals = [
            _make_signal(premium=10_000),
            _make_signal(premium=500_000),
            _make_signal(premium=2_000_000),
        ]
        filtered = backtester._apply_filters(signals, min_risk=1, max_risk=5,
                                              signal_types=None, min_premium=100_000)
        assert len(filtered) == 2

    def test_apply_filters_signal_types(self, backtester):
        """Should filter by signal type."""
        signals = [
            _make_signal(signal_types=["volume spike"]),
            _make_signal(signal_types=["bullish sweep"]),
            _make_signal(signal_types=["volume spike", "near expiry"]),
        ]
        filtered = backtester._apply_filters(signals, min_risk=1, max_risk=5,
                                              signal_types=["bullish sweep"],
                                              min_premium=0)
        assert len(filtered) == 1
        assert "bullish sweep" in filtered[0].signal_types

    def test_compute_stats_empty(self, backtester):
        """Empty signals should return zero stats."""
        stats = backtester._compute_stats([])
        assert stats.total_signals == 0
        assert stats.total_days == 0

    def test_compute_stats(self, backtester):
        """Should correctly compute aggregate stats."""
        signals = [
            _make_signal(ticker="AAPL", risk_score=4, premium=1_000_000, days_ago=0),
            _make_signal(ticker="AAPL", risk_score=3, premium=500_000, days_ago=1),
            _make_signal(ticker="TSLA", risk_score=5, premium=2_000_000, days_ago=0),
        ]
        stats = backtester._compute_stats(signals)
        assert stats.total_signals == 3
        assert stats.total_days == 2
        assert stats.avg_risk_score == 4.0
        assert stats.total_premium_scanned == 3_500_000
        assert len(stats.top_tickers) == 2

    def test_compute_stats_top_tickers_sorted(self, backtester):
        """Top tickers should be sorted by count descending."""
        signals = [
            _make_signal(ticker="AAPL", days_ago=i) for i in range(5)
        ] + [
            _make_signal(ticker="TSLA", days_ago=i) for i in range(3)
        ]
        stats = backtester._compute_stats(signals)
        assert stats.top_tickers[0][0] == "AAPL"
        assert stats.top_tickers[0][1] == 5

    def test_format_report(self, backtester):
        """Report should contain key sections."""
        stats = BacktestStats(
            total_signals=10,
            total_days=3,
            avg_signals_per_day=3.3,
            avg_risk_score=3.5,
            total_premium_scanned=5_000_000,
            top_tickers=[("AAPL", 6), ("TSLA", 4)],
            risk_distribution={3: 4, 4: 4, 5: 2},
            signal_type_counts={"volume spike": 8, "bullish sweep": 5},
            daily_signal_counts={"2025-03-13": 3, "2025-03-14": 3, "2025-03-15": 4},
        )
        result = BacktestResult(stats=stats, signals=[], patterns=[],
                                 filters_applied={"start_date": "all"})
        report = backtester.format_report(result)
        assert "BACKTEST REPORT" in report
        assert "AAPL" in report
        assert "RISK DISTRIBUTION" in report
        assert "SIGNAL TYPES" in report

    async def test_run_with_date_filters(self, backtester, mock_db):
        """run() should pass date parameters to query."""
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db._db.execute = AsyncMock(return_value=cursor)

        await backtester.run(start_date="2025-03-01", end_date="2025-03-15")

        call_args = mock_db._db.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "timestamp >=" in query
        assert "timestamp <" in query
        assert "2025-03-01" in params
        assert "2025-03-15T23:59:59" in params

    async def test_run_with_ticker_filter(self, backtester, mock_db):
        """run() should pass ticker filters to query."""
        cursor = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[])
        mock_db._db.execute = AsyncMock(return_value=cursor)

        await backtester.run(tickers=["AAPL", "TSLA"])

        call_args = mock_db._db.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "ticker IN" in query
        assert "AAPL" in params
        assert "TSLA" in params
