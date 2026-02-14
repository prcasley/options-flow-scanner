"""Web dashboard for Options Flow Scanner."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DB_PATH = BASE_DIR / "data" / "signals.db"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_db():
    """Get a read-only SQLite connection."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db


@app.route("/")
def index():
    config = load_config()
    return render_template("index.html", watchlist=config.get("watchlist", []))


@app.route("/api/signals")
def api_signals():
    """Return signals as JSON, with optional filters."""
    ticker = request.args.get("ticker", "").upper()
    risk_min = request.args.get("risk_min", type=int)
    risk_max = request.args.get("risk_max", type=int)
    contract_type = request.args.get("contract_type", "")
    date = request.args.get("date", "")
    limit = request.args.get("limit", 200, type=int)

    if not DB_PATH.exists():
        return jsonify({"signals": [], "total": 0})

    db = get_db()
    query = "SELECT * FROM signals WHERE 1=1"
    params = []

    if ticker:
        query += " AND ticker = ?"
        params.append(ticker)
    if risk_min is not None:
        query += " AND risk_score >= ?"
        params.append(risk_min)
    if risk_max is not None:
        query += " AND risk_score <= ?"
        params.append(risk_max)
    if contract_type in ("call", "put"):
        query += " AND contract_type = ?"
        params.append(contract_type)
    if date:
        query += " AND timestamp LIKE ?"
        params.append(f"{date}%")

    count_query = query.replace("SELECT *", "SELECT COUNT(*)", 1)
    total = db.execute(count_query, params).fetchone()[0]

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    db.close()

    signals = []
    for row in rows:
        signals.append({
            "id": row["id"],
            "timestamp": row["timestamp"],
            "ticker": row["ticker"],
            "strike": row["strike"],
            "expiry": row["expiry"],
            "contract_type": row["contract_type"],
            "volume": row["volume"],
            "open_interest": row["open_interest"],
            "estimated_premium": row["estimated_premium"],
            "risk_score": row["risk_score"],
            "signal_types": row["signal_types"],
            "volume_ratio": row["volume_ratio"],
            "oi_ratio": row["oi_ratio"],
            "description": row["description"],
            "last_price": row["last_price"],
        })

    return jsonify({"signals": signals, "total": total})


@app.route("/api/stats")
def api_stats():
    """Return summary statistics."""
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    if not DB_PATH.exists():
        return jsonify({
            "total_signals": 0,
            "high_risk_count": 0,
            "total_premium": 0,
            "top_tickers": [],
            "risk_distribution": {str(i): 0 for i in range(1, 6)},
            "calls_vs_puts": {"calls": 0, "puts": 0},
            "recent_count": 0,
        })

    db = get_db()

    # Total signals for the date
    total = db.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp LIKE ?",
        (f"{date}%",)
    ).fetchone()[0]

    # High risk (4-5)
    high_risk = db.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp LIKE ? AND risk_score >= 4",
        (f"{date}%",)
    ).fetchone()[0]

    # Total premium
    prem_row = db.execute(
        "SELECT COALESCE(SUM(estimated_premium), 0) FROM signals WHERE timestamp LIKE ?",
        (f"{date}%",)
    ).fetchone()
    total_premium = prem_row[0]

    # Top tickers by signal count
    top_tickers = db.execute(
        """SELECT ticker, COUNT(*) as cnt, SUM(estimated_premium) as prem
           FROM signals WHERE timestamp LIKE ?
           GROUP BY ticker ORDER BY cnt DESC LIMIT 10""",
        (f"{date}%",)
    ).fetchall()

    # Risk distribution
    risk_dist = {}
    for i in range(1, 6):
        count = db.execute(
            "SELECT COUNT(*) FROM signals WHERE timestamp LIKE ? AND risk_score = ?",
            (f"{date}%", i)
        ).fetchone()[0]
        risk_dist[str(i)] = count

    # Calls vs Puts
    calls = db.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp LIKE ? AND contract_type = 'call'",
        (f"{date}%",)
    ).fetchone()[0]
    puts = db.execute(
        "SELECT COUNT(*) FROM signals WHERE timestamp LIKE ? AND contract_type = 'put'",
        (f"{date}%",)
    ).fetchone()[0]

    # All-time total
    all_time = db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

    db.close()

    return jsonify({
        "total_signals": total,
        "high_risk_count": high_risk,
        "total_premium": total_premium,
        "top_tickers": [
            {"ticker": r["ticker"], "count": r["cnt"], "premium": r["prem"]}
            for r in top_tickers
        ],
        "risk_distribution": risk_dist,
        "calls_vs_puts": {"calls": calls, "puts": puts},
        "all_time_total": all_time,
    })


@app.route("/api/config")
def api_config():
    """Return current scanner configuration."""
    config = load_config()
    return jsonify({
        "watchlist": config.get("watchlist", []),
        "scan_interval": config.get("scan_interval_seconds", 60),
        "thresholds": config.get("thresholds", {}),
        "discovery_enabled": config.get("discovery", {}).get("enabled", False),
        "market_hours": config.get("market", {}),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
