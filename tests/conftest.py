"""Shared test fixtures."""

import pytest
import yaml
from pathlib import Path


@pytest.fixture
def sample_config():
    """Load the real config.yaml for tests."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def minimal_config():
    """Minimal config for unit tests that don't need full config."""
    return {
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
        "scan_interval_seconds": 60,
        "discovery": {"enabled": False},
        "market": {
            "open_hour": 9,
            "open_minute": 30,
            "close_hour": 16,
            "close_minute": 0,
            "timezone": "US/Eastern",
        },
        "daily_summary": {"enabled": False},
    }


def make_polygon_snapshot(
    strike: float = 200.0,
    expiry: str = "2026-06-20",
    contract_type: str = "call",
    volume: int = 500,
    open_interest: int = 100,
    close_price: float = 5.0,
    iv: float = 0.35,
) -> dict:
    """Build a fake Polygon-style options snapshot dict."""
    return {
        "details": {
            "strike_price": strike,
            "expiration_date": expiry,
            "contract_type": contract_type,
        },
        "day": {
            "volume": volume,
            "close": close_price,
        },
        "greeks": {
            "implied_volatility": iv,
        },
        "open_interest": open_interest,
    }
