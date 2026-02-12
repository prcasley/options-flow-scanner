"""Unit tests for configuration validation."""

import pytest

from main import validate_config


@pytest.fixture
def valid_config():
    return {
        "scan_interval_seconds": 60,
        "rate_limit": {"calls_per_minute": 5, "retry_delay_seconds": 15, "max_retries": 3},
        "thresholds": {
            "volume_spike_multiplier": 5.0,
            "min_volume": 100,
            "min_oi": 50,
            "high_volume_oi_ratio": 3.0,
            "min_estimated_premium_usd": 50000,
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
        "market": {"open_hour": 9, "close_hour": 16},
    }


class TestValidConfig:
    def test_valid_config_no_errors(self, valid_config):
        errors = validate_config(valid_config)
        assert errors == []


class TestWatchlistValidation:
    def test_missing_watchlist(self, valid_config):
        del valid_config["watchlist"]
        errors = validate_config(valid_config)
        assert any("watchlist" in e for e in errors)

    def test_empty_watchlist(self, valid_config):
        valid_config["watchlist"] = []
        errors = validate_config(valid_config)
        assert any("watchlist" in e for e in errors)


class TestScanIntervalValidation:
    def test_too_small_interval(self, valid_config):
        valid_config["scan_interval_seconds"] = 5
        errors = validate_config(valid_config)
        assert any("scan_interval" in e for e in errors)

    def test_negative_interval(self, valid_config):
        valid_config["scan_interval_seconds"] = -1
        errors = validate_config(valid_config)
        assert any("scan_interval" in e for e in errors)

    def test_string_interval(self, valid_config):
        valid_config["scan_interval_seconds"] = "fast"
        errors = validate_config(valid_config)
        assert any("scan_interval" in e for e in errors)


class TestRateLimitValidation:
    def test_invalid_rate_limit_type(self, valid_config):
        valid_config["rate_limit"] = "bad"
        errors = validate_config(valid_config)
        assert any("rate_limit" in e for e in errors)

    def test_zero_calls_per_minute(self, valid_config):
        valid_config["rate_limit"]["calls_per_minute"] = 0
        errors = validate_config(valid_config)
        assert any("calls_per_minute" in e for e in errors)


class TestThresholdValidation:
    def test_negative_threshold(self, valid_config):
        valid_config["thresholds"]["min_volume"] = -10
        errors = validate_config(valid_config)
        assert any("min_volume" in e for e in errors)

    def test_string_threshold(self, valid_config):
        valid_config["thresholds"]["volume_spike_multiplier"] = "high"
        errors = validate_config(valid_config)
        assert any("volume_spike_multiplier" in e for e in errors)


class TestRiskScoringValidation:
    def test_weights_not_summing_to_one(self, valid_config):
        valid_config["risk_scoring"]["volume_spike_weight"] = 0.9
        errors = validate_config(valid_config)
        assert any("weights sum" in e for e in errors)


class TestMarketHoursValidation:
    def test_invalid_open_hour(self, valid_config):
        valid_config["market"]["open_hour"] = 25
        errors = validate_config(valid_config)
        assert any("open_hour" in e for e in errors)

    def test_negative_hour(self, valid_config):
        valid_config["market"]["close_hour"] = -1
        errors = validate_config(valid_config)
        assert any("close_hour" in e for e in errors)
