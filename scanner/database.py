"""SQLite database for historical signal storage."""

import logging
from datetime import datetime
from pathlib import Path

import aiosqlite

from .models import Signal

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT NOT NULL,
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    contract_type TEXT NOT NULL,
    volume INTEGER NOT NULL,
    open_interest INTEGER NOT NULL,
    estimated_premium REAL NOT NULL,
    risk_score INTEGER NOT NULL,
    signal_types TEXT NOT NULL,
    volume_ratio REAL,
    oi_ratio REAL,
    description TEXT,
    last_price REAL
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker ON signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_risk ON signals(risk_score);
"""


class SignalDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("Database initialized at %s", self.db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    async def insert_signal(self, s: Signal):
        if not self._db:
            return
        await self._db.execute(
            """INSERT INTO signals
               (timestamp, ticker, strike, expiry, contract_type, volume,
                open_interest, estimated_premium, risk_score, signal_types,
                volume_ratio, oi_ratio, description, last_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.timestamp.isoformat(),
                s.ticker,
                s.strike,
                s.expiry,
                s.contract_type,
                s.volume,
                s.open_interest,
                s.estimated_premium,
                s.risk_score,
                "|".join(s.signal_types),
                s.volume_ratio,
                s.oi_ratio,
                s.description,
                s.last_price,
            ),
        )
        await self._db.commit()

    async def insert_signals(self, signals: list[Signal]):
        if not self._db or not signals:
            return
        await self._db.executemany(
            """INSERT INTO signals
               (timestamp, ticker, strike, expiry, contract_type, volume,
                open_interest, estimated_premium, risk_score, signal_types,
                volume_ratio, oi_ratio, description, last_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    s.timestamp.isoformat(),
                    s.ticker,
                    s.strike,
                    s.expiry,
                    s.contract_type,
                    s.volume,
                    s.open_interest,
                    s.estimated_premium,
                    s.risk_score,
                    "|".join(s.signal_types),
                    s.volume_ratio,
                    s.oi_ratio,
                    s.description,
                    s.last_price,
                )
                for s in signals
            ],
        )
        await self._db.commit()

    async def get_today_signals(self, date_str: str) -> list[Signal]:
        """Get all signals for a given date (YYYY-MM-DD)."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT timestamp, ticker, strike, expiry, contract_type,
                      volume, open_interest, estimated_premium, risk_score,
                      signal_types, volume_ratio, oi_ratio, description, last_price
               FROM signals
               WHERE timestamp LIKE ?
               ORDER BY risk_score DESC, estimated_premium DESC""",
            (f"{date_str}%",),
        )
        rows = await cursor.fetchall()
        return [self._row_to_signal(row) for row in rows]

    async def get_ticker_history(self, ticker: str,
                                  limit: int = 100) -> list[Signal]:
        """Get recent signals for a ticker."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT timestamp, ticker, strike, expiry, contract_type,
                      volume, open_interest, estimated_premium, risk_score,
                      signal_types, volume_ratio, oi_ratio, description, last_price
               FROM signals
               WHERE ticker = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (ticker, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_signal(row) for row in rows]

    @staticmethod
    def _row_to_signal(row) -> Signal:
        return Signal(
            timestamp=datetime.fromisoformat(row[0]),
            ticker=row[1],
            strike=row[2],
            expiry=row[3],
            contract_type=row[4],
            volume=row[5],
            open_interest=row[6],
            estimated_premium=row[7],
            risk_score=row[8],
            signal_types=row[9].split("|") if row[9] else [],
            volume_ratio=row[10] or 0.0,
            oi_ratio=row[11] or 0.0,
            description=row[12] or "",
            last_price=row[13] or 0.0,
        )
