# Options Flow Scanner — Complete How-To Guide

## What This Project Does

The Options Flow Scanner monitors the US stock options market in real-time to detect **unusual trading activity** — the kind of activity that often precedes significant price moves. Professional traders and institutions often use options to position ahead of catalysts (earnings, FDA approvals, acquisitions), and this tool catches those signals.

### Core Capabilities

1. **Volume Spike Detection** — Flags options contracts trading at 5x+ their normal average volume (using an exponential moving average). This identifies sudden surges of interest.

2. **Sweep Detection** — Identifies large block trades (100+ contracts) that suggest institutional-sized orders, classified as "bullish sweep" (calls) or "bearish sweep" (puts).

3. **Volume/Open Interest Ratio** — When volume far exceeds open interest (3x+), it indicates *new positions being opened* rather than existing positions being traded — a stronger signal.

4. **Near-Expiry Flagging** — Options expiring within 7 days with unusual activity are especially notable since they indicate short-term conviction.

5. **Risk Scoring (1-5)** — Combines all metrics into a weighted score:
   - Volume spike intensity (30%)
   - Premium size (25%)
   - Vol/OI ratio (20%)
   - Sweep detection (15%)
   - Near-expiry (10%)

6. **Discord Alerts** — Sends formatted alerts to a Discord channel in real-time.

7. **Data Logging** — Stores all signals in both CSV files and a SQLite database for historical analysis.

8. **Daily Summaries** — Posts a top-10 recap at market close (4:15 PM ET).

---

## Step-by-Step Setup

### Prerequisites
- Python 3.10+
- A Polygon.io API key (free tier works — 5 API calls/minute)
- (Optional) A Discord webhook URL for alerts

### Step 1: Clone and Set Up Environment

```bash
git clone <your-repo-url>
cd options-flow-scanner
python -m venv .venv
source .venv/bin/activate    # Linux/Mac
# .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### Step 2: Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and add your keys:
```
POLYGON_API_KEY=your_key_here
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

To get a Polygon.io key: sign up at https://polygon.io (free tier is sufficient).
To get a Discord webhook: Server Settings > Integrations > Webhooks > New Webhook.

### Step 3: Adjust Configuration (Optional)

Edit `config.yaml` to tune detection sensitivity:

| Setting | Default | What It Controls |
|---------|---------|------------------|
| `scan_interval_seconds` | 60 | How often to check for new activity |
| `volume_spike_multiplier` | 5.0 | How many times above average to trigger |
| `min_volume` | 100 | Minimum contracts to consider |
| `min_estimated_premium_usd` | 50000 | Minimum dollar premium to alert on |
| `sweep_size_threshold` | 100 | Contracts needed to flag as sweep |
| `watchlist` | 20 tickers | Which tickers to always monitor |
| `discovery.enabled` | true | Auto-discover active tickers beyond watchlist |

### Step 4: Run the Scanner

```bash
python main.py
```

The scanner will:
- Only scan during market hours (9:30 AM - 4:00 PM ET, weekdays)
- Cycle through your watchlist every 60 seconds
- Discover additional active tickers via gainers/losers
- Send Discord alerts for signals passing thresholds
- Log everything to `data/alerts.csv` and `data/signals.db`
- Post a daily summary at 4:15 PM ET

Press `Ctrl+C` for graceful shutdown.

### Step 5: Run via GitHub Actions (Alternative)

Go to your repo's Actions tab, select "Options Flow Scanner", click "Run workflow". This runs a single scan cycle and saves results as downloadable artifacts.

---

## How to Verify It Works (Without a UI)

Since this is a headless CLI tool with no web interface, here's how to confirm everything is functional:

### 1. Run the Test Suite (No API Key Needed)

```bash
python -m pytest tests/ -v
```

This runs **82 automated tests** covering:
- **Signal detection logic** — Verifies volume spikes, sweeps, vol/OI ratios, near-expiry detection, and risk scoring all work correctly with mock data
- **Database operations** — Tests insert, query, batch operations, and data roundtrip integrity using an in-memory SQLite database
- **Alert formatting** — Validates Discord message formatting, CSV logging, batching, and edge cases
- **Scheduler orchestration** — Tests market hours detection, scan cycle flow, discovery mode, and error handling
- **Rate limiter** — Verifies the token-bucket rate limiter respects API limits
- **Data models** — Tests contract label formatting, premium display, CSV serialization

If all 82 tests pass, the core logic is working correctly.

### 2. Dry Run with Logs

Run with DEBUG logging to see everything happening:

Edit `config.yaml`:
```yaml
log_level: DEBUG
```

Then run `python main.py`. Even outside market hours, you'll see:
```
2026-02-14 20:30:00 [INFO] main: Options Flow Scanner starting
2026-02-14 20:30:00 [INFO] main: Watchlist: SPY, QQQ, AAPL, ...
2026-02-14 20:30:00 [DEBUG] scanner.scheduler: Market closed, waiting...
```

