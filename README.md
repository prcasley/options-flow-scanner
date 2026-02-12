# Options Flow Scanner

Real-time options market scanner that detects unusual activity using the Polygon.io API and sends alerts to Discord.

## Features

- **Unusual Volume Detection** — flags contracts trading at 5x+ their average volume
- **Sweep Detection** — identifies large single-trade prints
- **Volume/OI Ratio** — catches new position openings with high volume relative to open interest
- **Risk Scoring** — ranks each signal 1-5 based on combined metrics
- **Watchlist + Discovery Mode** — scans your watchlist plus auto-discovers active tickers
- **Discord Alerts** — real-time alerts with contract details, premium estimates, and signal descriptions
- **Daily Summary** — top 10 signals posted to Discord at 4:15 PM ET
- **CSV + SQLite Logging** — all signals stored for backtesting and pattern recognition
- **Rate Limit Aware** — respects Polygon.io free tier limits (5 calls/min)

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/options-flow-scanner.git
cd options-flow-scanner
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` and add your keys:
- `POLYGON_API_KEY` — get one free at [polygon.io](https://polygon.io)
- `DISCORD_WEBHOOK_URL` — create a webhook in your Discord server settings

### 3. Run

```bash
python main.py
```

The scanner runs during market hours (9:30 AM - 4:00 PM ET, weekdays) and automatically pauses outside trading hours.

## Configuration

Edit `config.yaml` to tune:

| Parameter | Default | Description |
|---|---|---|
| `scan_interval_seconds` | 60 | Seconds between scan cycles |
| `thresholds.volume_spike_multiplier` | 5.0 | Volume must be Nx average to trigger |
| `thresholds.min_volume` | 100 | Minimum contract volume to consider |
| `thresholds.min_estimated_premium_usd` | 50000 | Minimum premium ($) to alert on |
| `thresholds.sweep_size_threshold` | 100 | Contracts in single trade to flag as sweep |
| `thresholds.high_volume_oi_ratio` | 3.0 | Volume/OI ratio threshold |
| `discovery.enabled` | true | Auto-discover active tickers beyond watchlist |
| `daily_summary.enabled` | true | Post daily summary at market close |

## Project Structure

```
options-flow-scanner/
├── main.py                 # Entry point
├── config.yaml             # All tunable parameters
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── scanner/
│   ├── polygon_client.py   # Async Polygon.io API client with rate limiting
│   ├── detector.py         # Signal detection engine
│   ├── alerts.py           # Discord webhooks + CSV logging
│   ├── database.py         # SQLite storage for historical signals
│   ├── scheduler.py        # Main scan loop orchestrator
│   └── models.py           # Data models (Signal, OptionsContract)
└── data/
    ├── alerts.csv           # Generated: CSV log of all alerts
    └── signals.db           # Generated: SQLite database
```

## Alert Format

Discord alerts look like:

```
🔴 [Risk 5/5] AVGO 220C 3/21 — 15x avg volume, $2.3M premium, bullish sweep
> Vol: 12,450 | OI: 830 | Premium: $2.3M
```

## Rate Limits

The free Polygon.io tier allows 5 API calls/minute. The scanner automatically:
- Rate-limits all requests with a token bucket
- Retries on 429 (rate limited) responses
- Backs off on server errors

For faster scanning, upgrade your Polygon plan and increase `rate_limit.calls_per_minute` in `config.yaml`.

## License

MIT
