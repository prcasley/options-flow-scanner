"""Options Flow Scanner — main entry point."""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from scanner.alerts import AlertManager
from scanner.database import SignalDatabase
from scanner.detector import Detector
from scanner.polygon_client import PolygonClient
from scanner.scheduler import Scanner

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def main():
    config = load_config()
    setup_logging(config.get("log_level", "INFO"))
    logger = logging.getLogger("main")

    # Validate environment
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        logger.error("POLYGON_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL not set — Discord alerts disabled.")

    # Initialize components
    rate_cfg = config.get("rate_limit", {})
    polygon = PolygonClient(
        api_key=api_key,
        rate_limit_cpm=rate_cfg.get("calls_per_minute", 5),
        max_retries=rate_cfg.get("max_retries", 3),
        retry_delay=rate_cfg.get("retry_delay_seconds", 15),
    )

    detector = Detector(config)
    alerts = AlertManager(
        webhook_url=webhook_url,
        csv_path=config.get("csv_log_path", "data/alerts.csv"),
    )
    db = SignalDatabase(config.get("db_path", "data/signals.db"))
    await db.initialize()

    scanner = Scanner(config, polygon, detector, alerts, db)

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def shutdown_handler():
        logger.info("Shutdown signal received...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler)

    logger.info("=" * 60)
    logger.info("Options Flow Scanner starting")
    logger.info("Watchlist: %s", ", ".join(config.get("watchlist", [])))
    logger.info("Discovery mode: %s",
                "ON" if config.get("discovery", {}).get("enabled") else "OFF")
    logger.info("Scan interval: %ds", config.get("scan_interval_seconds", 60))
    logger.info("=" * 60)

    # Run scanner until shutdown
    scan_task = asyncio.create_task(scanner.run())

    await stop_event.wait()
    await scanner.stop()
    scan_task.cancel()
    try:
        await scan_task
    except asyncio.CancelledError:
        pass

    # Cleanup
    await polygon.close()
    await alerts.close()
    await db.close()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
