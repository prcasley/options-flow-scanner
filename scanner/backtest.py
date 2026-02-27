"""Historical data analysis and backtesting for options flow signals."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import Signal
from .patterns import PatternAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class BacktestStats:
    """Aggregated statistics from a backtest run."""
    total_signals: int = 0
    total_days: int = 0
    avg_signals_per_day: float = 0.0
    avg_risk_score: float = 0.0
    total_premium_scanned: float = 0.0
    top_tickers: list[tuple[str, int]] = field(default_factory=list)
    risk_distribution: dict[int, int] = field(default_factory=dict)
    signal_type_counts: dict[str, int] = field(default_factory=dict)
    daily_signal_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class BacktestResult:
    """Full backtest result with stats, filtered signals, and patterns."""
    stats: BacktestStats
    signals: list[Signal]
    patterns: list  # list[PatternResult]
    filters_applied: dict[str, str] = field(default_factory=dict)


class Backtester:
    """Runs backtests on historical signal data from the database.

    Supports filtering by date range, ticker, risk score, signal type,
    and minimum premium. Integrates with PatternAnalyzer for pattern detection.
    """

    def __init__(self, db):
        self.db = db
        self.pattern_analyzer = PatternAnalyzer()

    async def run(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        tickers: Optional[list[str]] = None,
        min_risk: int = 1,
        max_risk: int = 5,
        signal_types: Optional[list[str]] = None,
        min_premium: float = 0,
    ) -> BacktestResult:
        """Run a backtest with the given filters.

        Args:
            start_date: Start date (YYYY-MM-DD), defaults to all history.
            end_date: End date (YYYY-MM-DD), defaults to today.
            tickers: Filter to specific tickers, None for all.
            min_risk: Minimum risk score to include (1-5).
            max_risk: Maximum risk score to include (1-5).
            signal_types: Filter to specific signal types, None for all.
            min_premium: Minimum premium to include.
        """
        # Fetch all signals from DB
        raw_signals = await self._fetch_signals(start_date, end_date, tickers)

        # Apply filters
        filtered = self._apply_filters(
            raw_signals, min_risk, max_risk, signal_types, min_premium
        )

        # Compute stats
        stats = self._compute_stats(filtered)

        # Run pattern analysis
        patterns = self.pattern_analyzer.analyze(filtered)

        filters_applied = {
            "start_date": start_date or "all",
            "end_date": end_date or "today",
            "tickers": ",".join(tickers) if tickers else "all",
            "risk_range": f"{min_risk}-{max_risk}",
            "min_premium": f"${min_premium:,.0f}",
        }

        return BacktestResult(
            stats=stats,
            signals=filtered,
            patterns=patterns,
            filters_applied=filters_applied,
        )

    async def _fetch_signals(
        self,
        start_date: Optional[str],
        end_date: Optional[str],
        tickers: Optional[list[str]],
    ) -> list[Signal]:
        """Fetch signals from database, optionally filtered by date/ticker."""
        if not self.db._db:
            return []

        query = """SELECT timestamp, ticker, strike, expiry, contract_type,
                          volume, open_interest, estimated_premium, risk_score,
                          signal_types, volume_ratio, oi_ratio, description, last_price
                   FROM signals WHERE 1=1"""
        params: list = []

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp < ?"
            params.append(end_date + "T23:59:59")
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            query += f" AND ticker IN ({placeholders})"
            params.extend(tickers)

        query += " ORDER BY timestamp DESC"

        cursor = await self.db._db.execute(query, params)
        rows = await cursor.fetchall()

        signals = []
        for row in rows:
            signals.append(Signal(
                timestamp=datetime.fromisoformat(row[0]),
                ticker=row[1],
                strike=row[2],
                expiry=row[3],
                contract_type=row[4],
                volume=row[5],
                open_interest=row[6],
                estimated_premium=row[7],
                risk_score=row[8],
                signal_types=row[9].split("|") if row[9] else [],
                volume_ratio=row[10] or 0.0,
                oi_ratio=row[11] or 0.0,
                description=row[12] or "",
                last_price=row[13] or 0.0,
            ))
        return signals

    def _apply_filters(
        self,
        signals: list[Signal],
        min_risk: int,
        max_risk: int,
        signal_types: Optional[list[str]],
        min_premium: float,
    ) -> list[Signal]:
        """Apply additional filters on fetched signals."""
        filtered = []
        for s in signals:
            if s.risk_score < min_risk or s.risk_score > max_risk:
                continue
            if s.estimated_premium < min_premium:
                continue
            if signal_types:
                if not any(st in s.signal_types for st in signal_types):
                    continue
            filtered.append(s)
        return filtered

    def _compute_stats(self, signals: list[Signal]) -> BacktestStats:
        """Compute aggregate statistics for a set of signals."""
        stats = BacktestStats()
        if not signals:
            return stats

        stats.total_signals = len(signals)

        # Daily counts
        days: dict[str, int] = defaultdict(int)
        ticker_counts: dict[str, int] = defaultdict(int)
        risk_dist: dict[int, int] = defaultdict(int)
        type_counts: dict[str, int] = defaultdict(int)
        total_premium = 0.0
        total_risk = 0

        for s in signals:
            date_key = s.timestamp.strftime("%Y-%m-%d")
            days[date_key] += 1
            ticker_counts[s.ticker] += 1
            risk_dist[s.risk_score] += 1
            total_premium += s.estimated_premium
            total_risk += s.risk_score
            for st in s.signal_types:
                type_counts[st] += 1

        stats.total_days = len(days)
        stats.avg_signals_per_day = round(
            stats.total_signals / max(stats.total_days, 1), 1
        )
        stats.avg_risk_score = round(total_risk / stats.total_signals, 1)
        stats.total_premium_scanned = total_premium
        stats.top_tickers = sorted(
            ticker_counts.items(), key=lambda x: x[1], reverse=True
        )[:10]
        stats.risk_distribution = dict(sorted(risk_dist.items()))
        stats.signal_type_counts = dict(
            sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        )
        stats.daily_signal_counts = dict(sorted(days.items()))

        return stats

    def format_report(self, result: BacktestResult) -> str:
        """Format a backtest result into a readable report."""
        s = result.stats
        lines = [
            "BACKTEST REPORT",
            "=" * 60,
            f"Filters: {result.filters_applied}",
            "",
            "OVERVIEW",
            "-" * 40,
            f"Total signals: {s.total_signals}",
            f"Trading days: {s.total_days}",
            f"Avg signals/day: {s.avg_signals_per_day}",
            f"Avg risk score: {s.avg_risk_score}/5",
            f"Total premium: ${s.total_premium_scanned/1e6:.1f}M",
            "",
            "TOP TICKERS",
            "-" * 40,
        ]
        for ticker, count in s.top_tickers:
            lines.append(f"  {ticker}: {count} signals")

        lines.extend(["", "RISK DISTRIBUTION", "-" * 40])
        for risk, count in s.risk_distribution.items():
            bar = "\u2588" * count
            lines.append(f"  Risk {risk}: {count:4d} {bar}")

        lines.extend(["", "SIGNAL TYPES", "-" * 40])
        for stype, count in s.signal_type_counts.items():
            lines.append(f"  {stype}: {count}")

        if result.patterns:
            lines.extend(["", "PATTERNS DETECTED", "-" * 40])
            for p in result.patterns[:10]:
                lines.append(f"  [{p.pattern_type}] {p.description}")

        return "\n".join(lines)
