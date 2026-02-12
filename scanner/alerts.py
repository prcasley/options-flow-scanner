"""Alert delivery: Discord webhooks and CSV logging."""

import csv
import logging
import os
from pathlib import Path

import aiohttp

from .models import Signal

logger = logging.getLogger(__name__)

RISK_EMOJI = {1: "\u26aa", 2: "\ud83d\udfe2", 3: "\ud83d\udfe1", 4: "\ud83d\udfe0", 5: "\ud83d\udd34"}


class AlertManager:
    def __init__(self, webhook_url: str, csv_path: str):
        self.webhook_url = webhook_url
        self.csv_path = csv_path
        self._ensure_csv()

    def _ensure_csv(self):
        path = Path(self.csv_path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(Signal.csv_header())

    async def send_signal(self, signal: Signal):
        """Send a single signal alert to Discord and log to CSV."""
        await self._post_discord(self._format_signal(signal))
        self._log_csv(signal)

    async def send_signals(self, signals: list[Signal]):
        """Send a batch of signals."""
        if not signals:
            return
        # Group into chunks of 10 to stay under Discord embed limits
        for i in range(0, len(signals), 10):
            batch = signals[i:i + 10]
            message = self._format_batch(batch)
            await self._post_discord(message)
        for s in signals:
            self._log_csv(s)

    async def send_daily_summary(self, signals: list[Signal], date_str: str):
        """Post daily summary to Discord."""
        if not signals:
            msg = f"**Daily Summary \u2014 {date_str}**\nNo significant signals today."
            await self._post_discord(msg)
            return

        lines = [f"**\ud83d\udcca Daily Summary \u2014 {date_str} | Top {len(signals)} Signals**\n"]
        for i, s in enumerate(signals, 1):
            emoji = RISK_EMOJI.get(s.risk_score, "\u26aa")
            lines.append(f"{i}. {emoji} **[{s.risk_score}/5]** {s.description}")
        lines.append(f"\n_Total signals today: {len(signals)}_")
        await self._post_discord("\n".join(lines))

    def _format_signal(self, s: Signal) -> str:
        emoji = RISK_EMOJI.get(s.risk_score, "\u26aa")
        return (
            f"{emoji} **[Risk {s.risk_score}/5]** {s.description}\n"
            f"> Vol: {s.volume:,} | OI: {s.open_interest:,} | "
            f"Premium: {s.premium_str} | V/OI: {s.oi_ratio:.1f}"
        )

    def _format_batch(self, signals: list[Signal]) -> str:
        lines = ["**\ud83d\udea8 Options Flow Alert**\n"]
        for s in signals:
            emoji = RISK_EMOJI.get(s.risk_score, "\u26aa")
            lines.append(
                f"{emoji} **[{s.risk_score}/5]** {s.description}\n"
                f"> Vol: {s.volume:,} | OI: {s.open_interest:,} | "
                f"Premium: {s.premium_str}"
            )
        return "\n".join(lines)

    async def _post_discord(self, content: str):
        if not self.webhook_url:
            logger.warning("No Discord webhook URL configured, skipping alert")
            return

        # Discord limit is 2000 chars
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
                        logger.error("Discord webhook error %d: %s",
                                     resp.status, text[:200])
        except Exception as e:
            logger.error("Failed to send Discord alert: %s", e)

    def _log_csv(self, signal: Signal):
        try:
            with open(self.csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(signal.to_csv_row())
        except Exception as e:
            logger.error("Failed to write CSV: %s", e)
