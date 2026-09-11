"""Local read-only dashboard fed by the Python trading state."""

import json
import os
import threading
import time
import urllib.request
import webbrowser
from dataclasses import asdict, is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RKL Algo Control Center</title>
  <style>
    :root {
      --bg: #0a0f14;
      --bg-2: #121b22;
      --panel: #121b24;
      --panel-2: #0d151b;
      --line: #243545;
      --text: #edf4fb;
      --muted: #8ea5b8;
      --green: #52d88f;
      --amber: #f3c76a;
      --red: #ff6a7d;
      --cyan: #62d7ff;
      --shadow: rgba(0,0,0,0.22);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: linear-gradient(180deg, var(--bg) 0%, var(--bg-2) 100%); color: var(--text); font-family: "Segoe UI", Tahoma, sans-serif; }
    .shell { max-width: 1400px; margin: 0 auto; padding: 18px; }
    .topbar { background: rgba(10,15,20,0.86); border-bottom: 1px solid var(--line); padding: 12px 18px; }
    .topbar-inner { max-width: 1400px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
    .brand { font-weight: 700; letter-spacing: 0.14rem; text-transform: uppercase; }
    .small { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.11rem; text-transform: uppercase; }
    .chip { display: inline-flex; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--line); background: var(--panel); font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06rem; }
    .chip.ok { color: var(--green); }
    .chip.warn { color: var(--amber); }
    .chip.bad { color: var(--red); }
    .chip.info { color: var(--cyan); }
    .layout { display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(340px, 1fr); gap: 16px; margin-top: 16px; }
    .stack { display: grid; gap: 16px; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 10px 30px var(--shadow); padding: 14px 16px; }
    .card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    .card h2 { margin: 0; font-size: 0.72rem; letter-spacing: 0.16rem; text-transform: uppercase; color: var(--muted); }
    .label { color: var(--muted); font-size: 0.68rem; letter-spacing: 0.08rem; text-transform: uppercase; }
    .market-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .instrument { border: 1px solid var(--line); background: linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%); border-radius: 12px; padding: 12px; }
    .instrument h3 { margin: 0 0 10px; font-size: 1rem; letter-spacing: 0.08rem; text-transform: uppercase; }
    .ltp-row { display: flex; justify-content: space-between; align-items: baseline; }
    .ltp { font-size: clamp(1.4rem, 2vw, 2.2rem); font-weight: 700; }
    .meta { text-align: right; color: var(--muted); font-size: 0.7rem; }
    .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .metric { border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,0.02); padding: 8px 9px; }
    .metric-label { display: block; color: var(--muted); font-size: 0.64rem; letter-spacing: 0.07rem; text-transform: uppercase; margin-bottom: 4px; }
    .metric-value { font-size: 0.84rem; font-weight: 600; }
    table { width: 100%; border-collapse: collapse; }
    td { padding: 6px 0; border-bottom: 1px solid var(--line); font-size: 0.75rem; }
    td:first-child { width: 120px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05rem; }
    .data-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .entry { border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,0.02); padding: 10px 12px; }
    .signal-panel { border-left: 4px solid var(--amber); background: var(--panel-2); }
    .signal-box { border: 1px solid var(--line); border-radius: 10px; background: rgba(255,255,255,0.02); padding: 12px; }
    .events { display: grid; gap: 8px; max-height: 220px; overflow: auto; }
    .event-line { padding: 7px 9px; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,0.02); font-size: 0.76rem; }
    .dim { color: var(--muted); }
    .ok { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }
    .info { color: var(--cyan); }
    @media (max-width: 980px) { .layout { grid-template-columns: 1fr; } .market-grid, .data-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div>
        <div class="brand">RKL Algo Trading Control Center</div>
        <div class="small">Read-only market intelligence</div>
      </div>
      <div id="headerBadges"></div>
    </div>
  </header>

  <main class="shell">
    <div class="card">
      <div class="card-head">
        <h2>Market status</h2>
        <span class="label" id="marketStatus">UNKNOWN</span>
      </div>
      <div class="data-grid" id="marketStatusGrid"></div>
    </div>

    <div class="layout">
      <div class="stack">
        <section class="card">
          <div class="card-head"><h2>Index market data</h2><span class="label">Authoritative runtime state</span></div>
          <div class="market-grid" id="marketGrid"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Data quality</h2><span class="label" id="qualityStatus">READY</span></div>
          <div id="qualityGrid" class="data-grid"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Indicators</h2><span class="label">Backend state</span></div>
          <div id="indicatorGrid" class="data-grid"></div>
        </section>
      </div>

      <div class="stack">
        <section class="card signal-panel">
          <div class="card-head"><h2>Signal engine</h2><span class="label" id="signalState">WAITING</span></div>
          <div id="signalPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Approval</h2><span class="label" id="approvalState">WAITING</span></div>
          <div id="approvalPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Option / stop-loss</h2><span class="label">Authoritative backend</span></div>
          <div id="optionPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Positions</h2><span class="label" id="positionsState">NONE</span></div>
          <div id="positionsPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Orders</h2><span class="label" id="ordersState">NONE</span></div>
          <div id="ordersPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Event stream</h2><span class="label">Recent</span></div>
          <div id="eventsPanel" class="events"></div>
        </section>
      </div>
    </div>
  </main>

  <script>
    const indexNames = ["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY"];
    function fmtNumber(value, digits = 2) {
      if (value === null || value === undefined || value === "") return "--";
      const number = Number(value);
      if (!Number.isFinite(number)) return "--";
      return number.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    function statusClass(value) {
      const text = String(value || "").toUpperCase();
      if (text.includes("OK") || text.includes("READY") || text.includes("LIVE") || text.includes("CONNECTED")) return "ok";
      if (text.includes("WARN") || text.includes("STALE") || text.includes("WAIT") || text.includes("BLOCKED") || text.includes("CLOSED")) return "warn";
      if (text.includes("FAIL") || text.includes("REJECT") || text.includes("INVALID") || text.includes("ERROR")) return "bad";
      return "info";
    }
    function badge(label, tone = "info") {
      return '<span class="chip ' + tone + '">' + label + '</span>';
    }
    function renderHeader(state) {
      const components = state.components || {};
      const labels = [
        badge("MARKET " + (state.market_status || "UNKNOWN").toUpperCase(), state.market_status === "OPEN" ? "ok" : "warn"),
        badge("WS " + (state.ws_status || "DISCONNECTED"), statusClass(state.ws_status)),
        badge("DB " + (components.DATABASE || "READY"), statusClass(components.DATABASE)),
        badge("HIST " + (components.HISTORY || "WAITING"), statusClass(components.HISTORY)),
        badge("SIGNALS " + (components.SIGNALS || "WAITING"), statusClass(components.SIGNALS)),
        badge("ORDERS " + (components.ORDERS || "DISABLED"), statusClass(components.ORDERS))
      ];
      document.getElementById("headerBadges").innerHTML = labels.join("");
    }
    function renderMarketStatus(state) {
      const market = state.market_status || "UNKNOWN";
      const latestValue = state.latest && Object.values(state.latest).length ? Object.values(state.latest)[0] : null;
      const previousValue = state.previous && Object.values(state.previous).length ? Object.values(state.previous)[0] : null;
      const data = [
        ["Market", market],
        ["Last update", state.last_event || "--"],
        ["Last valid tick", latestValue && latestValue.timestamp ? new Date(latestValue.timestamp).toLocaleTimeString("en-IN", { hour12: false }) : "--"],
        ["Last finalized candle", previousValue && previousValue.timestamp ? new Date(previousValue.timestamp).toLocaleTimeString("en-IN", { hour12: false }) : "--"]
      ];
      document.getElementById("marketStatusGrid").innerHTML = data.map(([label, value]) => '<div class="metric"><span class="metric-label">' + label + '</span><div class="metric-value">' + value + '</div></div>').join("");
      document.getElementById("marketStatus").textContent = market.toUpperCase();
      document.getElementById("marketStatus").className = "label " + statusClass(market);
    }
    function renderMarketGrid(state) {
      const cards = indexNames.map((name) => {
        const tick = state.latest?.[name];
        const previous = state.previous?.[name];
        const running = state.candles?.[name];
        const health = state.health?.[name] || "WAITING";
        const label = tick && tick.timestamp ? new Date(tick.timestamp).toLocaleTimeString("en-IN", { hour12: false }) : "--";
        const prevText = previous ? "O " + fmtNumber(previous.open) + " H " + fmtNumber(previous.high) + " L " + fmtNumber(previous.low) + " C " + fmtNumber(previous.close) : "--";
        const runText = running ? "O " + fmtNumber(running.open) + " H " + fmtNumber(running.high) + " L " + fmtNumber(running.low) + " C " + fmtNumber(running.close) : "--";
        return '<article class="instrument"><h3>' + name + '</h3><div class="ltp-row"><div class="ltp">' + fmtNumber(tick && tick.ltp, 2) + '</div><div class="meta"><div>' + label + '</div><div class="' + statusClass(health) + '">' + health + '</div></div></div><div class="metric-grid"><div class="metric"><span class="metric-label">LTP age</span><div class="metric-value">' + (tick ? "LIVE" : "WAITING") + '</div></div><div class="metric"><span class="metric-label">State</span><div class="metric-value ' + statusClass(health) + '">' + health + '</div></div></div><table><tr><td>Previous 5M</td><td>' + prevText + '</td></tr><tr><td>Running 5M</td><td>' + runText + '</td></tr></table></article>';
      }).join("");
      document.getElementById("marketGrid").innerHTML = cards;
    }
    function renderQuality(state) {
      const rows = indexNames.map((name) => {
        const sync = state.sync?.[name] || {};
        const signal = state.signal && state.signal.underlying === name ? state.signal : null;
        const signalStatus = signal ? "SIGNAL ACTIVE" : (state.market_status === "CLOSED" ? "BLOCKED" : "READY");
        const details = [
          ["WS", state.ws_status || "DISCONNECTED"],
          ["LTP", state.latest?.[name] ? "VALID" : "STALE"],
          ["5M", state.candles?.[name] ? "READY" : "STALE"],
          ["History", sync.status || "READY"],
          ["Indicators", state.indicators?.[name] ? "READY" : "WAITING"],
          ["Signal", signalStatus]
        ];
        return '<div class="entry"><strong>' + name + '</strong><div class="dim">' + details.map(([label, value]) => label + ': <span class="' + statusClass(value) + '">' + value + '</span>').join(" · ") + '</div></div>';
      });
      document.getElementById("qualityGrid").innerHTML = rows.join("");
      document.getElementById("qualityStatus").textContent = state.market_status === "OPEN" ? "LIVE" : "FROZEN";
    }
    function renderIndicators(state) {
      const entries = indexNames.map((name) => {
        const values = state.indicators?.[name] || [null, null];
        return '<div class="entry"><strong>' + name + '</strong><div>RSI14: <span class="info">' + fmtNumber(values[1], 2) + '</span></div><div>CCI5: <span class="info">' + fmtNumber(values[0], 2) + '</span></div></div>';
      });
      document.getElementById("indicatorGrid").innerHTML = entries.join("");
    }
    function renderSignalPanel(state) {
      const panel = document.getElementById("signalPanel");
      const signal = state.signal;
      if (!signal) {
        panel.innerHTML = '<div class="entry"><strong>WAITING</strong><div>NO ACTIVE SIGNAL</div></div>';
        document.getElementById("signalState").textContent = "WAITING";
        return;
      }
      panel.innerHTML = '<div class="entry"><strong>' + (signal.underlying || "--") + '</strong><div>Direction: ' + (signal.direction || "--") + '</div><div>Signal time: ' + (signal.timestamp || "--") + '</div><div>State: ' + (signal.status || "ACTIVE") + '</div></div>';
      document.getElementById("signalState").textContent = "ACTIVE";
    }
    function renderApprovalPanel(state) {
      const panel = document.getElementById("approvalPanel");
      const signal = state.signal;
      if (!signal) {
        panel.innerHTML = '<div class="entry"><strong>WAITING FOR APPROVAL</strong><div>NO ACTIVE SIGNAL</div></div>';
        document.getElementById("approvalState").textContent = "WAITING";
        return;
      }
      panel.innerHTML = '<div class="entry"><strong>' + (signal.underlying || "--") + '</strong><div>CALL / PUT: ' + (signal.direction || "--") + '</div><div>APPROVAL: ' + (signal.status || "WAITING FOR APPROVAL") + '</div><div>Signal age: ' + (signal.timestamp || "--") + '</div></div>';
      document.getElementById("approvalState").textContent = (signal.status || "WAITING FOR APPROVAL").toUpperCase();
    }
    function renderOptionPanel(state) {
      const panel = document.getElementById("optionPanel");
      const signal = state.signal;
      panel.innerHTML = signal ? '<div class="entry"><strong>' + (signal.underlying || "--") + '</strong><div>Direction: ' + (signal.direction || "--") + '</div><div>Expiry: ' + (signal.expiry || "--") + '</div><div>Strike: ' + (signal.strike || "--") + '</div><div>Option: ' + (signal.option || "--") + '</div><div>SL: ' + (signal.sl || "--") + '</div></div>' : '<div class="entry"><strong>OPTION</strong><div>—</div></div>';
    }
    function renderPositions(state) {
      const panel = document.getElementById("positionsPanel");
      const items = state.positions && state.positions.length ? state.positions : ["NO ACTIVE POSITIONS"];
      panel.innerHTML = items.map((item) => '<div class="entry">' + item + '</div>').join("");
      document.getElementById("positionsState").textContent = state.positions && state.positions.length ? "ACTIVE" : "NONE";
    }
    function renderOrders(state) {
      const panel = document.getElementById("ordersPanel");
      const items = state.orders && state.orders.length ? state.orders : ["NO ORDERS"];
      panel.innerHTML = items.map((item) => '<div class="entry">' + item + '</div>').join("");
      document.getElementById("ordersState").textContent = state.orders && state.orders.length ? "ACTIVE" : "NONE";
    }
    function renderEvents(state) {
      const events = (state.events || []).slice(-8).reverse();
      document.getElementById("eventsPanel").innerHTML = events.length ? events.map((item) => '<div class="event-line">' + item + '</div>').join("") : '<div class="event-line dim">No events yet.</div>';
    }
    function render(state) {
      renderHeader(state);
      renderMarketStatus(state);
      renderMarketGrid(state);
      renderQuality(state);
      renderIndicators(state);
      renderSignalPanel(state);
      renderApprovalPanel(state);
      renderOptionPanel(state);
      renderPositions(state);
      renderOrders(state);
      renderEvents(state);
    }
    async function refreshState() {
      try {
        const response = await fetch("/state");
        if (!response.ok) return;
        const payload = await response.json();
        render(payload);
      } catch (error) {
        document.getElementById("marketStatus").textContent = "DISCONNECTED";
      }
    }
    document.addEventListener("DOMContentLoaded", () => {
      refreshState();
      setInterval(refreshState, 1500);
    });
  </script>
</body>
</html>"""


def _json_value(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class DashboardServer:
    def __init__(self, state, host="127.0.0.1", port=8765):
        self.state = state
        self.host = host
        self.port = port
        self.server = None
        self.thread = None
        self._stop = threading.Event()
        self.url = f"http://{self.host}:{self.port}/"

    def start(self, open_browser=True):
        state = self.state
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def do_GET(self):
                if self.path == "/health":
                    snapshot = state.snapshot()
                    components = snapshot.get("components", {})
                    healthy = components.get("DATABASE") == "READY" and components.get("HISTORY") == "READY"
                    payload = json.dumps({
                        "status": "ok" if healthy else "degraded",
                        "components": components,
                        "feed": snapshot.get("ws_status", "UNKNOWN")
                    }, default=_json_value).encode("utf-8")
                    self.send_response(200 if healthy else 503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/state":
                    payload = json.dumps(state.snapshot(), default=_json_value).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/":
                    payload = HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/events":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    try:
                        while not owner._stop.is_set():
                            payload = json.dumps(state.snapshot(), default=_json_value)
                            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                            self.wfile.flush()
                            time.sleep(0.5)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                        pass
                    return

                self.send_error(404)

        try:
            self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as error:
            raise RuntimeError(f"Dashboard could not bind to {self.host}:{self.port}: {error}") from error

        self.thread = threading.Thread(target=self.server.serve_forever, name="local-dashboard", daemon=True)
        self.thread.start()
        self._wait_for_health(timeout=10)
        if open_browser:
            self._open_browser()
        return self.url

    def _wait_for_health(self, timeout=10):
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.url}health", timeout=1) as response:
                    if response.status == 200:
                        return True
                    last_error = RuntimeError(f"Dashboard health endpoint returned HTTP {response.status}")
            except Exception as error:  # pragma: no cover - network retry path
                last_error = error
            time.sleep(0.25)
        raise RuntimeError(f"Dashboard health check failed at {self.url}health: {last_error}")

    def _open_browser(self):
        if os.environ.get("DISPLAY") is None and os.name != "nt":
            return False
        try:
            opened = webbrowser.open(self.url)
            if not opened:
                print(f"DASHBOARD READY\n{self.url}", flush=True)
            return opened
        except Exception as error:  # pragma: no cover - browser launch is environment-dependent
            print(f"DASHBOARD READY\n{self.url}\nBROWSER OPEN FAILED: {error}", flush=True)
            return False

    def stop(self):
        self._stop.set()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
