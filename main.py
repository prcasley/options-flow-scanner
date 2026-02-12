"""Options Flow Scanner — main entry point."""

import asyncio
import json as _json
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
from scanner.health import HealthServer
from scanner.polygon_client import PolygonClient
from scanner.scheduler import Scanner

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def validate_config(config: dict) -> list[str]:
    """Validate configuration and return a list of warnings/errors."""
    errors = []

    # Required sections
    if not isinstance(config.get("watchlist"), list) or not config["watchlist"]:
        errors.append("'watchlist' must be a non-empty list of ticker symbols")

    # Numeric validations
    interval = config.get("scan_interval_seconds")
    if not isinstance(interval, (int, float)) or interval < 10:
        errors.append("'scan_interval_seconds' must be a number >= 10")

    rate_cfg = config.get("rate_limit", {})
    if not isinstance(rate_cfg, dict):
        errors.append("'rate_limit' must be a mapping")
    else:
        cpm = rate_cfg.get("calls_per_minute", 5)
        if not isinstance(cpm, (int, float)) or cpm < 1:
            errors.append("'rate_limit.calls_per_minute' must be >= 1")

    thresholds = config.get("thresholds", {})
    if not isinstance(thresholds, dict):
        errors.append("'thresholds' must be a mapping")
    else:
        for key in ("volume_spike_multiplier", "min_volume", "min_oi",
                     "high_volume_oi_ratio", "min_estimated_premium_usd",
                     "sweep_size_threshold"):
            val = thresholds.get(key)
            if val is not None and (not isinstance(val, (int, float)) or val < 0):
                errors.append(f"'thresholds.{key}' must be a non-negative number")

    risk = config.get("risk_scoring", {})
    if isinstance(risk, dict):
        weight_sum = sum(risk.get(k, 0) for k in (
            "volume_spike_weight", "premium_weight", "oi_ratio_weight",
            "sweep_weight", "near_expiry_weight",
        ))
        if abs(weight_sum - 1.0) > 0.01:
            errors.append(f"Risk scoring weights sum to {weight_sum:.2f}, expected ~1.0")

    market = config.get("market", {})
    if isinstance(market, dict):
        for key in ("open_hour", "close_hour"):
            val = market.get(key)
            if val is not None and (not isinstance(val, int) or not (0 <= val <= 23)):
                errors.append(f"'market.{key}' must be an integer 0-23")

    return errors


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production/container environments."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return _json.dumps(entry)


def setup_logging(level: str = "INFO", json_format: bool = False):
    log_level = getattr(logging, level.upper(), logging.INFO)
    if json_format:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S"))
        logging.root.handlers = [handler]
        logging.root.setLevel(log_level)
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


async def main():
    config = load_config()
    setup_logging(
        level=config.get("log_level", "INFO"),
        json_format=config.get("log_json", False),
    )
    logger = logging.getLogger("main")

    # Validate config
    config_errors = validate_config(config)
    for err in config_errors:
        logger.error("Config error: %s", err)
    if config_errors:
        sys.exit(1)

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

    # Health check server
    health_cfg = config.get("health", {})
    health = HealthServer(
        host=health_cfg.get("host", "0.0.0.0"),
        port=health_cfg.get("port", 8080),
    )

    scanner = Scanner(config, polygon, detector, alerts, db, health=health)

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

    # Start health server and scanner
    await health.start()
    scan_task = asyncio.create_task(scanner.run())

    await stop_event.wait()
    await scanner.stop()
    scan_task.cancel()
    try:
        await scan_task
    except asyncio.CancelledError:
        pass

    # Cleanup
    await health.stop()
    await polygon.close()
    await db.close()
    logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
