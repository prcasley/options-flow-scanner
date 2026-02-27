"""Shared fixtures for the options flow scanner test suite."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.models import Signal


@pytest.fixture
def sample_config():
    """Minimal valid config for testing."""
    return {
        "scan_interval_seconds": 60,
        "rate_limit": {
            "calls_per_minute": 5,
            "retry_delay_seconds": 1,
            "max_retries": 2,
        },
        "thresholds": {
            "volume_spike_multiplier": 5.0,
            "min_volume": 100,
            "min_oi": 50,
            "high_volume_oi_ratio": 3.0,
            "min_estimated_premium_usd": 50_000,
            "sweep_size_threshold": 100,
        },
        "risk_scoring": {
            "volume_spike_weight": 0.3,
            "premium_weight": 0.25,
            "oi_ratio_weight": 0.2,
            "sweep_weight": 0.15,
            "near_expiry_weight": 0.1,
        },
        "watchlist": ["SPY", "AAPL"],
        "discovery": {"enabled": False, "max_tickers": 10},
        "market": {
            "open_hour": 9,
            "open_minute": 30,
            "close_hour": 16,
            "close_minute": 0,
            "timezone": "US/Eastern",
        },
        "daily_summary": {"enabled": True, "hour": 16, "minute": 15, "top_n": 5},
        "log_level": "DEBUG",
        "csv_log_path": "data/test_alerts.csv",
        "db_path": ":memory:",
    }


@pytest.fixture
def sample_signal():
    """A realistic Signal object for testing."""
    return Signal(
        timestamp=datetime(2025, 3, 15, 10, 30, 0),
        ticker="AAPL",
        strike=220.0,
        expiry="2025-03-21",
        contract_type="call",
        volume=5000,
        open_interest=1200,
        estimated_premium=1_500_000.0,
        risk_score=4,
        signal_types=["volume spike", "bullish sweep"],
        description="AAPL 220C 3/21 — 12x avg volume, $1.5M premium, volume spike, bullish sweep",
        volume_ratio=12.0,
        oi_ratio=4.2,
        last_price=3.0,
    )


@pytest.fixture
def sample_contract_raw():
    """Raw Polygon API snapshot dict for a single options contract."""
    return {
        "details": {
            "strike_price": 220.0,
            "expiration_date": "2025-03-21",
            "contract_type": "call",
            "ticker": "O:AAPL250321C00220000",
        },
        "day": {
            "volume": 5000,
            "close": 3.0,
            "open": 2.5,
            "high": 3.2,
            "low": 2.4,
        },
        "open_interest": 1200,
        "greeks": {
            "implied_volatility": 0.45,
            "delta": 0.65,
            "gamma": 0.03,
            "theta": -0.12,
            "vega": 0.15,
        },
    }


@pytest.fixture
def low_volume_contract_raw():
    """Contract that should be filtered out due to low volume."""
    return {
        "details": {
            "strike_price": 150.0,
            "expiration_date": "2025-06-20",
            "contract_type": "put",
            "ticker": "O:AAPL250620P00150000",
        },
        "day": {"volume": 10, "close": 0.50},
        "open_interest": 500,
        "greeks": {},
    }


@pytest.fixture
def mock_polygon_client():
    """Mock PolygonClient with sensible defaults."""
    client = AsyncMock()
    client.get_options_snapshot = AsyncMock(return_value=[])
    client.get_most_active = AsyncMock(return_value=[])
    client.get_gainers_losers = AsyncMock(return_value=[])
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_alert_manager():
    """Mock AlertManager."""
    mgr = AsyncMock()
    mgr.send_signal = AsyncMock()
    mgr.send_signals = AsyncMock()
    mgr.send_daily_summary = AsyncMock()
    return mgr


@pytest.fixture
def mock_database():
    """Mock SignalDatabase."""
    db = AsyncMock()
    db.initialize = AsyncMock()
    db.insert_signal = AsyncMock()
    db.insert_signals = AsyncMock()
    db.get_today_signals = AsyncMock(return_value=[])
    db.get_ticker_history = AsyncMock(return_value=[])
    db.close = AsyncMock()
    return db
