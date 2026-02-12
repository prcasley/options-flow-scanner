"""Signal detection engine — analyzes options snapshots for unusual activity."""

import logging
from datetime import datetime, timedelta

from .models import OptionsContract, Signal

logger = logging.getLogger(__name__)


class Detector:
    def __init__(self, config: dict):
        t = config.get("thresholds", {})
        self.volume_spike_mult = t.get("volume_spike_multiplier", 5.0)
        self.min_volume = t.get("min_volume", 100)
        self.min_oi = t.get("min_oi", 50)
        self.high_vol_oi_ratio = t.get("high_volume_oi_ratio", 3.0)
        self.min_premium = t.get("min_estimated_premium_usd", 50_000)
        self.sweep_threshold = t.get("sweep_size_threshold", 100)

        r = config.get("risk_scoring", {})
        self.w_volume = r.get("volume_spike_weight", 0.3)
        self.w_premium = r.get("premium_weight", 0.25)
        self.w_oi_ratio = r.get("oi_ratio_weight", 0.2)
        self.w_sweep = r.get("sweep_weight", 0.15)
        self.w_expiry = r.get("near_expiry_weight", 0.1)

        # Running averages: ticker -> {contract_key -> avg_volume}
        self._avg_volume: dict[str, dict[str, float]] = {}

    def _contract_key(self, ticker: str, strike: float,
                      expiry: str, ctype: str) -> str:
        return f"{ticker}:{strike}:{expiry}:{ctype}"

    def _update_average(self, key: str, volume: int,
                        ticker: str) -> float:
        """EMA-style running average. Returns the prior average."""
        bucket = self._avg_volume.setdefault(ticker, {})
        prev = bucket.get(key)
        if prev is None:
            bucket[key] = float(volume)
            return float(volume)
        alpha = 0.3
        new_avg = alpha * volume + (1 - alpha) * prev
        bucket[key] = new_avg
        return prev

    def analyze_snapshot(self, underlying: str,
                         contracts: list[dict]) -> list[Signal]:
        """Analyze a batch of option contract snapshots and return signals."""
        signals = []
        now = datetime.now()

        for c in contracts:
            try:
                sig = self._evaluate_contract(underlying, c, now)
                if sig:
                    signals.append(sig)
            except Exception as e:
                logger.debug("Error evaluating contract: %s", e)

        return signals

    def _evaluate_contract(self, underlying: str, raw: dict,
                           now: datetime) -> Signal | None:
        """Evaluate a single contract snapshot dict from Polygon."""
        details = raw.get("details", {})
        day = raw.get("day", {})
        greeks = raw.get("greeks", {})

        strike = details.get("strike_price", 0)
        expiry = details.get("expiration_date", "")
        ctype = details.get("contract_type", "").lower()
        if ctype not in ("call", "put"):
            return None

        volume = day.get("volume", 0) or 0
        oi = raw.get("open_interest", 0) or 0
        last_price = day.get("close", 0) or day.get("last_otc", 0) or 0
        iv = greeks.get("implied_volatility")

        # Basic filters
        if volume < self.min_volume:
            return None

        # Estimated premium
        premium = volume * last_price * 100  # each contract = 100 shares

        if premium < self.min_premium:
            return None

        # Volume ratio vs running average
        key = self._contract_key(underlying, strike, expiry, ctype)
        avg_vol = self._update_average(key, volume, underlying)
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0

        # OI ratio
        oi_ratio = volume / oi if oi > 0 else 0.0

        # Detect signal types
        signal_types = []

        if vol_ratio >= self.volume_spike_mult:
            signal_types.append("volume spike")

        if volume >= self.sweep_threshold and premium >= self.min_premium:
            signal_types.append("bullish sweep" if ctype == "call" else "bearish sweep")

        if oi_ratio >= self.high_vol_oi_ratio and oi >= self.min_oi:
            signal_types.append("high vol/OI")

        # Near-expiry flag (within 7 days)
        near_expiry = False
        if expiry:
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
                if (exp_date - now).days <= 7:
                    near_expiry = True
                    signal_types.append("near expiry")
            except ValueError:
                pass

        if not signal_types:
            return None

        # Risk score (1-5)
        raw_score = 0.0
        raw_score += min(vol_ratio / 20, 1.0) * self.w_volume
        raw_score += min(premium / 5_000_000, 1.0) * self.w_premium
        raw_score += min(oi_ratio / 10, 1.0) * self.w_oi_ratio
        if "sweep" in " ".join(signal_types):
            raw_score += 1.0 * self.w_sweep
        if near_expiry:
            raw_score += 1.0 * self.w_expiry
        risk_score = max(1, min(5, round(raw_score * 5)))

        contract = OptionsContract(
            ticker=underlying,
            strike=strike,
            expiry=expiry,
            contract_type=ctype,
            volume=volume,
            open_interest=oi,
            last_price=last_price,
            implied_volatility=iv,
        )

        desc = self._build_description(contract, vol_ratio, premium, signal_types)

        return Signal(
            timestamp=now,
            ticker=underlying,
            strike=strike,
            expiry=expiry,
            contract_type=ctype,
            volume=volume,
            open_interest=oi,
            estimated_premium=premium,
            risk_score=risk_score,
            signal_types=signal_types,
            description=desc,
            volume_ratio=vol_ratio,
            oi_ratio=oi_ratio,
            last_price=last_price,
        )

    def _build_description(self, c: OptionsContract, vol_ratio: float,
                           premium: float, signal_types: list[str]) -> str:
        sig = Signal(
            timestamp=datetime.now(),
            ticker=c.ticker,
            strike=c.strike,
            expiry=c.expiry,
            contract_type=c.contract_type,
            volume=c.volume,
            open_interest=c.open_interest,
            estimated_premium=premium,
            risk_score=0,
            signal_types=signal_types,
            volume_ratio=vol_ratio,
        )
        parts = [sig.contract_label, "\u2014"]
        if vol_ratio > 1:
            parts.append(f"{vol_ratio:.0f}x avg volume,")
        parts.append(f"{sig.premium_str} premium,")
        parts.append(", ".join(signal_types))
        return " ".join(parts)
