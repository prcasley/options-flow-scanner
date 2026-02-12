"""Recurring pattern analysis for options flow signals."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .models import Signal

logger = logging.getLogger(__name__)


@dataclass
class PatternResult:
    """A detected recurring pattern in signal data."""
    ticker: str
    pattern_type: str
    occurrences: int
    avg_risk_score: float
    avg_premium: float
    description: str
    first_seen: datetime
    last_seen: datetime
    signal_types: list[str] = field(default_factory=list)


class PatternAnalyzer:
    """Analyzes historical signals for recurring patterns.

    Detects:
    - Repeat flow: same ticker + contract type appearing N+ times
    - Accumulation: growing volume on same strike across sessions
    - Cluster activity: multiple strikes on same ticker in short windows
    - High-conviction repeat: same ticker hitting risk 4+ repeatedly
    """

    def __init__(self, min_occurrences: int = 3, lookback_days: int = 7):
        self.min_occurrences = min_occurrences
        self.lookback_days = lookback_days

    def analyze(self, signals: list[Signal]) -> list[PatternResult]:
        """Run all pattern detectors on a list of signals."""
        if not signals:
            return []

        results = []
        results.extend(self._detect_repeat_flow(signals))
        results.extend(self._detect_accumulation(signals))
        results.extend(self._detect_cluster_activity(signals))
        results.extend(self._detect_high_conviction(signals))

        # Deduplicate and sort by occurrence count
        results.sort(key=lambda p: p.occurrences, reverse=True)
        return results

    def _detect_repeat_flow(self, signals: list[Signal]) -> list[PatternResult]:
        """Detect tickers with repeated unusual flow (same direction)."""
        patterns = []
        # Group by ticker + contract_type
        groups: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            key = f"{s.ticker}:{s.contract_type}"
            groups[key].append(s)

        for key, group in groups.items():
            if len(group) < self.min_occurrences:
                continue
            ticker, ctype = key.split(":")
            avg_risk = sum(s.risk_score for s in group) / len(group)
            avg_prem = sum(s.estimated_premium for s in group) / len(group)
            direction = "bullish" if ctype == "call" else "bearish"
            all_types = set()
            for s in group:
                all_types.update(s.signal_types)

            patterns.append(PatternResult(
                ticker=ticker,
                pattern_type="repeat_flow",
                occurrences=len(group),
                avg_risk_score=round(avg_risk, 1),
                avg_premium=avg_prem,
                description=(
                    f"{ticker} showing repeated {direction} flow: "
                    f"{len(group)} signals, avg risk {avg_risk:.1f}/5"
                ),
                first_seen=min(s.timestamp for s in group),
                last_seen=max(s.timestamp for s in group),
                signal_types=sorted(all_types),
            ))
        return patterns

    def _detect_accumulation(self, signals: list[Signal]) -> list[PatternResult]:
        """Detect accumulation: same ticker+strike with growing volume."""
        patterns = []
        # Group by ticker + strike + contract_type
        groups: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            key = f"{s.ticker}:{s.strike}:{s.contract_type}"
            groups[key].append(s)

        for key, group in groups.items():
            if len(group) < self.min_occurrences:
                continue

            # Sort by time and check for growing volume trend
            group.sort(key=lambda s: s.timestamp)
            volumes = [s.volume for s in group]
            if len(volumes) >= 3:
                # Check if at least 50% of sequential pairs show increase
                increases = sum(1 for i in range(len(volumes) - 1)
                                if volumes[i + 1] > volumes[i])
                if increases / (len(volumes) - 1) < 0.5:
                    continue

            ticker, strike, ctype = key.split(":")
            side = "C" if ctype == "call" else "P"
            avg_prem = sum(s.estimated_premium for s in group) / len(group)

            patterns.append(PatternResult(
                ticker=ticker,
                pattern_type="accumulation",
                occurrences=len(group),
                avg_risk_score=round(sum(s.risk_score for s in group) / len(group), 1),
                avg_premium=avg_prem,
                description=(
                    f"{ticker} {strike}{side} accumulation: "
                    f"{len(group)} sessions with growing volume"
                ),
                first_seen=group[0].timestamp,
                last_seen=group[-1].timestamp,
                signal_types=["accumulation"],
            ))
        return patterns

    def _detect_cluster_activity(self, signals: list[Signal]) -> list[PatternResult]:
        """Detect cluster: multiple different strikes on same ticker in one session."""
        patterns = []
        # Group by ticker + date
        groups: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            date_key = s.timestamp.strftime("%Y-%m-%d")
            key = f"{s.ticker}:{date_key}"
            groups[key].append(s)

        for key, group in groups.items():
            # Need multiple distinct strikes
            strikes = {s.strike for s in group}
            if len(strikes) < self.min_occurrences:
                continue

            ticker, date_str = key.split(":")
            avg_risk = sum(s.risk_score for s in group) / len(group)
            total_prem = sum(s.estimated_premium for s in group)

            patterns.append(PatternResult(
                ticker=ticker,
                pattern_type="cluster",
                occurrences=len(group),
                avg_risk_score=round(avg_risk, 1),
                avg_premium=total_prem / len(group),
                description=(
                    f"{ticker} cluster on {date_str}: "
                    f"{len(strikes)} strikes, {len(group)} signals, "
                    f"total premium ${total_prem/1e6:.1f}M"
                ),
                first_seen=min(s.timestamp for s in group),
                last_seen=max(s.timestamp for s in group),
                signal_types=["cluster"],
            ))
        return patterns

    def _detect_high_conviction(self, signals: list[Signal]) -> list[PatternResult]:
        """Detect tickers with repeated high-risk (4+) signals."""
        patterns = []
        groups: dict[str, list[Signal]] = defaultdict(list)
        for s in signals:
            if s.risk_score >= 4:
                groups[s.ticker].append(s)

        for ticker, group in groups.items():
            if len(group) < self.min_occurrences:
                continue
            avg_prem = sum(s.estimated_premium for s in group) / len(group)
            all_types = set()
            for s in group:
                all_types.update(s.signal_types)

            patterns.append(PatternResult(
                ticker=ticker,
                pattern_type="high_conviction",
                occurrences=len(group),
                avg_risk_score=round(sum(s.risk_score for s in group) / len(group), 1),
                avg_premium=avg_prem,
                description=(
                    f"{ticker} high-conviction: {len(group)} signals "
                    f"at risk 4+, avg premium ${avg_prem/1e6:.1f}M"
                ),
                first_seen=min(s.timestamp for s in group),
                last_seen=max(s.timestamp for s in group),
                signal_types=sorted(all_types),
            ))
        return patterns

    def format_report(self, patterns: list[PatternResult]) -> str:
        """Format pattern results into a human-readable report."""
        if not patterns:
            return "No recurring patterns detected."

        lines = [f"Recurring Patterns Detected ({len(patterns)} patterns)\n{'='*50}"]
        for i, p in enumerate(patterns, 1):
            lines.append(
                f"\n{i}. [{p.pattern_type.upper()}] {p.description}"
                f"\n   Occurrences: {p.occurrences} | "
                f"Avg Risk: {p.avg_risk_score}/5 | "
                f"Window: {p.first_seen.strftime('%m/%d')} - {p.last_seen.strftime('%m/%d')}"
            )
        return "\n".join(lines)
