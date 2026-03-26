"""Options Flow Scanner package.

Backward-compatible re-exports so any code that previously imported from
the flat scanner.* namespace continues to work after the modular refactor.

Canonical import paths:
  scanner.core.models        — OptionsContract, Signal
  scanner.core.database      — SignalDatabase
  scanner.core.scheduler     — Scanner
  scanner.sources.polygon_client  — PolygonClient, RateLimiter
  scanner.sources.yfinance_client — YFinanceClient
  scanner.sources.schwab_client   — SchwabClient
  scanner.sources.source_manager  — SourceManager
  scanner.analysis.detector  — Detector
  scanner.analysis.patterns  — PatternAnalyzer, PatternResult
  scanner.analysis.backtest  — Backtester, BacktestStats, BacktestResult
  scanner.alerts.manager     — AlertManager, RISK_EMOJI
  scanner.alerts.channels    — AlertChannel, DiscordChannel, SlackChannel,
                               EmailChannel, MultiChannelDispatcher
  scanner.dashboard.health   — HealthServer
  scanner.dashboard.server   — DashboardServer
"""

from .alerts.channels import (
    AlertChannel,
    DiscordChannel,
    EmailChannel,
    MultiChannelDispatcher,
    SlackChannel,
)
from .alerts.manager import AlertManager, RISK_EMOJI
from .analysis.backtest import Backtester, BacktestResult, BacktestStats
from .analysis.detector import Detector
from .analysis.patterns import PatternAnalyzer, PatternResult
from .core.database import SignalDatabase
from .core.models import OptionsContract, Signal
from .core.scheduler import Scanner
from .dashboard.health import HealthServer
from .dashboard.server import DashboardServer
from .sources.polygon_client import PolygonClient, RateLimiter
from .sources.schwab_client import SchwabClient
from .sources.source_manager import SourceManager
from .sources.yfinance_client import YFinanceClient

__all__ = [
    # core
    "OptionsContract",
    "Signal",
    "SignalDatabase",
    "Scanner",
    # sources
    "PolygonClient",
    "RateLimiter",
    "YFinanceClient",
    "SchwabClient",
    "SourceManager",
    # analysis
    "Detector",
    "PatternAnalyzer",
    "PatternResult",
    "Backtester",
    "BacktestStats",
    "BacktestResult",
    # alerts
    "AlertManager",
    "RISK_EMOJI",
    "AlertChannel",
    "DiscordChannel",
    "SlackChannel",
    "EmailChannel",
    "MultiChannelDispatcher",
    # dashboard
    "HealthServer",
    "DashboardServer",
]
