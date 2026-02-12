"""Unit tests for the alert delivery system."""

import csv
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from scanner.alerts import AlertManager, RISK_EMOJI
from scanner.models import Signal


@pytest.fixture
def tmp_csv(tmp_path):
    return str(tmp_path / "test_alerts.csv")


@pytest.fixture
def alert_mgr(tmp_csv):
    return AlertManager(webhook_url="", csv_path=tmp_csv)


@pytest.fixture
def alert_mgr_with_webhook(tmp_csv):
    return AlertManager(
        webhook_url="https://discord.com/api/webhooks/test/fake",
        csv_path=tmp_csv,
    )


class TestCSVLogging:
    def test_csv_created_with_header(self, tmp_csv):
        AlertManager(webhook_url="", csv_path=tmp_csv)
        assert Path(tmp_csv).exists()
        with open(tmp_csv) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert "timestamp" in header
            assert "ticker" in header

    def test_log_csv_writes_signal(self, alert_mgr, sample_signal, tmp_csv):
        alert_mgr._log_csv(sample_signal)
        with open(tmp_csv) as f:
            reader = csv.reader(f)
            header = next(reader)
            row = next(reader)
            assert row[1] == "AAPL"
            assert "220" in row[2]

    def test_csv_flush_on_write(self, alert_mgr, sample_signal, tmp_csv):
        """Verify data is flushed to disk immediately."""
        alert_mgr._log_csv(sample_signal)
        # Read back immediately — data should be there
        with open(tmp_csv) as f:
            content = f.read()
            assert "AAPL" in content

    def test_csv_parent_dirs_created(self, tmp_path):
        nested = str(tmp_path / "a" / "b" / "alerts.csv")
        AlertManager(webhook_url="", csv_path=nested)
        assert Path(nested).exists()


class TestDiscordPosting:
    @pytest.mark.asyncio
    async def test_skip_when_no_webhook(self, alert_mgr, sample_signal):
        """Should not raise when webhook_url is empty."""
        await alert_mgr.send_signal(sample_signal)

    @pytest.mark.asyncio
    async def test_post_discord_sends_request(self, alert_mgr_with_webhook):
        with patch("scanner.alerts.aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.status = 204
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)

            mock_post = MagicMock()
            mock_post.return_value = mock_resp

            mock_session = AsyncMock()
            mock_session.post = mock_post
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            await alert_mgr_with_webhook._post_discord("Test message")
            mock_session.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_truncates_long_messages(self, alert_mgr_with_webhook):
        long_msg = "x" * 3000
        with patch("scanner.alerts.aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.status = 204
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_resp)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            await alert_mgr_with_webhook._post_discord(long_msg)
            call_args = mock_session.post.call_args
            sent_content = call_args[1]["json"]["content"]
            assert len(sent_content) <= 2000


class TestBatchSending:
    @pytest.mark.asyncio
    async def test_send_signals_batches(self, alert_mgr, sample_signal):
        """Verify signals are batched in groups of 10."""
        signals = [sample_signal] * 25
        alert_mgr._post_discord = AsyncMock()
        await alert_mgr.send_signals(signals)
        # 25 signals / 10 per batch = 3 Discord calls
        assert alert_mgr._post_discord.call_count == 3


class TestFormatting:
    def test_format_signal_contains_risk(self, alert_mgr, sample_signal):
        formatted = alert_mgr._format_signal(sample_signal)
        assert "[Risk 4/5]" in formatted

    def test_format_batch_header(self, alert_mgr, sample_signal):
        formatted = alert_mgr._format_batch([sample_signal])
        assert "Options Flow Alert" in formatted

    def test_risk_emoji_mapping(self):
        assert 1 in RISK_EMOJI
        assert 5 in RISK_EMOJI
        assert len(RISK_EMOJI) == 5


class TestDailySummary:
    @pytest.mark.asyncio
    async def test_summary_with_no_signals(self, alert_mgr):
        alert_mgr._post_discord = AsyncMock()
        await alert_mgr.send_daily_summary([], "2025-03-15")
        alert_mgr._post_discord.assert_called_once()
        msg = alert_mgr._post_discord.call_args[0][0]
        assert "No significant signals" in msg

    @pytest.mark.asyncio
    async def test_summary_with_signals(self, alert_mgr, sample_signal):
        alert_mgr._post_discord = AsyncMock()
        await alert_mgr.send_daily_summary([sample_signal], "2025-03-15")
        msg = alert_mgr._post_discord.call_args[0][0]
        assert "Daily Summary" in msg
        assert "2025-03-15" in msg
