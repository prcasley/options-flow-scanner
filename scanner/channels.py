"""Multi-channel alert delivery: Discord, Slack, and email."""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiohttp

from .models import Signal

logger = logging.getLogger(__name__)

RISK_EMOJI = {1: "\u26aa", 2: "\ud83d\udfe2", 3: "\ud83d\udfe1", 4: "\ud83d\udfe0", 5: "\ud83d\udd34"}


class AlertChannel:
    """Base class for alert channels."""

    async def send(self, content: str):
        raise NotImplementedError

    async def send_batch(self, signals: list[Signal]):
        raise NotImplementedError


class DiscordChannel(AlertChannel):
    """Send alerts via Discord webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, content: str):
        if not self.webhook_url:
            return
        if len(content) > 1990:
            content = content[:1990] + "..."
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json={"content": content},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 204:
                        logger.debug("Discord alert sent")
                    else:
                        text = await resp.text()
                        logger.error("Discord error %d: %s", resp.status, text[:200])
        except Exception as e:
            logger.error("Discord send failed: %s", e)

    async def send_batch(self, signals: list[Signal]):
        for i in range(0, len(signals), 10):
            batch = signals[i:i + 10]
            lines = ["**\ud83d\udea8 Options Flow Alert**\n"]
            for s in batch:
                emoji = RISK_EMOJI.get(s.risk_score, "\u26aa")
                lines.append(
                    f"{emoji} **[{s.risk_score}/5]** {s.description}\n"
                    f"> Vol: {s.volume:,} | OI: {s.open_interest:,} | "
                    f"Premium: {s.premium_str}"
                )
            await self.send("\n".join(lines))


class SlackChannel(AlertChannel):
    """Send alerts via Slack incoming webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send(self, content: str):
        if not self.webhook_url:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json={"text": content},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.debug("Slack alert sent")
                    else:
                        text = await resp.text()
                        logger.error("Slack error %d: %s", resp.status, text[:200])
        except Exception as e:
            logger.error("Slack send failed: %s", e)

    async def send_batch(self, signals: list[Signal]):
        for i in range(0, len(signals), 10):
            batch = signals[i:i + 10]
            blocks = [":rotating_light: *Options Flow Alert*\n"]
            for s in batch:
                risk_bar = "\u2588" * s.risk_score + "\u2591" * (5 - s.risk_score)
                blocks.append(
                    f"*[{risk_bar}]* {s.description}\n"
                    f"    Vol: {s.volume:,} | OI: {s.open_interest:,} | "
                    f"Premium: {s.premium_str}"
                )
            await self.send("\n".join(blocks))


class EmailChannel(AlertChannel):
    """Send alert digests via SMTP email."""

    def __init__(self, smtp_host: str, smtp_port: int, username: str,
                 password: str, from_addr: str, to_addrs: list[str],
                 use_tls: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    async def send(self, content: str):
        try:
            self._send_email("Options Flow Alert", content)
        except Exception as e:
            logger.error("Email send failed: %s", e)

    async def send_batch(self, signals: list[Signal]):
        if not signals:
            return
        lines = ["Options Flow Scanner - Signal Alert\n"]
        lines.append(f"{'='*60}\n")
        for s in signals:
            lines.append(
                f"[Risk {s.risk_score}/5] {s.description}\n"
                f"  Volume: {s.volume:,} | OI: {s.open_interest:,} | "
                f"Premium: {s.premium_str} | V/OI: {s.oi_ratio:.1f}\n"
            )
        lines.append(f"\n{'='*60}")
        lines.append(f"Total signals: {len(signals)}")
        try:
            self._send_email(
                f"Options Flow: {len(signals)} signals detected",
                "\n".join(lines),
            )
        except Exception as e:
            logger.error("Email batch send failed: %s", e)

    def _send_email(self, subject: str, body: str):
        msg = MIMEMultipart()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if self.use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.username, self.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.login(self.username, self.password)
                server.send_message(msg)
        logger.debug("Email sent to %s", self.to_addrs)


class MultiChannelDispatcher:
    """Routes alerts to multiple configured channels."""

    def __init__(self):
        self.channels: list[AlertChannel] = []

    def add_channel(self, channel: AlertChannel):
        self.channels.append(channel)

    async def dispatch(self, content: str):
        for ch in self.channels:
            try:
                await ch.send(content)
            except Exception as e:
                logger.error("Channel %s failed: %s", type(ch).__name__, e)

    async def dispatch_signals(self, signals: list[Signal]):
        for ch in self.channels:
            try:
                await ch.send_batch(signals)
            except Exception as e:
                logger.error("Channel %s batch failed: %s", type(ch).__name__, e)
