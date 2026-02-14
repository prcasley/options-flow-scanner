"""Tests for scanner/database.py — SQLite storage with in-memory DB."""

import pytest
from datetime import datetime

from scanner.database import SignalDatabase
from scanner.models import Signal


def _make_signal(**overrides) -> Signal:
    defaults = dict(
        timestamp=datetime(2026, 2, 14, 10, 30, 0),
        ticker="NVDA",
        strike=800.0,
        expiry="2026-03-21",
        contract_type="call",
        volume=5000,
        open_interest=200,
        estimated_premium=2_500_000,
        risk_score=5,
        signal_types=["volume spike", "bullish sweep"],
        description="test signal",
        volume_ratio=10.0,
        oi_ratio=25.0,
        last_price=5.0,
    )
    defaults.update(overrides)
    return Signal(**defaults)


@pytest.fixture
async def db():
    """In-memory SQLite database for testing."""
    database = SignalDatabase(":memory:")
    await database.initialize()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_initialize_creates_tables(db):
    """Database should create tables on initialize."""
    cursor = await db._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "signals"


@pytest.mark.asyncio
async def test_insert_single_signal(db):
    """Should insert a signal and retrieve it."""
    sig = _make_signal()
    await db.insert_signal(sig)

    cursor = await db._db.execute("SELECT COUNT(*) FROM signals")
    row = await cursor.fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_insert_signals_batch(db):
    """Batch insert should insert all signals in one transaction."""
    signals = [
        _make_signal(ticker="SPY", strike=500.0 + i)
        for i in range(10)
    ]
    await db.insert_signals(signals)

    cursor = await db._db.execute("SELECT COUNT(*) FROM signals")
    row = await cursor.fetchone()
    assert row[0] == 10


@pytest.mark.asyncio
async def test_insert_signals_empty_list(db):
    """Empty list should not cause errors."""
    await db.insert_signals([])

    cursor = await db._db.execute("SELECT COUNT(*) FROM signals")
    row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_get_today_signals(db):
    """Should retrieve signals for a specific date."""
    sig1 = _make_signal(timestamp=datetime(2026, 2, 14, 10, 0, 0), risk_score=3)
    sig2 = _make_signal(timestamp=datetime(2026, 2, 14, 14, 0, 0), risk_score=5)
    sig3 = _make_signal(timestamp=datetime(2026, 2, 13, 10, 0, 0), risk_score=4)

    await db.insert_signal(sig1)
    await db.insert_signal(sig2)
    await db.insert_signal(sig3)

    results = await db.get_today_signals("2026-02-14")
    assert len(results) == 2
    # Should be ordered by risk_score DESC
    assert results[0].risk_score >= results[1].risk_score


@pytest.mark.asyncio
async def test_get_today_signals_empty(db):
    """Should return empty list when no signals for date."""
    results = await db.get_today_signals("2026-01-01")
    assert results == []


@pytest.mark.asyncio
async def test_get_ticker_history(db):
    """Should retrieve signal history for a specific ticker."""
    for i in range(5):
        sig = _make_signal(
            ticker="AAPL",
            timestamp=datetime(2026, 2, 14, 10 + i, 0, 0),
        )
        await db.insert_signal(sig)

    sig_other = _make_signal(ticker="MSFT")
    await db.insert_signal(sig_other)

    results = await db.get_ticker_history("AAPL")
    assert len(results) == 5
    assert all(s.ticker == "AAPL" for s in results)


@pytest.mark.asyncio
async def test_get_ticker_history_with_limit(db):
    """Should respect the limit parameter."""
    for i in range(10):
        await db.insert_signal(
            _make_signal(
                ticker="SPY",
                timestamp=datetime(2026, 2, 14, 10, i, 0),
            )
        )

    results = await db.get_ticker_history("SPY", limit=3)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_get_ticker_history_ordered_by_timestamp_desc(db):
    """Results should be ordered newest first."""
    await db.insert_signal(
        _make_signal(ticker="SPY", timestamp=datetime(2026, 2, 14, 9, 0, 0))
    )
    await db.insert_signal(
        _make_signal(ticker="SPY", timestamp=datetime(2026, 2, 14, 15, 0, 0))
    )
    await db.insert_signal(
        _make_signal(ticker="SPY", timestamp=datetime(2026, 2, 14, 12, 0, 0))
    )

    results = await db.get_ticker_history("SPY")
    assert results[0].timestamp > results[1].timestamp
    assert results[1].timestamp > results[2].timestamp


@pytest.mark.asyncio
async def test_signal_roundtrip_data_integrity(db):
    """Data should survive insert -> retrieve without corruption."""
    original = _make_signal(
        ticker="META",
        strike=550.5,
        expiry="2026-04-17",
        contract_type="put",
        volume=3000,
        open_interest=150,
        estimated_premium=1_200_000,
        risk_score=4,
        signal_types=["bearish sweep", "high vol/OI"],
        description="META 550.5P 4/17 — $1.2M premium",
        volume_ratio=8.5,
        oi_ratio=20.0,
        last_price=4.0,
    )
    await db.insert_signal(original)
    results = await db.get_ticker_history("META")
    assert len(results) == 1

    r = results[0]
    assert r.ticker == "META"
    assert r.strike == 550.5
    assert r.expiry == "2026-04-17"
    assert r.contract_type == "put"
    assert r.volume == 3000
    assert r.open_interest == 150
    assert r.estimated_premium == 1_200_000
    assert r.risk_score == 4
    assert "bearish sweep" in r.signal_types
    assert "high vol/OI" in r.signal_types
    assert r.volume_ratio == 8.5
    assert r.oi_ratio == 20.0
    assert r.last_price == 4.0


@pytest.mark.asyncio
async def test_db_not_initialized_returns_empty():
    """Methods should return empty results if DB wasn't initialized."""
    db = SignalDatabase(":memory:")
    # Don't call initialize
    results = await db.get_today_signals("2026-02-14")
    assert results == []
    results = await db.get_ticker_history("SPY")
    assert results == []
