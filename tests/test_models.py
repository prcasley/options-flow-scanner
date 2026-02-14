"""Tests for scanner/models.py — Signal and OptionsContract data classes."""

from datetime import datetime

from scanner.models import OptionsContract, Signal


class TestOptionsContract:
    def test_basic_creation(self):
        c = OptionsContract(
            ticker="AAPL",
            strike=200.0,
            expiry="2026-06-20",
            contract_type="call",
            volume=1000,
            open_interest=500,
            last_price=5.50,
        )
        assert c.ticker == "AAPL"
        assert c.strike == 200.0
        assert c.contract_type == "call"
        assert c.implied_volatility is None
        assert c.day_change is None

    def test_optional_fields(self):
        c = OptionsContract(
            ticker="SPY",
            strike=500.0,
            expiry="2026-03-21",
            contract_type="put",
            volume=200,
            open_interest=50,
            last_price=3.0,
            implied_volatility=0.35,
            day_change=-0.5,
        )
        assert c.implied_volatility == 0.35
        assert c.day_change == -0.5


class TestSignal:
    def _make_signal(self, **overrides) -> Signal:
        defaults = dict(
            timestamp=datetime(2026, 2, 14, 10, 30, 0),
            ticker="NVDA",
            strike=800.0,
            expiry="2026-03-21",
            contract_type="call",
            volume=5000,
            open_interest=200,
            estimated_premium=2_500_000,
            risk_score=5,
            signal_types=["volume spike", "bullish sweep"],
            description="NVDA 800C 3/21 — 10x avg volume, $2.5M premium",
            volume_ratio=10.0,
            oi_ratio=25.0,
            last_price=5.0,
        )
        defaults.update(overrides)
        return Signal(**defaults)

    def test_contract_label_call(self):
        s = self._make_signal(
            ticker="AVGO", strike=220.0, expiry="2026-03-21", contract_type="call"
        )
        assert s.contract_label == "AVGO 220C 3/21"

    def test_contract_label_put(self):
        s = self._make_signal(
            ticker="SPY", strike=500.5, expiry="2026-12-05", contract_type="put"
        )
        assert s.contract_label == "SPY 500.5P 12/5"

    def test_contract_label_integer_strike(self):
        s = self._make_signal(strike=100.0)
        assert "100C" in s.contract_label

    def test_premium_str_millions(self):
        s = self._make_signal(estimated_premium=2_500_000)
        assert s.premium_str == "$2.5M"

    def test_premium_str_thousands(self):
        s = self._make_signal(estimated_premium=75_000)
        assert s.premium_str == "$75K"

    def test_premium_str_small(self):
        s = self._make_signal(estimated_premium=500)
        assert s.premium_str == "$500"

    def test_premium_str_boundary_million(self):
        s = self._make_signal(estimated_premium=1_000_000)
        assert s.premium_str == "$1.0M"

    def test_premium_str_boundary_thousand(self):
        s = self._make_signal(estimated_premium=1_000)
        assert s.premium_str == "$1K"

    def test_to_discord_line(self):
        s = self._make_signal()
        line = s.to_discord_line()
        assert "NVDA 800C 3/21" in line
        assert "10x avg volume" in line
        assert "$2.5M premium" in line
        assert "volume spike" in line
        assert "bullish sweep" in line

    def test_to_discord_line_low_volume_ratio(self):
        s = self._make_signal(volume_ratio=0.5)
        line = s.to_discord_line()
        # Should NOT include "x avg volume" when ratio <= 1
        assert "avg volume" not in line

    def test_to_csv_row_length(self):
        s = self._make_signal()
        row = s.to_csv_row()
        assert len(row) == len(Signal.csv_header())

    def test_to_csv_row_content(self):
        s = self._make_signal()
        row = s.to_csv_row()
        assert row[0] == s.timestamp.isoformat()
        assert row[1] == "NVDA"
        assert row[2] == 800.0
        assert row[4] == "call"
        assert row[8] == 5
        assert "volume spike" in row[9]
        assert "bullish sweep" in row[9]

    def test_csv_header(self):
        header = Signal.csv_header()
        assert "timestamp" in header
        assert "ticker" in header
        assert "risk_score" in header
        assert len(header) == 13

    def test_signal_default_values(self):
        s = Signal(
            timestamp=datetime.now(),
            ticker="TEST",
            strike=100.0,
            expiry="2026-01-01",
            contract_type="call",
            volume=100,
            open_interest=50,
            estimated_premium=50_000,
            risk_score=3,
        )
        assert s.signal_types == []
        assert s.description == ""
        assert s.volume_ratio == 0.0
        assert s.oi_ratio == 0.0
        assert s.last_price == 0.0
