"""Tests for scanner/detector.py — signal detection engine."""

from datetime import datetime, timedelta

from scanner.detector import Detector
from tests.conftest import make_polygon_snapshot


class TestDetector:
    def _make_detector(self, **overrides) -> Detector:
        config = {
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
        }
        config["thresholds"].update(overrides)
        return Detector(config)

    # ── Filter tests ──

    def test_below_min_volume_filtered(self):
        """Contracts with volume below threshold should be ignored."""
        d = self._make_detector()
        snap = make_polygon_snapshot(volume=50, close_price=20.0)  # 50 < 100
        signals = d.analyze_snapshot("SPY", [snap])
        assert len(signals) == 0

    def test_below_min_premium_filtered(self):
        """Contracts with premium below $50k should be ignored."""
        d = self._make_detector()
        # volume=100, close=1.0 => premium = 100 * 1.0 * 100 = $10,000
        snap = make_polygon_snapshot(volume=100, close_price=1.0)
        signals = d.analyze_snapshot("SPY", [snap])
        assert len(signals) == 0

    def test_invalid_contract_type_filtered(self):
        """Contracts with unknown type should be ignored."""
        d = self._make_detector()
        snap = make_polygon_snapshot(volume=500, close_price=10.0)
        snap["details"]["contract_type"] = "unknown"
        signals = d.analyze_snapshot("SPY", [snap])
        assert len(signals) == 0

    # ── Volume spike detection ──

    def test_volume_spike_detected(self):
        """A contract seen twice — second time with 10x volume — triggers spike."""
        d = self._make_detector()
        # First observation: establishes baseline (volume=100, price=10 => $100k premium)
        snap1 = make_polygon_snapshot(
            strike=200.0, volume=100, close_price=10.0, open_interest=200
        )
        d.analyze_snapshot("SPY", [snap1])

        # Second observation: 10x volume spike
        snap2 = make_polygon_snapshot(
            strike=200.0, volume=1000, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap2])
        assert len(signals) >= 1
        sig = signals[0]
        assert "volume spike" in sig.signal_types
        assert sig.volume_ratio > 5.0

    def test_no_spike_on_first_observation(self):
        """First observation of a contract can't be a spike (avg == current)."""
        d = self._make_detector()
        # volume=500, price=10 => premium=$500k, passes filter
        # But vol_ratio == 1.0 on first observation
        snap = make_polygon_snapshot(
            strike=200.0, volume=500, close_price=10.0, open_interest=50
        )
        signals = d.analyze_snapshot("SPY", [snap])
        # It may still trigger on sweep or high vol/OI, but not volume spike
        for s in signals:
            assert "volume spike" not in s.signal_types

    # ── Sweep detection ──

    def test_sweep_detected_call(self):
        """Large volume call should be flagged as bullish sweep."""
        d = self._make_detector()
        snap = make_polygon_snapshot(
            contract_type="call", volume=500, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap])
        sweep_signals = [s for s in signals if "bullish sweep" in s.signal_types]
        assert len(sweep_signals) >= 1

    def test_sweep_detected_put(self):
        """Large volume put should be flagged as bearish sweep."""
        d = self._make_detector()
        snap = make_polygon_snapshot(
            contract_type="put", volume=500, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap])
        sweep_signals = [s for s in signals if "bearish sweep" in s.signal_types]
        assert len(sweep_signals) >= 1

    # ── High vol/OI detection ──

    def test_high_vol_oi_detected(self):
        """Volume/OI ratio >= 3.0 with sufficient OI should trigger."""
        d = self._make_detector()
        # volume=500, OI=100 => ratio=5.0
        snap = make_polygon_snapshot(
            volume=500, close_price=10.0, open_interest=100
        )
        signals = d.analyze_snapshot("SPY", [snap])
        vol_oi_signals = [s for s in signals if "high vol/OI" in s.signal_types]
        assert len(vol_oi_signals) >= 1

    def test_low_oi_not_flagged(self):
        """Volume/OI ratio high but OI below min_oi should not flag high vol/OI."""
        d = self._make_detector()
        # volume=500, OI=10 => ratio=50.0, but OI < min_oi(50)
        snap = make_polygon_snapshot(
            volume=500, close_price=10.0, open_interest=10
        )
        signals = d.analyze_snapshot("SPY", [snap])
        vol_oi_signals = [s for s in signals if "high vol/OI" in s.signal_types]
        assert len(vol_oi_signals) == 0

    # ── Near-expiry detection ──

    def test_near_expiry_detected(self):
        """Contract expiring within 7 days should be flagged."""
        d = self._make_detector()
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        snap = make_polygon_snapshot(
            expiry=tomorrow, volume=500, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap])
        expiry_signals = [s for s in signals if "near expiry" in s.signal_types]
        assert len(expiry_signals) >= 1

    def test_far_expiry_not_flagged(self):
        """Contract expiring in 30+ days should not flag near expiry."""
        d = self._make_detector()
        far_out = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
        snap = make_polygon_snapshot(
            expiry=far_out, volume=500, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap])
        expiry_signals = [s for s in signals if "near expiry" in s.signal_types]
        assert len(expiry_signals) == 0

    # ── Risk scoring ──

    def test_risk_score_range(self):
        """Risk score should always be between 1 and 5."""
        d = self._make_detector()
        snap = make_polygon_snapshot(
            volume=10000, close_price=50.0, open_interest=100
        )
        signals = d.analyze_snapshot("SPY", [snap])
        for s in signals:
            assert 1 <= s.risk_score <= 5

    def test_high_risk_score(self):
        """Extreme activity should produce a high risk score."""
        d = self._make_detector()
        # First establish a low baseline
        snap1 = make_polygon_snapshot(
            strike=300.0, volume=100, close_price=50.0, open_interest=100
        )
        d.analyze_snapshot("SPY", [snap1])

        # Now hit with extreme volume
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        snap2 = make_polygon_snapshot(
            strike=300.0, volume=10000, close_price=50.0,
            open_interest=100, expiry=tomorrow
        )
        signals = d.analyze_snapshot("SPY", [snap2])
        assert len(signals) >= 1
        assert signals[0].risk_score >= 4

    # ── EMA average tracking ──

    def test_ema_updates_correctly(self):
        """Running average should move towards new values."""
        d = self._make_detector()
        key = d._contract_key("SPY", 200.0, "2026-06-20", "call")

        avg1 = d._update_average(key, 100, "SPY")
        assert avg1 == 100.0  # First observation returns the value itself

        avg2 = d._update_average(key, 200, "SPY")
        assert avg2 == 100.0  # Returns prior average
        # New internal average: 0.3*200 + 0.7*100 = 130
        assert d._avg_volume["SPY"][key] == 130.0

    # ── Batch processing ──

    def test_analyze_multiple_contracts(self):
        """Should process a batch of contracts and return multiple signals."""
        d = self._make_detector()
        contracts = [
            make_polygon_snapshot(
                strike=200.0 + i * 10,
                volume=500,
                close_price=10.0,
                open_interest=200,
            )
            for i in range(5)
        ]
        signals = d.analyze_snapshot("SPY", contracts)
        # All should pass filters and produce signals
        assert len(signals) >= 1

    def test_malformed_contract_skipped(self):
        """Malformed data should be skipped gracefully, not crash."""
        d = self._make_detector()
        malformed = {"bad": "data"}
        good = make_polygon_snapshot(volume=500, close_price=10.0, open_interest=200)
        signals = d.analyze_snapshot("SPY", [malformed, good])
        # Should still get the good signal
        assert len(signals) >= 1

    # ── Description building ──

    def test_description_format(self):
        """Signal description should contain key info."""
        d = self._make_detector()
        snap = make_polygon_snapshot(
            strike=200.0, volume=500, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap])
        assert len(signals) >= 1
        desc = signals[0].description
        assert "SPY" in desc
        assert "200C" in desc
        assert "premium" in desc

    def test_signal_output_fields(self):
        """Signal should have all expected fields populated."""
        d = self._make_detector()
        snap = make_polygon_snapshot(
            strike=200.0, volume=500, close_price=10.0, open_interest=200
        )
        signals = d.analyze_snapshot("SPY", [snap])
        assert len(signals) >= 1
        s = signals[0]
        assert s.ticker == "SPY"
        assert s.strike == 200.0
        assert s.contract_type == "call"
        assert s.volume == 500
        assert s.open_interest == 200
        assert s.estimated_premium == 500 * 10.0 * 100  # $500,000
        assert len(s.signal_types) >= 1
