"""Tests for the web dashboard and API endpoints."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.dashboard import DashboardServer
from scanner.health import HealthServer
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
        signal_types=["volume spike"],
        description=f"{ticker} 220C 3/21 test",
        volume_ratio=10.0,
        oi_ratio=4.0,
        last_price=3.0,
    )


class TestDashboardServer:
    def test_init_registers_routes(self):
        """Dashboard should register routes on the health server app."""
        health = HealthServer(port=0)
        db = AsyncMock()
        dashboard = DashboardServer(health, db)

        # Check that routes were registered
        routes = [r.resource.canonical for r in health._app.router.routes()
                  if hasattr(r, 'resource') and r.resource is not None]
        assert "/" in routes or any("/" == str(r.resource.canonical) for r in health._app.router.routes() if hasattr(r, 'resource') and r.resource)

    def test_signal_to_dict(self):
        """Should convert Signal to serializable dict."""
        sig = _make_signal()
        d = DashboardServer._signal_to_dict(sig)

        assert d["ticker"] == "AAPL"
        assert d["strike"] == 220.0
        assert d["risk_score"] == 4
        assert d["volume"] == 5000
        assert d["estimated_premium"] == 1_500_000.0
        assert d["signal_types"] == ["volume spike"]
        assert "timestamp" in d

    def test_signal_to_dict_preserves_types(self):
        """Dict values should have correct types for JSON serialization."""
        sig = _make_signal()
        d = DashboardServer._signal_to_dict(sig)

        assert isinstance(d["timestamp"], str)
        assert isinstance(d["ticker"], str)
        assert isinstance(d["strike"], float)
        assert isinstance(d["volume"], int)
        assert isinstance(d["risk_score"], int)
        assert isinstance(d["signal_types"], list)

    def test_signal_to_dict_all_fields(self):
        """All expected fields should be present."""
        sig = _make_signal()
        d = DashboardServer._signal_to_dict(sig)

        expected_keys = {
            "timestamp", "ticker", "strike", "expiry", "contract_type",
            "volume", "open_interest", "estimated_premium", "risk_score",
            "signal_types", "volume_ratio", "oi_ratio", "description",
        }
        assert set(d.keys()) == expected_keys


class TestDashboardAPI:
    """Integration-style tests using aiohttp test client."""

    @pytest.fixture
    def dashboard_app(self):
        health = HealthServer(port=0)
        db = AsyncMock()
        db.get_today_signals = AsyncMock(return_value=[])
        db.get_ticker_history = AsyncMock(return_value=[])
        dashboard = DashboardServer(health, db)
        return health._app, db

    async def test_dashboard_returns_html(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, _ = dashboard_app
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "Options Flow Scanner" in text
            assert "text/html" in resp.content_type

    async def test_health_endpoint(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, _ = dashboard_app
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"

    async def test_api_status(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, _ = dashboard_app
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/status")
            assert resp.status == 200
            data = await resp.json()
            assert "status" in data
            assert "scan_count" in data
            assert "uptime_seconds" in data

    async def test_api_signals_empty(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, _ = dashboard_app
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/signals")
            assert resp.status == 200
            data = await resp.json()
            assert data == []

    async def test_api_signals_with_data(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, db = dashboard_app
        db.get_today_signals = AsyncMock(return_value=[_make_signal()])

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/signals")
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 1
            assert data[0]["ticker"] == "AAPL"

    async def test_api_signals_limit(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, db = dashboard_app
        db.get_today_signals = AsyncMock(
            return_value=[_make_signal() for _ in range(10)]
        )

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/signals?limit=3")
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 3

    async def test_api_ticker_signals(self, dashboard_app):
        from aiohttp.test_utils import TestClient, TestServer
        app, db = dashboard_app
        db.get_ticker_history = AsyncMock(return_value=[_make_signal()])

        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/signals/AAPL")
            assert resp.status == 200
            data = await resp.json()
            assert len(data) == 1
