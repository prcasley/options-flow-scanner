"""Tests for multi-channel alert dispatch."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.channels import (
    AlertChannel,
    DiscordChannel,
    SlackChannel,
    EmailChannel,
    MultiChannelDispatcher,
)
from scanner.models import Signal


def _make_signal(ticker="AAPL", risk_score=4):
    return Signal(
        timestamp=datetime(2025, 3, 15, 10, 30),
        ticker=ticker,
        strike=220.0,
        expiry="2025-03-21",
        contract_type="call",
        volume=5000,
        open_interest=1000,
        estimated_premium=1_500_000.0,
        risk_score=risk_score,
        signal_types=["volume spike", "bullish sweep"],
        description=f"{ticker} 220C 3/21 — test signal",
        volume_ratio=10.0,
        oi_ratio=4.0,
        last_price=3.0,
    )


class TestDiscordChannel:
    async def test_send_skips_empty_url(self):
        ch = DiscordChannel("")
        # Should not raise
        await ch.send("test message")

    async def test_send_truncates_long_message(self):
        ch = DiscordChannel("https://discord.com/api/webhooks/test")
        long_msg = "x" * 3000

        with patch("scanner.channels.aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.status = 204
            mock_post = AsyncMock(return_value=mock_resp)
            mock_post.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_post.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            mock_session_cls.return_value = mock_session

            await ch.send(long_msg)
            call_args = mock_session.post.call_args
            sent_content = call_args[1]["json"]["content"]
            assert len(sent_content) <= 1993  # 1990 + "..."

    async def test_send_batch(self):
        ch = DiscordChannel("https://discord.com/api/webhooks/test")
        ch.send = AsyncMock()
        signals = [_make_signal() for _ in range(3)]
        await ch.send_batch(signals)
        ch.send.assert_called_once()


class TestSlackChannel:
    async def test_send_skips_empty_url(self):
        ch = SlackChannel("")
        await ch.send("test message")

    async def test_send_batch(self):
        ch = SlackChannel("https://hooks.slack.com/services/test")
        ch.send = AsyncMock()
        signals = [_make_signal() for _ in range(3)]
        await ch.send_batch(signals)
        ch.send.assert_called_once()


class TestEmailChannel:
    def test_send_email_with_tls(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=587,
            username="user",
            password="pass",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
            use_tls=True,
        )
        with patch("scanner.channels.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            ch._send_email("Test Subject", "Test Body")
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("user", "pass")
            mock_server.send_message.assert_called_once()

    def test_send_email_without_tls(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=25,
            username="user",
            password="pass",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
            use_tls=False,
        )
        with patch("scanner.channels.smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            ch._send_email("Test Subject", "Test Body")
            mock_server.starttls.assert_not_called()
            mock_server.login.assert_called_once()

    async def test_send_handles_error(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com", smtp_port=587,
            username="user", password="pass",
            from_addr="from@example.com", to_addrs=["to@example.com"],
        )
        with patch.object(ch, "_send_email", side_effect=Exception("SMTP error")):
            # Should not raise
            await ch.send("test content")

    async def test_send_batch_empty(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com", smtp_port=587,
            username="user", password="pass",
            from_addr="from@example.com", to_addrs=["to@example.com"],
        )
        # Empty signals should return early
        await ch.send_batch([])


class TestMultiChannelDispatcher:
    async def test_dispatch_to_multiple_channels(self):
        d = MultiChannelDispatcher()
        ch1 = AsyncMock(spec=AlertChannel)
        ch2 = AsyncMock(spec=AlertChannel)
        d.add_channel(ch1)
        d.add_channel(ch2)

        await d.dispatch("test message")
        ch1.send.assert_called_once_with("test message")
        ch2.send.assert_called_once_with("test message")

    async def test_dispatch_signals(self):
        d = MultiChannelDispatcher()
        ch = AsyncMock(spec=AlertChannel)
        d.add_channel(ch)
        signals = [_make_signal()]

        await d.dispatch_signals(signals)
        ch.send_batch.assert_called_once_with(signals)

    async def test_dispatch_handles_channel_error(self):
        d = MultiChannelDispatcher()
        failing_ch = AsyncMock(spec=AlertChannel)
        failing_ch.send = AsyncMock(side_effect=Exception("Channel down"))
        ok_ch = AsyncMock(spec=AlertChannel)
        d.add_channel(failing_ch)
        d.add_channel(ok_ch)

        await d.dispatch("test")
        # Second channel should still be called
        ok_ch.send.assert_called_once()

    async def test_empty_dispatcher(self):
        d = MultiChannelDispatcher()
        # Should not raise with no channels
        await d.dispatch("test")
        await d.dispatch_signals([])
