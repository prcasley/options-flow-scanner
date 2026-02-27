"""Unit tests for data models."""

from datetime import datetime

import pytest

from scanner.models import OptionsContract, Signal


class TestOptionsContract:
    def test_basic_creation(self):
        c = OptionsContract(
            ticker="AAPL", strike=220.0, expiry="2025-03-21",
            contract_type="call", volume=1000, open_interest=500,
            last_price=3.0,
        )
        assert c.ticker == "AAPL"
        assert c.implied_volatility is None
        assert c.day_change is None


class TestSignal:
    def test_contract_label_call(self):
        sig = Signal(
            timestamp=datetime(2025, 3, 15),
            ticker="AAPL", strike=220.0, expiry="2025-03-21",
            contract_type="call", volume=5000, open_interest=1200,
            estimated_premium=1_500_000.0, risk_score=4,
        )
        label = sig.contract_label
        assert "AAPL" in label
        assert "220C" in label
        assert "3/21" in label

    def test_contract_label_put(self):
        sig = Signal(
            timestamp=datetime(2025, 3, 15),
            ticker="SPY", strike=500.0, expiry="2025-06-20",
            contract_type="put", volume=1000, open_interest=300,
            estimated_premium=200_000.0, risk_score=2,
        )
        assert "500P" in sig.contract_label
        assert "6/20" in sig.contract_label

    def test_premium_str_millions(self):
        sig = Signal(
            timestamp=datetime(2025, 3, 15),
            ticker="AAPL", strike=220.0, expiry="2025-03-21",
            contract_type="call", volume=5000, open_interest=1200,
            estimated_premium=2_500_000.0, risk_score=4,
        )
        assert sig.premium_str == "$2.5M"

    def test_premium_str_thousands(self):
        sig = Signal(
            timestamp=datetime(2025, 3, 15),
            ticker="AAPL", strike=220.0, expiry="2025-03-21",
            contract_type="call", volume=500, open_interest=100,
            estimated_premium=75_000.0, risk_score=2,
        )
        assert sig.premium_str == "$75K"

    def test_premium_str_dollars(self):
        sig = Signal(
            timestamp=datetime(2025, 3, 15),
            ticker="AAPL", strike=220.0, expiry="2025-03-21",
            contract_type="call", volume=10, open_interest=50,
            estimated_premium=500.0, risk_score=1,
        )
        assert sig.premium_str == "$500"

    def test_to_csv_row(self, sample_signal):
        row = sample_signal.to_csv_row()
        assert len(row) == len(Signal.csv_header())
        assert row[1] == "AAPL"

    def test_csv_header_matches_row_length(self, sample_signal):
        assert len(sample_signal.to_csv_row()) == len(Signal.csv_header())

    def test_to_discord_line(self, sample_signal):
        line = sample_signal.to_discord_line()
        assert "AAPL" in line
        assert "avg volume" in line

    def test_default_field_values(self):
        sig = Signal(
            timestamp=datetime(2025, 3, 15),
            ticker="TEST", strike=100.0, expiry="2025-03-21",
            contract_type="call", volume=100, open_interest=50,
            estimated_premium=10_000.0, risk_score=1,
        )
        assert sig.signal_types == []
        assert sig.description == ""
        assert sig.volume_ratio == 0.0
        assert sig.oi_ratio == 0.0
        assert sig.last_price == 0.0
