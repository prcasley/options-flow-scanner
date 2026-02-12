"""Tests for recurring pattern analysis."""

from datetime import datetime, timedelta

import pytest

from scanner.models import Signal
from scanner.patterns import PatternAnalyzer, PatternResult


def _make_signal(ticker="AAPL", strike=220.0, contract_type="call",
                 volume=5000, risk_score=4, premium=1_000_000,
                 days_ago=0, signal_types=None):
    """Helper to create test signals with sensible defaults."""
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


class TestPatternAnalyzer:
    def test_empty_signals_returns_empty(self):
        analyzer = PatternAnalyzer()
        assert analyzer.analyze([]) == []

    def test_detect_repeat_flow(self):
        """Signals with same ticker+contract_type >= min_occurrences trigger repeat_flow."""
        signals = [
            _make_signal(days_ago=i) for i in range(4)
        ]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        repeat = [r for r in results if r.pattern_type == "repeat_flow"]
        assert len(repeat) >= 1
        assert repeat[0].ticker == "AAPL"
        assert repeat[0].occurrences == 4

    def test_repeat_flow_below_threshold(self):
        """Fewer than min_occurrences should not trigger."""
        signals = [_make_signal(days_ago=i) for i in range(2)]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        repeat = [r for r in results if r.pattern_type == "repeat_flow"]
        assert len(repeat) == 0

    def test_detect_accumulation(self):
        """Same ticker+strike with growing volume triggers accumulation."""
        signals = [
            _make_signal(volume=100, days_ago=3),
            _make_signal(volume=200, days_ago=2),
            _make_signal(volume=400, days_ago=1),
            _make_signal(volume=800, days_ago=0),
        ]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        accum = [r for r in results if r.pattern_type == "accumulation"]
        assert len(accum) >= 1
        assert "accumulation" in accum[0].description.lower()

    def test_accumulation_no_growth(self):
        """Declining volume should not be flagged as accumulation."""
        signals = [
            _make_signal(volume=800, days_ago=3),
            _make_signal(volume=400, days_ago=2),
            _make_signal(volume=200, days_ago=1),
            _make_signal(volume=100, days_ago=0),
        ]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        accum = [r for r in results if r.pattern_type == "accumulation"]
        assert len(accum) == 0

    def test_detect_cluster_activity(self):
        """Multiple strikes on same ticker on same date triggers cluster."""
        base = datetime(2025, 3, 15, 10, 0)
        signals = [
            _make_signal(strike=200 + i * 5)
            for i in range(5)
        ]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        clusters = [r for r in results if r.pattern_type == "cluster"]
        assert len(clusters) >= 1
        assert clusters[0].ticker == "AAPL"

    def test_detect_high_conviction(self):
        """Repeated risk 4+ signals on same ticker triggers high_conviction."""
        signals = [
            _make_signal(risk_score=5, days_ago=i) for i in range(4)
        ]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        hc = [r for r in results if r.pattern_type == "high_conviction"]
        assert len(hc) >= 1
        assert hc[0].avg_risk_score >= 4.0

    def test_high_conviction_ignores_low_risk(self):
        """Risk < 4 signals should not appear in high_conviction."""
        signals = [
            _make_signal(risk_score=2, days_ago=i) for i in range(5)
        ]
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        hc = [r for r in results if r.pattern_type == "high_conviction"]
        assert len(hc) == 0

    def test_results_sorted_by_occurrences(self):
        """Results should be sorted by occurrences descending."""
        signals = (
            [_make_signal(ticker="AAPL", days_ago=i) for i in range(5)] +
            [_make_signal(ticker="TSLA", days_ago=i) for i in range(3)]
        )
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        if len(results) >= 2:
            assert results[0].occurrences >= results[1].occurrences

    def test_multiple_tickers(self):
        """Patterns from different tickers both appear."""
        signals = (
            [_make_signal(ticker="AAPL", days_ago=i) for i in range(4)] +
            [_make_signal(ticker="TSLA", contract_type="put", days_ago=i) for i in range(4)]
        )
        analyzer = PatternAnalyzer(min_occurrences=3)
        results = analyzer.analyze(signals)
        tickers = {r.ticker for r in results}
        assert "AAPL" in tickers
        assert "TSLA" in tickers

    def test_format_report_empty(self):
        analyzer = PatternAnalyzer()
        report = analyzer.format_report([])
        assert "No recurring patterns" in report

    def test_format_report_with_patterns(self):
        patterns = [
            PatternResult(
                ticker="AAPL",
                pattern_type="repeat_flow",
                occurrences=5,
                avg_risk_score=4.2,
                avg_premium=1_000_000,
                description="AAPL showing repeated bullish flow",
                first_seen=datetime(2025, 3, 10),
                last_seen=datetime(2025, 3, 15),
                signal_types=["volume spike"],
            )
        ]
        report = PatternAnalyzer().format_report(patterns)
        assert "REPEAT_FLOW" in report
        assert "AAPL" in report
        assert "5" in report
