"""Lightweight HTTP health check server for container orchestration."""

import asyncio
import json
import logging
from datetime import datetime
from aiohttp import web

logger = logging.getLogger(__name__)


class HealthServer:
    """Exposes /health and /status endpoints for liveness and readiness probes."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.router.add_get("/health", self._health)
        self._app.router.add_get("/status", self._status)
        self._runner: web.AppRunner | None = None
        self._started_at = datetime.utcnow()

        # Mutable state updated by the scanner
        self.scan_count = 0
        self.signal_count = 0
        self.last_scan_time: datetime | None = None
        self.last_error: str | None = None
        self.is_running = False

    async def start(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Health server listening on %s:%d", self.host, self.port)

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()

    async def _health(self, request: web.Request) -> web.Response:
        """Liveness probe — returns 200 if the process is alive."""
        return web.json_response({"status": "ok"})

    async def _status(self, request: web.Request) -> web.Response:
        """Readiness/status probe with operational metrics."""
        uptime = (datetime.utcnow() - self._started_at).total_seconds()
        body = {
            "status": "running" if self.is_running else "idle",
            "uptime_seconds": round(uptime, 1),
            "scan_count": self.scan_count,
            "signal_count": self.signal_count,
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "last_error": self.last_error,
        }
        return web.json_response(body)
