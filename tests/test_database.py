"""Unit tests for the SQLite signal database."""

from datetime import datetime

import pytest

from scanner.database import SignalDatabase
from scanner.models import Signal


@pytest.fixture
async def db():
    """Create an in-memory database for testing."""
    database = SignalDatabase(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def make_signal():
    """Factory for Signal objects with customizable fields."""
    def _make(ticker="AAPL", risk_score=3, premium=500_000.0,
              timestamp=None, expiry="2025-03-21"):
        return Signal(
            timestamp=timestamp or datetime(2025, 3, 15, 10, 30, 0),
            ticker=ticker,
            strike=220.0,
            expiry=expiry,
            contract_type="call",
            volume=5000,
            open_interest=1200,
            estimated_premium=premium,
            risk_score=risk_score,
            signal_types=["volume spike"],
            description="Test signal",
            volume_ratio=10.0,
            oi_ratio=4.2,
            last_price=3.0,
        )
    return _make


class TestDatabaseInit:
    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db):
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "signals"

    @pytest.mark.asyncio
    async def test_initialize_creates_indexes(self, db):
        cursor = await db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        rows = await cursor.fetchall()
        index_names = {r[0] for r in rows}
        assert "idx_signals_ticker" in index_names
        assert "idx_signals_timestamp" in index_names
        assert "idx_signals_risk" in index_names


class TestInsert:
    @pytest.mark.asyncio
    async def test_insert_single_signal(self, db, make_signal):
        sig = make_signal()
        await db.insert_signal(sig)

        cursor = await db._db.execute("SELECT COUNT(*) FROM signals")
        count = (await cursor.fetchone())[0]
        assert count == 1

    @pytest.mark.asyncio
    async def test_insert_batch(self, db, make_signal):
        signals = [make_signal(ticker=t) for t in ("AAPL", "MSFT", "GOOGL")]
        await db.insert_signals(signals)

        cursor = await db._db.execute("SELECT COUNT(*) FROM signals")
        count = (await cursor.fetchone())[0]
        assert count == 3

    @pytest.mark.asyncio
    async def test_insert_preserves_fields(self, db, make_signal):
        sig = make_signal(ticker="TSLA", risk_score=5, premium=2_000_000.0)
        await db.insert_signal(sig)

        cursor = await db._db.execute("SELECT ticker, risk_score, estimated_premium FROM signals")
        row = await cursor.fetchone()
        assert row[0] == "TSLA"
        assert row[1] == 5
        assert row[2] == pytest.approx(2_000_000.0)


class TestQuery:
    @pytest.mark.asyncio
    async def test_get_today_signals(self, db, make_signal):
        sig1 = make_signal(ticker="AAPL", risk_score=5, premium=1_000_000,
                           timestamp=datetime(2025, 3, 15, 10, 0))
        sig2 = make_signal(ticker="MSFT", risk_score=3, premium=500_000,
                           timestamp=datetime(2025, 3, 15, 11, 0))
        sig3 = make_signal(ticker="GOOGL", risk_score=4, premium=800_000,
                           timestamp=datetime(2025, 3, 14, 10, 0))  # different day
        await db.insert_signals([sig1, sig2, sig3])

        results = await db.get_today_signals("2025-03-15")
        assert len(results) == 2
        # Should be sorted by risk_score desc
        assert results[0].ticker == "AAPL"
        assert results[0].risk_score == 5

    @pytest.mark.asyncio
    async def test_get_today_signals_empty(self, db):
        results = await db.get_today_signals("2025-01-01")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_ticker_history(self, db, make_signal):
        for i in range(5):
            sig = make_signal(ticker="SPY",
                              timestamp=datetime(2025, 3, 15, 10 + i, 0))
            await db.insert_signal(sig)

        results = await db.get_ticker_history("SPY", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_get_ticker_history_empty(self, db):
        results = await db.get_ticker_history("NOPE")
        assert results == []


class TestSignalRoundTrip:
    @pytest.mark.asyncio
    async def test_signal_survives_roundtrip(self, db, make_signal):
        original = make_signal(ticker="NVDA", risk_score=4, premium=750_000)
        await db.insert_signal(original)

        results = await db.get_today_signals("2025-03-15")
        assert len(results) == 1
        restored = results[0]

        assert restored.ticker == original.ticker
        assert restored.strike == original.strike
        assert restored.expiry == original.expiry
        assert restored.contract_type == original.contract_type
        assert restored.volume == original.volume
        assert restored.risk_score == original.risk_score
        assert restored.signal_types == original.signal_types


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_db_connection(self):
        db = SignalDatabase(":memory:")
        # Don't initialize — _db is None
        result = await db.get_today_signals("2025-03-15")
        assert result == []

    @pytest.mark.asyncio
    async def test_insert_with_no_connection(self, make_signal):
        db = SignalDatabase(":memory:")
        sig = make_signal()
        # Should not raise
        await db.insert_signal(sig)
