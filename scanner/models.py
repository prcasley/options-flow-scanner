"""Data models for options flow signals."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OptionsContract:
    ticker: str
    strike: float
    expiry: str  # YYYY-MM-DD
    contract_type: str  # "call" or "put"
    volume: int
    open_interest: int
    last_price: float
    implied_volatility: Optional[float] = None
    day_change: Optional[float] = None


@dataclass
class Signal:
    timestamp: datetime
    ticker: str
    strike: float
    expiry: str
    contract_type: str  # "call" or "put"
    volume: int
    open_interest: int
    estimated_premium: float
    risk_score: int  # 1-5
    signal_types: list[str] = field(default_factory=list)
    description: str = ""
    volume_ratio: float = 0.0
    oi_ratio: float = 0.0
    last_price: float = 0.0

    @property
    def contract_label(self) -> str:
        """e.g. 'AVGO 220C 3/21'"""
        exp = datetime.strptime(self.expiry, "%Y-%m-%d")
        exp_str = f"{exp.month}/{exp.day}"
        side = "C" if self.contract_type == "call" else "P"
        strike_str = f"{self.strike:g}"
        return f"{self.ticker} {strike_str}{side} {exp_str}"

    @property
    def premium_str(self) -> str:
        if self.estimated_premium >= 1_000_000:
            return f"${self.estimated_premium / 1_000_000:.1f}M"
        if self.estimated_premium >= 1_000:
            return f"${self.estimated_premium / 1_000:.0f}K"
        return f"${self.estimated_premium:.0f}"

    def to_discord_line(self) -> str:
        parts = [self.contract_label, "---"]
        if self.volume_ratio > 1:
            parts.append(f"{self.volume_ratio:.0f}x avg volume")
        parts.append(f"{self.premium_str} premium")
        for st in self.signal_types:
            parts.append(st)
        return " | ".join(parts)

    def to_csv_row(self) -> list:
        return [
            self.timestamp.isoformat(),
            self.ticker,
            self.strike,
            self.expiry,
            self.contract_type,
            self.volume,
            self.open_interest,
            self.estimated_premium,
            self.risk_score,
            "|".join(self.signal_types),
            self.volume_ratio,
            self.oi_ratio,
            self.description,
        ]

    @staticmethod
    def csv_header() -> list:
        return [
            "timestamp",
            "ticker",
            "strike",
            "expiry",
            "contract_type",
            "volume",
            "open_interest",
            "estimated_premium",
            "risk_score",
            "signal_types",
            "volume_ratio",
            "oi_ratio",
            "description",
        ]
