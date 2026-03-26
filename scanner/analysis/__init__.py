"""Signal detection, pattern analysis, and backtesting."""

from .backtest import Backtester, BacktestResult, BacktestStats
from .detector import Detector
from .patterns import PatternAnalyzer, PatternResult

__all__ = [
    "Detector",
    "PatternAnalyzer",
    "PatternResult",
    "Backtester",
    "BacktestStats",
    "BacktestResult",
]
