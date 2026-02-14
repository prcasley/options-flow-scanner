"""Seed the database with demo signals for testing the dashboard."""

import asyncio
import random
from datetime import datetime, timedelta

from scanner.database import SignalDatabase
from scanner.models import Signal

TICKERS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "AMD", "GOOGL",
            "AVGO", "JPM", "NFLX", "COIN", "SMCI"]

SIGNAL_TYPES = [
    ["volume spike"],
    ["bullish sweep"],
    ["bearish sweep"],
    ["high vol/OI"],
    ["volume spike", "near expiry"],
    ["bullish sweep", "high vol/OI"],
    ["bearish sweep", "near expiry"],
    ["volume spike", "high vol/OI"],
    ["bullish sweep", "volume spike", "near expiry"],
]


def random_signal(base_time: datetime) -> Signal:
    ticker = random.choice(TICKERS)
    ctype = random.choice(["call", "put"])
    strike = round(random.uniform(100, 600), 0)
    days_out = random.choice([1, 2, 3, 5, 7, 14, 30, 60])
    expiry = (base_time + timedelta(days=days_out)).strftime("%Y-%m-%d")
    volume = random.randint(200, 15000)
    oi = random.randint(50, 8000)
    last_price = round(random.uniform(0.5, 30.0), 2)
    premium = volume * last_price * 100
    risk = random.randint(1, 5)
    sig_types = random.choice(SIGNAL_TYPES)
    vol_ratio = round(random.uniform(1.5, 25.0), 1)
    oi_ratio = round(volume / max(oi, 1), 2)
    offset = timedelta(minutes=random.randint(0, 390))
    ts = base_time.replace(hour=9, minute=30, second=0, microsecond=0) + offset

    side = "C" if ctype == "call" else "P"
    exp_d = datetime.strptime(expiry, "%Y-%m-%d")
    exp_str = f"{exp_d.month}/{exp_d.day}"
    strike_str = f"{strike:g}"
    label = f"{ticker} {strike_str}{side} {exp_str}"

    if premium >= 1_000_000:
        prem_str = f"${premium / 1_000_000:.1f}M"
    elif premium >= 1_000:
        prem_str = f"${premium / 1_000:.0f}K"
    else:
        prem_str = f"${premium:.0f}"

    desc = f"{label} \u2014 {vol_ratio:.0f}x avg volume, {prem_str} premium, {', '.join(sig_types)}"

    return Signal(
        timestamp=ts,
        ticker=ticker,
        strike=strike,
        expiry=expiry,
        contract_type=ctype,
        volume=volume,
        open_interest=oi,
        estimated_premium=premium,
        risk_score=risk,
        signal_types=sig_types,
        description=desc,
        volume_ratio=vol_ratio,
        oi_ratio=oi_ratio,
        last_price=last_price,
    )


async def main():
    db = SignalDatabase("data/signals.db")
    await db.initialize()

    now = datetime.now()
    signals = [random_signal(now) for _ in range(60)]
    # Also add some from yesterday
    yesterday = now - timedelta(days=1)
    signals += [random_signal(yesterday) for _ in range(30)]

    await db.insert_signals(signals)
    await db.close()

    print(f"Seeded {len(signals)} demo signals into data/signals.db")
    print(f"  Today: 60 signals")
    print(f"  Yesterday: 30 signals")
    print(f"\nStart the dashboard with:  python dashboard.py")


if __name__ == "__main__":
    asyncio.run(main())
