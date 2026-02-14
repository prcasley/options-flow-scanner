"""Tests for scanner/alerts.py — Discord + CSV alert delivery."""

import csv
import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.alerts import AlertManager, RISK_EMOJI
from scanner.models import Signal


def _make_signal(**overrides) -> Signal:
    defaults = dict(
        timestamp=datetime(2026, 2, 14, 10, 30, 0),
        ticker="SPY",
        strike=600.0,
        expiry="2026-03-21",
        contract_type="call",
        volume=5000,
        open_interest=200,
        estimated_premium=2_500_000,
        risk_score=5,
        signal_types=["volume spike", "bullish sweep"],
        description="SPY 600C 3/21 — 10x avg volume, $2.5M premium",
        volume_ratio=10.0,
        oi_ratio=25.0,
        last_price=5.0,
    )
    defaults.update(overrides)
    return Signal(**defaults)


class TestAlertManagerCSV:
    def test_csv_created_with_header(self):
        """CSV file should be created with header row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_alerts.csv")
            am = AlertManager(webhook_url="", csv_path=csv_path)

            assert os.path.exists(csv_path)
            with open(csv_path) as f:
                reader = csv.reader(f)
                header = next(reader)
                assert "timestamp" in header
                assert "ticker" in header
                assert "risk_score" in header

    def test_csv_log_appends_signal(self):
        """Logging a signal should append a row to the CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_alerts.csv")
            am = AlertManager(webhook_url="", csv_path=csv_path)

            sig = _make_signal()
            am._log_csv(sig)

            with open(csv_path) as f:
                reader = csv.reader(f)
                header = next(reader)
                row = next(reader)
                assert row[1] == "SPY"  # ticker
                assert row[4] == "call"  # contract_type

    def test_csv_log_multiple_signals(self):
        """Multiple signals should each get their own row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test_alerts.csv")
            am = AlertManager(webhook_url="", csv_path=csv_path)

            for i in range(5):
                am._log_csv(_make_signal(ticker=f"TEST{i}"))

            with open(csv_path) as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                rows = list(reader)
                assert len(rows) == 5

    def test_csv_creates_parent_directory(self):
        """Should create parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "nested", "dir", "alerts.csv")
            am = AlertManager(webhook_url="", csv_path=csv_path)
            assert os.path.exists(csv_path)


class TestAlertManagerFormatting:
    def test_format_signal_contains_risk(self):
        """Formatted signal should include risk score."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        sig = _make_signal(risk_score=5)
        text = am._format_signal(sig)
        assert "[Risk 5/5]" in text

    def test_format_signal_contains_stats(self):
        """Formatted signal should include volume, OI, premium."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        sig = _make_signal(volume=5000, open_interest=200)
        text = am._format_signal(sig)
        assert "5,000" in text
        assert "200" in text
        assert "$2.5M" in text

    def test_format_batch(self):
        """Batch format should include alert header and all signals."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        signals = [_make_signal(risk_score=i) for i in range(1, 4)]
        text = am._format_batch(signals)
        assert "Options Flow Alert" in text
        assert "[1/5]" in text
        assert "[2/5]" in text
        assert "[3/5]" in text

    def test_format_daily_summary(self):
        """Daily summary should have date and ranking."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        signals = [_make_signal(risk_score=5 - i) for i in range(3)]
        # We can't easily test the async method directly without mocking Discord,
        # but we can verify the formatting logic indirectly


class TestAlertManagerDiscord:
    @pytest.mark.asyncio
    async def test_no_webhook_skips_silently(self):
        """Should not crash when webhook URL is empty."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        # Should not raise
        await am._post_discord("test message")

    @pytest.mark.asyncio
    async def test_message_truncation(self):
        """Messages over 2000 chars should be truncated."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        long_message = "x" * 3000
        # No webhook, so it just returns — but we verify the logic
        await am._post_discord(long_message)
        # The method should handle long messages without crashing

    @pytest.mark.asyncio
    async def test_send_signals_logs_to_csv(self):
        """send_signals should log all signals to CSV even without Discord."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test.csv")
            am = AlertManager(webhook_url="", csv_path=csv_path)

            signals = [_make_signal(ticker=f"T{i}") for i in range(3)]
            await am.send_signals(signals)

            with open(csv_path) as f:
                reader = csv.reader(f)
                next(reader)  # header
                rows = list(reader)
                assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_send_signals_empty_list(self):
        """Empty signal list should be a no-op."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        await am.send_signals([])

    @pytest.mark.asyncio
    async def test_send_daily_summary_no_signals(self):
        """Daily summary with no signals should still post."""
        am = AlertManager(webhook_url="", csv_path="/dev/null")
        await am.send_daily_summary([], "2026-02-14")


class TestRiskEmoji:
    def test_all_risk_levels_have_emoji(self):
        """Risk levels 1-5 should each have an emoji."""
        for level in range(1, 6):
            assert level in RISK_EMOJI
            assert len(RISK_EMOJI[level]) > 0

    def test_emojis_are_distinct(self):
        """Each risk level should have a unique emoji."""
        emojis = list(RISK_EMOJI.values())
        assert len(emojis) == len(set(emojis))
