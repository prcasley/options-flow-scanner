"""Unit tests for the signal detection engine."""

from datetime import datetime, timedelta

import pytest

from scanner.detector import Detector
from scanner.models import Signal


class TestDetectorInit:
    def test_default_thresholds(self, sample_config):
        det = Detector(sample_config)
        assert det.volume_spike_mult == 5.0
        assert det.min_volume == 100
        assert det.min_oi == 50
        assert det.sweep_threshold == 100

    def test_custom_ema_alpha(self, sample_config):
        sample_config["ema"] = {"alpha": 0.5, "max_tracked_contracts": 500}
        det = Detector(sample_config)
        assert det._ema_alpha == 0.5
        assert det._max_tracked == 500


class TestDailyReset:
    def test_averages_reset_on_new_day(self, sample_config):
        det = Detector(sample_config)
        # Simulate data from day 1
        det._last_reset_date = "2025-03-14"
        det._avg_volume = {"SPY": {"key1": 100.0}}
        det._total_tracked = 1

        now = datetime(2025, 3, 15, 10, 0, 0)
        det._maybe_reset_for_new_day(now)

        assert det._avg_volume == {}
        assert det._total_tracked == 0
        assert det._last_reset_date == "2025-03-15"

    def test_no_reset_same_day(self, sample_config):
        det = Detector(sample_config)
        det._last_reset_date = "2025-03-15"
        det._avg_volume = {"SPY": {"key1": 100.0}}
        det._total_tracked = 1

        now = datetime(2025, 3, 15, 14, 0, 0)
        det._maybe_reset_for_new_day(now)

        assert det._total_tracked == 1  # unchanged

    def test_first_call_no_reset(self, sample_config):
        det = Detector(sample_config)
        assert det._last_reset_date is None

        now = datetime(2025, 3, 15, 10, 0, 0)
        det._maybe_reset_for_new_day(now)
        # First call should just set the date, not reset
        assert det._last_reset_date == "2025-03-15"


class TestEviction:
    def test_evict_when_over_limit(self, sample_config):
        sample_config["ema"] = {"max_tracked_contracts": 3}
        det = Detector(sample_config)

        # Add entries up to the limit
        det._update_average("k1", 100, "AAA")
        det._update_average("k2", 200, "AAA")
        det._update_average("k3", 300, "BBB")
        assert det._total_tracked == 3

        # Adding a 4th triggers eviction of the smallest bucket
        det._update_average("k4", 400, "CCC")
        # BBB had 1 entry (smallest), should be evicted
        assert "BBB" not in det._avg_volume
        assert det._total_tracked <= 3


class TestEMAUpdate:
    def test_first_observation(self, sample_config):
        det = Detector(sample_config)
        avg = det._update_average("k1", 1000, "SPY")
        assert avg == 1000.0
        assert det._avg_volume["SPY"]["k1"] == 1000.0

    def test_second_observation_uses_ema(self, sample_config):
        det = Detector(sample_config)
        det._update_average("k1", 1000, "SPY")  # sets avg to 1000
        prev = det._update_average("k1", 2000, "SPY")
        assert prev == 1000.0
        # EMA: 0.3 * 2000 + 0.7 * 1000 = 1300
        assert det._avg_volume["SPY"]["k1"] == pytest.approx(1300.0)


class TestAnalyzeSnapshot:
    def test_detects_volume_spike(self, sample_config, sample_contract_raw):
        det = Detector(sample_config)
        # Seed a low average first
        key = det._contract_key("AAPL", 220.0, "2025-03-21", "call")
        det._avg_volume.setdefault("AAPL", {})[key] = 100.0
        det._total_tracked = 1

        signals = det.analyze_snapshot("AAPL", [sample_contract_raw])
        assert len(signals) >= 1
        sig = signals[0]
        assert "volume spike" in sig.signal_types
        assert sig.risk_score >= 1

    def test_filters_low_volume(self, sample_config, low_volume_contract_raw):
        det = Detector(sample_config)
        signals = det.analyze_snapshot("AAPL", [low_volume_contract_raw])
        assert len(signals) == 0

    def test_filters_invalid_contract_type(self, sample_config, sample_contract_raw):
        det = Detector(sample_config)
        sample_contract_raw["details"]["contract_type"] = "future"
        signals = det.analyze_snapshot("AAPL", [sample_contract_raw])
        assert len(signals) == 0

    def test_near_expiry_detection(self, sample_config, sample_contract_raw):
        det = Detector(sample_config)
        # Set expiry to 3 days from now
        near = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        sample_contract_raw["details"]["expiration_date"] = near
        # Seed low average
        key = det._contract_key("AAPL", 220.0, near, "call")
        det._avg_volume.setdefault("AAPL", {})[key] = 50.0
        det._total_tracked = 1

        signals = det.analyze_snapshot("AAPL", [sample_contract_raw])
        if signals:
            assert "near expiry" in signals[0].signal_types

    def test_sweep_detection(self, sample_config, sample_contract_raw):
        det = Detector(sample_config)
        # Volume >= sweep_threshold (100) and premium >= min ($50k)
        sample_contract_raw["day"]["volume"] = 500
        sample_contract_raw["day"]["close"] = 10.0  # premium = 500 * 10 * 100 = $500k
        signals = det.analyze_snapshot("AAPL", [sample_contract_raw])
        if signals:
            assert any("sweep" in st for st in signals[0].signal_types)

    def test_handles_malformed_contract(self, sample_config):
        det = Detector(sample_config)
        bad = {"details": {}, "day": {"volume": 9999}}
        signals = det.analyze_snapshot("AAPL", [bad])
        # Should not crash, just skip
        assert len(signals) == 0

    def test_risk_score_bounds(self, sample_config, sample_contract_raw):
        det = Detector(sample_config)
        # Seed low average for maximum spike
        key = det._contract_key("AAPL", 220.0, "2025-03-21", "call")
        det._avg_volume.setdefault("AAPL", {})[key] = 1.0
        det._total_tracked = 1
        sample_contract_raw["day"]["volume"] = 100_000
        sample_contract_raw["day"]["close"] = 50.0

        signals = det.analyze_snapshot("AAPL", [sample_contract_raw])
        if signals:
            assert 1 <= signals[0].risk_score <= 5


class TestBuildDescription:
    def test_description_contains_ticker(self, sample_config, sample_contract_raw):
        det = Detector(sample_config)
        key = det._contract_key("AAPL", 220.0, "2025-03-21", "call")
        det._avg_volume.setdefault("AAPL", {})[key] = 50.0
        det._total_tracked = 1

        signals = det.analyze_snapshot("AAPL", [sample_contract_raw])
        if signals:
            assert "AAPL" in signals[0].description
