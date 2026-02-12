# Options Flow Scanner

Real-time unusual options activity scanner powered by [Polygon.io](https://polygon.io). Detects volume spikes, sweeps, and high-conviction trades — then alerts you via Discord, Slack, or email.

```
┌─────────────────────────────────────────────────────────────────┐
│                    OPTIONS FLOW SCANNER                         │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Polygon  │───▶│ Detector │───▶│  Alerts  │───▶│ Discord  │  │
│  │   API    │    │  Engine  │    │ Manager  │    │  Slack   │  │
│  └──────────┘    └──────────┘    └──────────┘    │  Email   │  │
│       │               │              │           └──────────┘  │
│       │          ┌────┴────┐    ┌────┴────┐                    │
│       │          │ Pattern │    │  Daily  │                    │
│       │          │Analyzer │    │ Summary │                    │
│       │          └─────────┘    └─────────┘                    │
│       │                                                         │
│  ┌────┴────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Rate   │    │  SQLite  │    │ Backtest │    │   Web    │  │
│  │ Limiter │    │    DB    │◀──▶│  Engine  │    │Dashboard │  │
│  └─────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│  │  Health  │    │  Docker  │    │   CI/CD  │                  │
│  │  Server  │    │ Support  │    │ Pipeline │                  │
│  └──────────┘    └──────────┘    └──────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## Features

| Feature | Description |
|---|---|
| **Volume Spike Detection** | Flags contracts trading at 5x+ their EMA average volume |
| **Sweep Detection** | Identifies large single-trade prints hitting multiple exchanges |
| **Vol/OI Ratio Analysis** | Catches new positions with high volume relative to open interest |
| **Risk Scoring (1-5)** | Weighted composite score based on multiple signal factors |
| **Watchlist + Discovery** | Scans your tickers plus auto-discovers the most active names |
| **Multi-Channel Alerts** | Discord, Slack, and email with rich formatting |
| **Web Dashboard** | Real-time browser UI with auto-refresh and signal history |
| **Daily Summary** | Top signals posted at market close |
| **Pattern Analysis** | Detects repeat flow, accumulation, clusters, and high-conviction patterns |
| **Backtesting** | Filter and analyze historical signals with full statistics |
| **CSV + SQLite Logging** | All signals persisted for analysis and replay |
| **Rate Limit Aware** | Token-bucket limiter with retry/backoff for Polygon.io free tier |
| **Health Checks** | `/health` and `/status` endpoints for container orchestration |
| **Structured Logging** | JSON log output for production/container environments |
| **Docker Ready** | Dockerfile + docker-compose for one-command deployment |
| **CI/CD** | GitHub Actions workflow with test, lint, and Docker build |

## Quick Start

### Option 1: Local

```bash
git clone https://github.com/YOUR_USERNAME/options-flow-scanner.git
cd options-flow-scanner
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — add your POLYGON_API_KEY (required) and webhook URLs (optional)

python main.py
```

### Option 2: Docker Compose

```bash
cp .env.example .env
# Edit .env with your keys

docker compose up -d
```

The scanner runs during US market hours (9:30 AM – 4:00 PM ET, weekdays) and automatically pauses outside trading hours and on market holidays.

## Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `POLYGON_API_KEY` | Yes | API key from [polygon.io](https://polygon.io) |
| `DISCORD_WEBHOOK_URL` | No | Discord channel webhook URL |
| `SLACK_WEBHOOK_URL` | No | Slack incoming webhook URL |

### config.yaml

| Parameter | Default | Description |
|---|---|---|
| `scan_interval_seconds` | 60 | Seconds between scan cycles |
| `thresholds.volume_spike_multiplier` | 5.0 | Volume must be Nx average to trigger |
| `thresholds.min_volume` | 100 | Minimum contract volume to consider |
| `thresholds.min_estimated_premium_usd` | 50000 | Minimum premium ($) to alert on |
| `thresholds.sweep_size_threshold` | 100 | Contracts in single trade to flag as sweep |
| `thresholds.high_volume_oi_ratio` | 3.0 | Volume/OI ratio threshold |
| `discovery.enabled` | true | Auto-discover active tickers beyond watchlist |
| `discovery.max_tickers` | 50 | Max tickers to scan via discovery |
| `daily_summary.enabled` | true | Post daily summary at market close |
| `daily_summary.hour` | 16 | Hour (ET) to send summary |
| `daily_summary.minute` | 15 | Minute to send summary |
| `ema.alpha` | 0.3 | EMA smoothing factor for volume averages |
| `ema.max_tracked_contracts` | 10000 | Max contracts in memory before eviction |
| `health.host` | 0.0.0.0 | Health server bind address |
| `health.port` | 8080 | Health server port |
| `log_json` | false | Enable structured JSON logging |

## Project Structure

```
options-flow-scanner/
├── main.py                  # Entry point, config validation, component wiring
├── config.yaml              # All tunable parameters
├── requirements.txt         # Python dependencies
├── Dockerfile               # Multi-stage container build
├── docker-compose.yml       # One-command deployment
├── .env.example             # Environment variable template
├── .github/
│   └── workflows/
│       └── ci.yml           # GitHub Actions CI/CD pipeline
├── scanner/
│   ├── models.py            # Data models (Signal, OptionsContract)
│   ├── polygon_client.py    # Async Polygon.io API client with rate limiting
│   ├── detector.py          # Signal detection engine with EMA tracking
│   ├── alerts.py            # Discord webhooks + CSV logging
│   ├── channels.py          # Multi-channel dispatch (Discord, Slack, Email)
│   ├── database.py          # SQLite storage for historical signals
│   ├── scheduler.py         # Main scan loop with market hours + holidays
│   ├── patterns.py          # Recurring pattern analysis engine
│   ├── backtest.py          # Historical data backtesting
│   ├── health.py            # HTTP health check server
│   └── dashboard.py         # Web dashboard with REST API
├── tests/
│   ├── conftest.py          # Shared fixtures
│   ├── test_detector.py     # Detector engine tests
│   ├── test_alerts.py       # Alert manager tests
│   ├── test_database.py     # Database tests
│   ├── test_models.py       # Data model tests
│   ├── test_polygon_client.py # API client tests
│   ├── test_scheduler.py    # Scanner loop tests
│   ├── test_config_validation.py # Config validation tests
│   ├── test_channels.py     # Multi-channel alert tests
│   ├── test_patterns.py     # Pattern analysis tests
│   ├── test_backtest.py     # Backtesting tests
│   └── test_dashboard.py    # Dashboard API tests
└── data/                    # Generated at runtime
    ├── alerts.csv
    └── signals.db
```

## Alert Formats

### Discord
```
🔴 [Risk 5/5] AVGO 220C 3/21 — 15x avg volume, $2.3M premium, bullish sweep
> Vol: 12,450 | OI: 830 | Premium: $2.3M
```

### Slack
```
🚨 Options Flow Alert
*[█████]* AVGO 220C 3/21 — 15x avg volume, $2.3M premium
    Vol: 12,450 | OI: 830 | Premium: $2.3M
```

## Web Dashboard

Access the dashboard at `http://localhost:8080/` when the scanner is running. It shows:
- Scanner status (running/idle), uptime, scan count
- Signals detected today with risk badges
- Auto-refreshes every 30 seconds

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Web dashboard UI |
| `GET /health` | Liveness probe (always 200) |
| `GET /status` | Readiness probe with metrics |
| `GET /api/status` | Scanner status JSON |
| `GET /api/signals?limit=50&date=YYYY-MM-DD` | Recent signals |
| `GET /api/signals/{TICKER}?limit=50` | Ticker signal history |

## Pattern Analysis

The pattern analyzer detects recurring activity across historical signals:

| Pattern | Description |
|---|---|
| **Repeat Flow** | Same ticker + direction appearing 3+ times |
| **Accumulation** | Growing volume on same strike across sessions |
| **Cluster** | Multiple different strikes on same ticker in one day |
| **High Conviction** | Repeated risk 4+ signals on same ticker |

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=scanner --cov-report=term-missing

# Run specific test file
pytest tests/test_detector.py -v
```

## Rate Limits

The free Polygon.io tier allows 5 API calls/minute. The scanner automatically:
- Rate-limits all requests with a token-bucket algorithm
- Retries on 429 (rate limited) responses with exponential backoff
- Backs off on server errors (5xx)

For faster scanning, upgrade your Polygon plan and increase `rate_limit.calls_per_minute` in `config.yaml`.

## License

MIT
