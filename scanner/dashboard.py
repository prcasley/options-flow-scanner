"""Web dashboard for monitoring scan results and signal history."""

import logging
from datetime import datetime, timedelta
from aiohttp import web

logger = logging.getLogger(__name__)

# Minimal embedded HTML template — no external dependencies
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Options Flow Scanner</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  h1 { color: #58a6ff; margin-bottom: 8px; }
  .subtitle { color: #8b949e; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card .label { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .card .value { font-size: 28px; font-weight: 700; color: #f0f6fc; margin-top: 4px; }
  .card .value.green { color: #3fb950; }
  .card .value.yellow { color: #d29922; }
  .card .value.red { color: #f85149; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 10px 12px; color: #8b949e; font-size: 12px;
       text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #30363d; }
  td { padding: 10px 12px; border-bottom: 1px solid #21262d; }
  tr:hover td { background: #161b22; }
  .risk-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .risk-1 { background: #1f2a1f; color: #3fb950; }
  .risk-2 { background: #1f2a1f; color: #3fb950; }
  .risk-3 { background: #2a2519; color: #d29922; }
  .risk-4 { background: #2a1f1f; color: #f85149; }
  .risk-5 { background: #3d1f1f; color: #ff7b72; }
  .signal-tag { display: inline-block; padding: 2px 6px; margin: 1px 2px; border-radius: 4px;
                font-size: 11px; background: #1f2937; color: #79c0ff; }
  .refresh-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .refresh-bar button { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
                         padding: 6px 16px; border-radius: 6px; cursor: pointer; }
  .refresh-bar button:hover { background: #30363d; }
  .empty { text-align: center; padding: 40px; color: #484f58; }
</style>
</head>
<body>
<div class="container">
  <h1>Options Flow Scanner</h1>
  <p class="subtitle">Real-time unusual options activity monitor</p>
  <div class="grid" id="metrics"></div>
  <div class="refresh-bar">
    <h2 style="color:#f0f6fc">Recent Signals</h2>
    <button onclick="loadData()">Refresh</button>
  </div>
  <div id="signals-table"></div>
</div>
<script>
async function loadData() {
  try {
    const [statusRes, signalsRes] = await Promise.all([
      fetch('/api/status'), fetch('/api/signals?limit=50')
    ]);
    const status = await statusRes.json();
    const signals = await signalsRes.json();
    renderMetrics(status);
    renderSignals(signals);
  } catch(e) { console.error('Failed to load data', e); }
}
function renderMetrics(s) {
  const statusColor = s.status === 'running' ? 'green' : 'yellow';
  document.getElementById('metrics').innerHTML = `
    <div class="card"><div class="label">Status</div><div class="value ${statusColor}">${s.status}</div></div>
    <div class="card"><div class="label">Uptime</div><div class="value">${formatUptime(s.uptime_seconds)}</div></div>
    <div class="card"><div class="label">Scan Cycles</div><div class="value">${s.scan_count}</div></div>
    <div class="card"><div class="label">Signals Today</div><div class="value">${s.signal_count}</div></div>
    <div class="card"><div class="label">Last Scan</div><div class="value" style="font-size:16px">${s.last_scan_time || 'N/A'}</div></div>
  `;
}
function formatUptime(sec) {
  if (!sec) return '0s';
  const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60);
  return h > 0 ? h+'h '+m+'m' : m+'m';
}
function renderSignals(signals) {
  if (!signals.length) {
    document.getElementById('signals-table').innerHTML = '<div class="empty">No signals yet today</div>';
    return;
  }
  let html = `<table><thead><tr><th>Time</th><th>Ticker</th><th>Contract</th><th>Risk</th>
    <th>Volume</th><th>Premium</th><th>Signals</th></tr></thead><tbody>`;
  for (const s of signals) {
    const time = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '';
    const side = s.contract_type === 'call' ? 'C' : 'P';
    const contract = s.strike + side + ' ' + s.expiry;
    const premium = s.estimated_premium >= 1e6 ? '$'+(s.estimated_premium/1e6).toFixed(1)+'M'
                  : s.estimated_premium >= 1e3 ? '$'+Math.round(s.estimated_premium/1e3)+'K'
                  : '$'+Math.round(s.estimated_premium);
    const tags = (s.signal_types||[]).map(t => `<span class="signal-tag">${t}</span>`).join('');
    html += `<tr><td>${time}</td><td><strong>${s.ticker}</strong></td><td>${contract}</td>
      <td><span class="risk-badge risk-${s.risk_score}">${s.risk_score}/5</span></td>
      <td>${s.volume.toLocaleString()}</td><td>${premium}</td><td>${tags}</td></tr>`;
  }
  html += '</tbody></table>';
  document.getElementById('signals-table').innerHTML = html;
}
loadData();
setInterval(loadData, 30000);
</script>
</body>
</html>"""


class DashboardServer:
    """Extends the health server with a web dashboard and API endpoints."""

    def __init__(self, health_server, db):
        self.health = health_server
        self.db = db
        self._register_routes()

    def _register_routes(self):
        app = self.health._app
        app.router.add_get("/", self._dashboard)
        app.router.add_get("/api/status", self._api_status)
        app.router.add_get("/api/signals", self._api_signals)
        app.router.add_get("/api/signals/{ticker}", self._api_ticker_signals)

    async def _dashboard(self, request: web.Request) -> web.Response:
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

    async def _api_status(self, request: web.Request) -> web.Response:
        uptime = (datetime.utcnow() - self.health._started_at).total_seconds()
        body = {
            "status": "running" if self.health.is_running else "idle",
            "uptime_seconds": round(uptime, 1),
            "scan_count": self.health.scan_count,
            "signal_count": self.health.signal_count,
            "last_scan_time": (self.health.last_scan_time.isoformat()
                               if self.health.last_scan_time else None),
            "last_error": self.health.last_error,
        }
        return web.json_response(body)

    async def _api_signals(self, request: web.Request) -> web.Response:
        limit = min(int(request.query.get("limit", "50")), 200)
        date_str = request.query.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
        signals = await self.db.get_today_signals(date_str)
        return web.json_response([self._signal_to_dict(s) for s in signals[:limit]])

    async def _api_ticker_signals(self, request: web.Request) -> web.Response:
        ticker = request.match_info["ticker"].upper()
        limit = min(int(request.query.get("limit", "50")), 200)
        signals = await self.db.get_ticker_history(ticker, limit)
        return web.json_response([self._signal_to_dict(s) for s in signals])

    @staticmethod
    def _signal_to_dict(s) -> dict:
        return {
            "timestamp": s.timestamp.isoformat(),
            "ticker": s.ticker,
            "strike": s.strike,
            "expiry": s.expiry,
            "contract_type": s.contract_type,
            "volume": s.volume,
            "open_interest": s.open_interest,
            "estimated_premium": s.estimated_premium,
            "risk_score": s.risk_score,
            "signal_types": s.signal_types,
            "volume_ratio": s.volume_ratio,
            "oi_ratio": s.oi_ratio,
            "description": s.description,
        }
