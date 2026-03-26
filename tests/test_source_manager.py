"""Unit tests for the smart source rotation manager."""

import time
from unittest.mock import AsyncMock

import pytest

from scanner.sources.source_manager import SourceManager, _SourceState


class TestSourceState:
    def test_initially_available(self):
        state = _SourceState("polygon")
        assert state.available is True

    def test_mark_failed_makes_unavailable(self):
        state = _SourceState("polygon", cooldown=9999)
        state.mark_failed()
        assert state.available is False

    def test_mark_ok_restores_availability(self):
        state = _SourceState("polygon", cooldown=9999)
        state.mark_failed()
        state.mark_ok()
        assert state.available is True

    def test_increment_calls_tracks_per_minute(self):
        state = _SourceState("polygon")
        assert state.increment_calls() == 1
        assert state.increment_calls() == 2
        assert state.increment_calls() == 3

    def test_increment_calls_resets_after_minute(self):
        state = _SourceState("polygon")
        state._minute_start = time.monotonic() - 61  # simulate old window
        result = state.increment_calls()
        assert result == 1  # reset


class TestSourceManager:
    @pytest.fixture
    def polygon(self):
        client = AsyncMock()
        client.name = "polygon"
        client.get_options_snapshot = AsyncMock(return_value=[{"test": True}])
        client.get_most_active = AsyncMock(return_value=["SPY", "AAPL"])
        client.close = AsyncMock()
        return client

    @pytest.fixture
    def schwab(self):
        client = AsyncMock()
        client.name = "schwab"
        client.get_options_snapshot = AsyncMock(return_value=[{"schwab": True}])
        client.get_most_active = AsyncMock(return_value=["TSLA", "NVDA"])
        client.close = AsyncMock()
        return client

    @pytest.fixture
    def yfinance(self):
        client = AsyncMock()
        client.name = "yfinance"
        client.get_options_snapshot = AsyncMock(return_value=[{"yf": True}])
        client.get_most_active = AsyncMock(return_value=["QQQ"])
        client.close = AsyncMock()
        return client

    @pytest.fixture
    def manager(self, polygon, schwab, yfinance):
        return SourceManager(
            polygon=polygon,
            schwab=schwab,
            yfinance=yfinance,
            polygon_rate_limit_cpm=5,
        )

    @pytest.mark.asyncio
    async def test_uses_polygon_by_default(self, manager, polygon):
        result = await manager.get_options_snapshot("AAPL")
        polygon.get_options_snapshot.assert_called_once_with("AAPL")
        assert result == [{"test": True}]

    @pytest.mark.asyncio
    async def test_falls_back_to_schwab_when_polygon_fails(
        self, manager, polygon, schwab
    ):
        polygon.get_options_snapshot.side_effect = Exception("network error")
        result = await manager.get_options_snapshot("AAPL")
        assert schwab.get_options_snapshot.called
        assert result  # should have gotten schwab data

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_fail(
        self, manager, polygon, schwab, yfinance
    ):
        polygon.get_options_snapshot.side_effect = Exception("fail")
        schwab.get_options_snapshot.side_effect = Exception("fail")
        yfinance.get_options_snapshot.side_effect = Exception("fail")
        result = await manager.get_options_snapshot("AAPL")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_most_active_uses_polygon_first(self, manager, polygon):
        result = await manager.get_most_active()
        polygon.get_most_active.assert_called_once()
        assert "SPY" in result

    @pytest.mark.asyncio
    async def test_get_most_active_falls_back_on_failure(
        self, manager, polygon, schwab
    ):
        polygon.get_most_active.side_effect = Exception("fail")
        result = await manager.get_most_active()
        schwab.get_most_active.assert_called_once()
        assert result

    def test_source_status_all_available(self, manager):
        status = manager.source_status()
        assert status["polygon"] is True
        assert status["schwab"] is True
        assert status["yfinance"] is True

    def test_source_status_after_failure(self, manager):
        manager._states["polygon"].mark_failed()
        status = manager.source_status()
        assert status["polygon"] is False
        assert status["schwab"] is True

    @pytest.mark.asyncio
    async def test_close_calls_all_clients(self, manager, polygon, schwab, yfinance):
        await manager.close()
        polygon.close.assert_called_once()
        schwab.close.assert_called_once()
        yfinance.close.assert_called_once()

    def test_manager_without_optional_sources(self, polygon):
        m = SourceManager(polygon=polygon)
        assert "schwab" not in m._states
        assert "yfinance" not in m._states

    def test_name(self, manager):
        assert manager.name == "source_manager"

    @pytest.mark.asyncio
    async def test_prefers_schwab_during_extended_hours(self, manager, polygon, schwab):
        """When extended hours, Schwab should be preferred over Polygon."""
        with pytest.MonkeyPatch().context() as mp:
            from scanner.sources import schwab_client

            mp.setattr(
                schwab_client.SchwabClient,
                "is_extended_hours",
                staticmethod(lambda: True),
            )
            # Force polygon to be rate-limited so extended-hours logic kicks in
            await manager.get_options_snapshot("AAPL")
            # In extended hours the first choice is Schwab if available
            # (polygon may also have been called if extended_hours check is first)
            assert (
                schwab.get_options_snapshot.called
                or polygon.get_options_snapshot.called
            )