### 3. Check the Database After a Session

After running during market hours (or via GitHub Actions):

```python
import asyncio
from scanner.database import SignalDatabase

async def check():
    db = SignalDatabase("data/signals.db")
    await db.initialize()
    signals = await db.get_today_signals("2026-02-14")
    for s in signals:
        print(f"[{s.risk_score}/5] {s.description}")
    await db.close()

asyncio.run(check())
```

### 4. Check the CSV Log

```bash
# View the most recent signals
column -t -s, data/alerts.csv | head -20
```

### 5. Quick Integration Test (During Market Hours)

Run the scanner for just one cycle and check output:
```bash
timeout 120 python main.py
# Then check:
ls -la data/
cat data/alerts.csv
```

---

## How This Benefits from Claude Code and AI Workflow Agents

### With Claude Code Directly

Claude Code can work with this project in several powerful ways:

1. **Live debugging** — When signals aren't triggering as expected, describe the issue and Claude Code can read the detector logic, trace the thresholds, and identify why contracts are being filtered.

2. **Threshold tuning** — Describe your trading style ("I want to catch more pre-earnings activity") and Claude Code can adjust `config.yaml` thresholds, explain the tradeoffs, and run the tests to verify nothing breaks.

3. **Adding new signal types** — Need to detect gamma squeeze setups, unusual put/call ratios, or dark pool prints? Claude Code can extend `detector.py` with new detection methods and write tests for them.

4. **Database queries** — Ask Claude Code to query your `signals.db` for patterns: "Show me all NVDA signals with risk score 4+ from the last week" and it can write and run the SQL.

5. **Test-driven development** — When adding features, Claude Code can write the test first (in `tests/`), then implement the feature, and verify it passes.

### With Agentic Workflows and Automation

This project is structured to work well with AI agent orchestration tools:

**Scheduled Agent Runs:**
- An agent can launch the scanner during market hours, monitor its output, and escalate high-risk signals (risk 4-5) for human review while auto-logging everything else.

**Multi-Agent Analysis Pipeline:**
- **Scanner Agent**: Runs this tool to collect raw signals
- **Analysis Agent**: Takes signals from the SQLite DB, cross-references with news/earnings calendars, and adds context
- **Decision Agent**: Evaluates whether signals match a trading strategy's criteria
- **Execution Agent**: Places orders via a brokerage API if criteria are met

**Backtesting Integration:**
- An agent can query the signals database, fetch actual price outcomes (did the stock move in the predicted direction?), and calculate signal accuracy rates
- This feedback loop can be used to automatically tune thresholds in `config.yaml`

**Multi-Source Correlation:**
- Pair this scanner's output with agents monitoring: SEC filings (13F, insider trades), social sentiment, news feeds, and technical analysis
- An orchestrating agent can correlate unusual options flow with other signals for higher-confidence alerts

**CI/CD with Agent Review:**
- GitHub Actions already runs the scanner — an agent can review the artifact output, compare against historical patterns, and flag anomalies

### Practical Integration Points

The project exposes clean interfaces for agents:

| Interface | How Agents Use It |
|-----------|-------------------|
| `data/signals.db` | SQLite — query with any language/tool |
| `data/alerts.csv` | CSV — ingest into pandas, spreadsheets, dashboards |
| `config.yaml` | YAML — agents can tune thresholds programmatically |
| Discord webhook | Real-time alerts that agents can also consume |
| `scanner/detector.py` | Extend with custom detection logic |
| `scanner/models.py` | Data structures agents can import directly |

---

## Architecture Overview

```
main.py                         Entry point, wiring, shutdown handling
  |
  +-- config.yaml               All tunable parameters
  +-- .env                      API keys (never committed)
  |
  +-- scanner/
       +-- scheduler.py         Orchestrates scan cycles, market hours
       |     |
       |     +-- polygon_client.py   Rate-limited Polygon.io API calls
       |     +-- detector.py         Signal detection + risk scoring
       |     +-- alerts.py           Discord + CSV output
       |     +-- database.py         SQLite persistence
       |
       +-- models.py            OptionsContract + Signal dataclasses
       +-- yfinance_client.py   Free alternative API (no key needed)
  |
  +-- tests/                    82 automated tests
  +-- data/                     Generated output (CSV, SQLite)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "POLYGON_API_KEY not set" | Copy `.env.example` to `.env` and add your key |
| No signals during market hours | Lower `min_volume` or `min_estimated_premium_usd` in config.yaml |
| Rate limit errors (429) | The default 5 calls/min matches Polygon's free tier — upgrade your plan or increase `retry_delay_seconds` |
| "Market closed, waiting..." | The scanner only runs 9:30 AM - 4:00 PM ET on weekdays |
| Discord alerts not appearing | Verify your webhook URL in `.env` — test it manually with curl |
| Tests fail | Run `pip install -r requirements.txt` to ensure all deps are installed |
