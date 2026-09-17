"""Local read-only dashboard fed by the Python trading state."""

import asyncio
import hmac
import json
import os
import threading
import time
import urllib.request
import webbrowser
from dataclasses import asdict, is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from ui_contracts import build_observer_envelope, build_observer_payload

try:
  import websockets
except ImportError:  # pragma: no cover - dependency is installed for mobile deployment
  websockets = None

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RKL Algo Control Center</title>
  <style>
    :root { --bg: #081217; --bg-2: #101e24; --panel: rgba(17, 31, 37, 0.92); --panel-2: #0c1b20; --line: #28434b; --text: #edf7f5; --muted: #8ba6aa; --green: #57dda3; --amber: #f4c76d; --red: #ff7182; --cyan: #70dcf2; --accent: #70dcf2; --shadow: rgba(0, 0, 0, 0.28); }
    :root[data-theme="arctic"] { --bg: #eaf1f3; --bg-2: #d5e1e5; --panel: rgba(250, 252, 252, 0.94); --panel-2: #edf4f5; --line: #b7cbd0; --text: #152a31; --muted: #5e747b; --green: #087f5b; --amber: #a46600; --red: #b42318; --cyan: #006d8f; --accent: #006d8f; --shadow: rgba(39, 67, 80, 0.16); }
    :root[data-theme="midnight"] { --bg: #070b13; --bg-2: #121a2c; --panel: rgba(18, 27, 48, 0.94); --panel-2: #0b1221; --line: #2d4163; --text: #f5f7ff; --muted: #91a5c0; --green: #73e0ad; --amber: #f4c66d; --red: #ff7c8b; --cyan: #74d9ff; --accent: #a6b8ff; --shadow: rgba(0, 0, 0, 0.36); }
    :root[data-theme="copper"] { --bg: #17110d; --bg-2: #2a1b13; --panel: rgba(48, 31, 23, 0.94); --panel-2: #211610; --line: #66483a; --text: #fff4e8; --muted: #c7a992; --green: #8ee0ac; --amber: #f4b66d; --red: #ff8580; --cyan: #8fd9d5; --accent: #e5a56f; --shadow: rgba(15, 7, 3, 0.35); }
    :root[data-theme="emerald"] { --bg: #061511; --bg-2: #0e2b22; --panel: rgba(12, 43, 34, 0.94); --panel-2: #09231c; --line: #245e4d; --text: #e7fff2; --muted: #86b9a5; --green: #73efb0; --amber: #e9ca73; --red: #ff807f; --cyan: #81e4d4; --accent: #73efb0; --shadow: rgba(0, 12, 8, 0.35); }
    :root[data-theme="paper"] { --bg: #f2eee6; --bg-2: #e4ded2; --panel: rgba(255, 253, 248, 0.96); --panel-2: #f5f0e7; --line: #d3c8b6; --text: #2c2823; --muted: #776c5d; --green: #17734e; --amber: #a96812; --red: #b63b32; --cyan: #1d7180; --accent: #9b4d2e; --shadow: rgba(78, 63, 44, 0.15); }
    :root[data-theme="solarized"] { --bg: #002b36; --bg-2: #073642; --panel: rgba(7, 54, 66, 0.95); --panel-2: #04313c; --line: #1b5662; --text: #eee8d5; --muted: #93a1a1; --green: #859900; --amber: #b58900; --red: #dc322f; --cyan: #2aa198; --accent: #cb4b16; --shadow: rgba(0, 20, 25, 0.36); }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; max-width: 100%; overflow-x: hidden; background: radial-gradient(circle at 90% -10%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 38%), linear-gradient(145deg, var(--bg) 0%, var(--bg-2) 100%); color: var(--text); font-family: "Aptos", "Trebuchet MS", sans-serif; }
    .shell { width: min(100%, 1480px); margin: 0 auto; padding: 20px clamp(14px, 2.4vw, 34px) 44px; }
    .topbar { background: color-mix(in srgb, var(--bg) 88%, transparent); border-bottom: 1px solid var(--line); padding: 16px clamp(14px, 2.4vw, 34px); position: sticky; top: 0; z-index: 5; backdrop-filter: blur(18px); }
    .topbar-inner { max-width: 1480px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; gap: 24px; }
    .brand { font-size: 1.02rem; font-weight: 800; letter-spacing: 0.13rem; text-transform: uppercase; }
    .toolbar { display: flex; align-items: center; justify-content: flex-end; gap: 12px; min-width: 0; }
    select { color: var(--text); background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px; font: inherit; font-size: 0.78rem; }
    .small { color: var(--muted); font-size: 0.66rem; letter-spacing: 0.12rem; text-transform: uppercase; }
    .chip { display: inline-flex; align-items: center; min-height: 26px; padding: 5px 9px; border-radius: 7px; border: 1px solid var(--line); background: color-mix(in srgb, var(--panel) 88%, transparent); font-size: 0.63rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05rem; white-space: nowrap; }
    .chip.ok { color: var(--green); }
    .chip.warn { color: var(--amber); }
    .chip.bad { color: var(--red); }
    .chip.info { color: var(--cyan); }
    .layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(360px, 0.95fr); gap: 20px; margin-top: 20px; align-items: start; }
    .stack { display: grid; gap: 20px; min-width: 0; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 14px 36px var(--shadow); padding: 18px; min-width: 0; }
    .card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
    .card h2 { margin: 0; font-size: 0.73rem; letter-spacing: 0.15rem; text-transform: uppercase; color: var(--muted); }
    .label { color: var(--muted); font-size: 0.65rem; letter-spacing: 0.08rem; text-transform: uppercase; text-align: right; }
    .market-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .instrument { min-width: 0; border: 1px solid var(--line); border-top: 2px solid var(--accent); background: linear-gradient(145deg, var(--panel) 0%, var(--panel-2) 100%); border-radius: 10px; padding: 15px; }
    .instrument h3 { margin: 0 0 12px; font-size: 0.98rem; letter-spacing: 0.08rem; text-transform: uppercase; }
    .ltp-row { display: flex; justify-content: space-between; align-items: baseline; }
    .ltp { font-size: clamp(1.55rem, 2.4vw, 2.45rem); font-weight: 800; letter-spacing: -0.03rem; }
    .meta { text-align: right; color: var(--muted); font-size: 0.7rem; }
    .metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
    .metric { border: 1px solid var(--line); border-radius: 8px; background: color-mix(in srgb, var(--panel-2) 80%, transparent); padding: 9px 10px; min-width: 0; }
    .metric-label { display: block; color: var(--muted); font-size: 0.64rem; letter-spacing: 0.07rem; text-transform: uppercase; margin-bottom: 4px; }
    .metric-value { font-size: 0.84rem; font-weight: 600; }
    table { width: 100%; max-width: 100%; table-layout: fixed; border-collapse: collapse; }
    td { padding: 8px 4px 8px 0; border-bottom: 1px solid var(--line); font-size: 0.74rem; overflow-wrap: anywhere; }
    td:first-child { width: 120px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05rem; }
    .data-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .entry { border: 1px solid var(--line); border-radius: 9px; background: color-mix(in srgb, var(--panel-2) 82%, transparent); padding: 12px 13px; line-height: 1.55; min-width: 0; }
    .signal-panel { border-left: 4px solid var(--accent); background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 9%, var(--panel)), var(--panel)); }
    .signal-box { border: 1px solid var(--line); border-radius: 9px; background: color-mix(in srgb, var(--panel-2) 84%, transparent); padding: 13px; }
    .events { display: grid; gap: 9px; max-height: 250px; overflow: auto; padding-right: 2px; }
    .event-line { padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: color-mix(in srgb, var(--panel-2) 82%, transparent); font-size: 0.74rem; line-height: 1.45; }
    .dim { color: var(--muted); }
    .ok { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }
    .info { color: var(--cyan); }
    .notice { position: fixed; right: 18px; bottom: 18px; z-index: 10; max-width: min(420px, calc(100vw - 36px)); padding: 12px 14px; border: 1px solid var(--cyan); border-radius: 10px; background: rgba(13,21,27,0.96); box-shadow: 0 12px 36px var(--shadow); opacity: 0; transform: translateY(12px); transition: opacity .18s ease, transform .18s ease; pointer-events: none; }
    .notice.visible { opacity: 1; transform: translateY(0); }
    .connection { display: inline-flex; align-items: center; gap: 7px; margin-left: 10px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); }
    .dot.off { background: var(--red); }
    @media (max-width: 1120px) { .topbar-inner { align-items: flex-start; flex-direction: column; } .toolbar { width: 100%; justify-content: space-between; } }
    @media (max-width: 980px) { .layout { grid-template-columns: 1fr; } .market-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 620px) { .shell { padding-top: 14px; } .toolbar { align-items: flex-start; flex-wrap: wrap; } .market-grid, .data-grid { grid-template-columns: 1fr; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .card { padding: 14px; } .card-head { align-items: flex-start; flex-direction: column; } .label { text-align: left; } }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <div>
        <div class="brand">RKL Algo Trading Control Center</div>
        <div class="small">Read-only market intelligence</div>
      </div>
      <div class="toolbar"><select id="themeSelect" aria-label="Dashboard theme"><option value="obsidian">Obsidian Pro</option><option value="arctic">Arctic Institutional</option><option value="midnight">Midnight Quant</option><option value="copper">Copper Terminal</option><option value="emerald">Emerald Ledger</option><option value="paper">Paper Research</option><option value="solarized">Solarized Focus</option></select><div id="headerBadges"><span class="connection"><span class="dot" id="connectionDot"></span><span class="small" id="connectionText">CONNECTING</span></span></div></div>
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

    <div class="card">
      <div class="card-head">
        <h2>Pipeline state</h2>
        <span class="label" id="pipelineStateLabel">UNAVAILABLE</span>
      </div>
      <div class="data-grid" id="pipelineGrid"></div>
    </div>

    <div class="layout">
      <div class="stack">
        <div class="small">DATA WINDOW | MARKET INTELLIGENCE</div>
        <section class="card">
          <div class="card-head"><h2>Index market data</h2><span class="label">Authoritative runtime state</span></div>
          <div class="market-grid" id="marketGrid"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>5-minute price window</h2><span class="label">Backend candles only</span></div>
          <canvas id="candleChart" height="220" aria-label="Five minute candle chart"></canvas>
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
        <div class="small">TRADING WINDOW | SIGNALS, POSITIONS, ORDERS</div>
        <section class="card signal-panel">
          <div class="card-head"><h2>Signal engine</h2><span class="label" id="signalState">WAITING</span></div>
          <div id="signalPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Signal monitor</h2><span class="label">Type 1 / Type 2 audit</span></div>
          <div id="signalHistoryPanel" class="events"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Automatic entry</h2><span class="label" id="approvalState">GUARDED</span></div>
          <div id="approvalPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>ATM OPTION EXECUTION</h2><span class="label">Authoritative backend</span></div>
          <div id="optionPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Positions</h2><span class="label" id="positionsState">NONE</span></div>
          <div id="positionsPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Closed trades</h2><span class="label">Recent backend records</span></div>
          <div id="closedTradesPanel" class="events"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Orders</h2><span class="label" id="ordersState">NONE</span></div>
          <div id="ordersPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Fills</h2><span class="label" id="fillsState">UNAVAILABLE</span></div>
          <div id="fillsPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Exit monitor</h2><span class="label" id="exitsState">UNAVAILABLE</span></div>
          <div id="exitsPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Incidents</h2><span class="label" id="incidentsState">UNAVAILABLE</span></div>
          <div id="incidentsPanel" class="events"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Report</h2><span class="label" id="reportState">UNAVAILABLE</span></div>
          <div id="reportPanel" class="signal-box"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Event stream</h2><span class="label">Recent</span></div>
          <div id="eventsPanel" class="events"></div>
        </section>
      </div>
    </div>
  </main>
  <div id="notice" class="notice"></div>

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
        badge("DATA " + (components["DATA FEED"] || "WAITING"), statusClass(components["DATA FEED"])),
        badge("DB " + (components.DATABASE || "READY"), statusClass(components.DATABASE)),
        badge("HIST " + (components.HISTORY || "WAITING"), statusClass(components.HISTORY)),
        badge("SIGNALS " + (components.SIGNALS || "WAITING"), statusClass(components.SIGNALS)),
        badge("AUTO ENTRY LOGIC " + (components["AUTO ENTRY"] || "DISABLED"), statusClass(components["AUTO ENTRY"])),
        badge("EXECUTION " + (components["EXECUTION MODE"] || "READ_ONLY"), components["EXECUTION MODE"] === "REAL" ? "warn" : "info"),
        badge("ORDERS " + (components.ORDERS || "DISABLED"), statusClass(components.ORDERS)),
        badge("STARTUP " + (state.startup_phase || "STARTING"), statusClass(state.startup_phase))
      ];
      document.getElementById("headerBadges").innerHTML = labels.join("");
    }
    function renderMarketStatus(state) {
      const market = state.market_status || "UNKNOWN";
      const latestValue = state.latest && Object.values(state.latest).sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)))[0];
      const finalized = state.previous ? Object.values(state.previous).filter(item => item && item.timestamp && new Date(item.timestamp).getTime() <= Date.now()) : [];
      const previousValue = finalized.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0] || null;
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
    function renderPipeline(state) {
      const pipeline = state.pipeline_state || {};
      const ordered = [
        ["MARKET DATA", pipeline.market_data || "UNAVAILABLE"],
        ["CANDLE ENGINE", pipeline.candle_engine || "UNAVAILABLE"],
        ["INDICATORS", pipeline.indicators || "UNAVAILABLE"],
        ["STRATEGY", pipeline.strategy || "WAITING"],
        ["SIGNAL", pipeline.signal || "WAITING"],
        ["OPTION", pipeline.option || "UNAVAILABLE"],
        ["ORDER", pipeline.order || "NOT ACTIVE"],
        ["FILL", pipeline.fill || "UNAVAILABLE"],
        ["POSITION", pipeline.position || "NONE"],
        ["EXIT", pipeline.exit || "IDLE"],
        ["BROKER CLOSE", pipeline.broker_close || "WAITING"],
        ["RECONCILIATION", pipeline.reconciliation || "UNAVAILABLE"]
      ];
      document.getElementById("pipelineGrid").innerHTML = ordered.map(([label, value]) => '<div class="metric"><span class="metric-label">' + label + '</span><div class="metric-value ' + statusClass(value) + '">' + value + '</div></div>').join("");
      document.getElementById("pipelineStateLabel").textContent = "UNAVAILABLE";
    }
    function renderMarketGrid(state) {
      const cards = indexNames.map((name) => {
        const tick = state.latest?.[name];
        const prev2 = state.prev2?.[name];
        const previous = state.previous?.[name];
        const running = state.candles?.[name];
        const health = state.health?.[name] || "WAITING";
        const label = tick && tick.timestamp ? new Date(tick.timestamp).toLocaleTimeString("en-IN", { hour12: false }) : "--";
        const age = "UNAVAILABLE";
        const prev2Text = prev2 ? "O " + fmtNumber(prev2.open) + " H " + fmtNumber(prev2.high) + " L " + fmtNumber(prev2.low) + " C " + fmtNumber(prev2.close) : "--";
        const prevText = previous ? "O " + fmtNumber(previous.open) + " H " + fmtNumber(previous.high) + " L " + fmtNumber(previous.low) + " C " + fmtNumber(previous.close) : "--";
        const runText = running ? "O " + fmtNumber(running.open) + " H " + fmtNumber(running.high) + " L " + fmtNumber(running.low) + " C " + fmtNumber(running.close) : "--";
        const source = tick && tick.source ? tick.source : "--";
        const candleState = health || "UNAVAILABLE";
        const ltpState = health || "UNAVAILABLE";
        const exchangeTime = tick && tick.exchange_timestamp ? new Date(tick.exchange_timestamp).toLocaleTimeString("en-IN", { hour12: false }) : label;
        const receivedTime = tick && tick.received_timestamp ? new Date(tick.received_timestamp).toLocaleTimeString("en-IN", { hour12: false }) : "--";
        return '<article class="instrument"><h3>' + name + '</h3><div class="ltp-row"><div class="ltp">' + fmtNumber(tick && tick.ltp, 2) + '</div><div class="meta"><div>' + exchangeTime + '</div><div class="' + statusClass(candleState) + '">' + candleState + '</div></div></div><div class="metric-grid"><div class="metric"><span class="metric-label">LTP state</span><div class="metric-value ' + statusClass(ltpState) + '">' + ltpState + '</div></div><div class="metric"><span class="metric-label">Data age</span><div class="metric-value">' + age + '</div></div><div class="metric"><span class="metric-label">Source</span><div class="metric-value">' + source + '</div></div></div><table><tr><td>Exchange tick</td><td>' + exchangeTime + '</td></tr><tr><td>Received</td><td>' + receivedTime + '</td></tr><tr><td>Prev2 5M</td><td>' + prev2Text + '</td></tr><tr><td>Previous 5M</td><td>' + prevText + '</td></tr><tr><td>Running 5M</td><td>' + runText + '</td></tr></table></article>';
      }).join("");
      document.getElementById("marketGrid").innerHTML = cards;
    }
    function renderQuality(state) {
      const rows = indexNames.map((name) => {
        const sync = state.sync?.[name] || {};
        const signal = state.signal && state.signal.underlying === name ? state.signal : null;
        const signalStatus = signal && signal.status ? signal.status : "UNAVAILABLE";
        const details = [
          ["WS", state.ws_status || "UNAVAILABLE"],
          ["LTP", state.latest?.[name]?.health || "UNAVAILABLE"],
          ["5M", state.candles?.[name]?.status || "UNAVAILABLE"],
          ["History", sync.status || "UNAVAILABLE"],
          ["Indicators", state.indicator_status?.[name] || "UNAVAILABLE"],
          ["Signal", signalStatus]
        ];
        return '<div class="entry"><strong>' + name + '</strong><div class="dim">' + details.map(([label, value]) => label + ': <span class="' + statusClass(value) + '">' + value + '</span>').join(" · ") + '</div></div>';
      });
      document.getElementById("qualityGrid").innerHTML = rows.join("");
      document.getElementById("qualityStatus").textContent = state.quality_status || "UNAVAILABLE";
    }
    function renderIndicators(state) {
      const entries = indexNames.map((name) => {
        const values = state.indicators?.[name] || [null, null];
        const detail = state.indicator_details?.[name] || {};
        const reason = state.indicator_reason?.[name] || "--";
        return '<div class="entry"><strong>' + name + '</strong><div>SMA8/13/21: <span class="info">' + [detail.sma8, detail.sma13, detail.sma21].map(value => fmtNumber(value)).join(' / ') + '</span></div><div>RSI14: <span class="info">' + fmtNumber(values[1], 2) + '</span></div><div>RSI14-SMA5: <span class="info">' + fmtNumber(detail.rsi_sma5, 2) + '</span></div><div>CCI5: <span class="info">' + fmtNumber(values[0], 2) + '</span> · Fast Stochastic14: <span class="info">' + fmtNumber(detail.stochastic14, 2) + '</span></div><div>Trend: <span class="' + statusClass(detail.trend) + '">' + (detail.trend || 'UNAVAILABLE') + '</span></div><div class="dim">' + (reason || "UNAVAILABLE") + '</div></div>';
      });
      document.getElementById("indicatorGrid").innerHTML = entries.join("");
    }
    function renderSignalPanel(state) {
      const panel = document.getElementById("signalPanel");
      const signal = state.signal;
      if (!signal) {
        panel.innerHTML = '<div class="entry"><strong>UNAVAILABLE</strong><div>NO SIGNAL DATA SUPPLIED</div></div>';
        document.getElementById("signalState").textContent = "UNAVAILABLE";
        return;
      }
      const conditions = signal.filters && Object.keys(signal.filters).length ? '<div class="dim">Conditions: ' + Object.entries(signal.filters).map(([key, value]) => key + '=' + (value ? 'PASS' : 'FAIL')).join(' · ') + '</div>' : '';
      const stochastic = (signal.stochastic_values || []).length ? '<div>Closed Stochastic values: ' + signal.stochastic_values.map(value => fmtNumber(value, 2)).join(' · ') + '</div>' : '';
      panel.innerHTML = '<div class="entry"><strong>' + (signal.underlying || "UNAVAILABLE") + ' ' + (signal.signal_type || "UNAVAILABLE") + '</strong><div>Direction: ' + (signal.direction || "UNAVAILABLE") + '</div><div>Signal time: ' + (signal.timestamp || "UNAVAILABLE") + '</div><div>State: ' + (signal.status || "UNAVAILABLE") + '</div><div>Entry filter: <span class="info">' + (signal.entry_filter || "UNAVAILABLE") + '</span></div>' + stochastic + conditions + '</div>';
      document.getElementById("signalState").textContent = signal.status || "UNAVAILABLE";
    }
    function renderApprovalPanel(state) {
      const panel = document.getElementById("approvalPanel");
      const signal = state.signal;
      if (!signal) {
        panel.innerHTML = '<div class="entry"><strong>UNAVAILABLE</strong><div>NO ENTRY STATE SUPPLIED</div></div>';
        document.getElementById("approvalState").textContent = "UNAVAILABLE";
        return;
      }
      panel.innerHTML = '<div class="entry"><strong>' + (signal.underlying || "UNAVAILABLE") + ' ' + (signal.signal_type || "UNAVAILABLE") + '</strong><div>CALL / PUT: ' + (signal.direction || "UNAVAILABLE") + '</div><div>ENTRY: ' + (signal.status || "UNAVAILABLE") + '</div><div>Signal time: ' + (signal.timestamp || "UNAVAILABLE") + '</div></div>';
      document.getElementById("approvalState").textContent = signal.status || "UNAVAILABLE";
    }
    function renderOptionPanel(state) {
      const panel = document.getElementById("optionPanel");
      const signal = state.signal;
      const universe = Object.values(state.option_universe || {});
      const rows = universe.slice(0, 40).map((item) => { const quote = state.option_quotes?.[item.instrument_key]; return '<div class="entry"><strong>' + (item.strike ?? "UNAVAILABLE") + ' ' + (item.option_type || "UNAVAILABLE") + '</strong><div>' + (item.symbol || item.instrument_key || "UNAVAILABLE") + ' · LTP ' + fmtNumber(quote && quote.ltp) + ' · Status ' + (item.status || "UNAVAILABLE") + '</div></div>'; }).join('');
      const selected = signal && signal.option ? '<div class="entry"><strong>ATM OPTION EXECUTION</strong><div>' + (signal.option || "UNAVAILABLE") + ' · ' + (signal.direction || "UNAVAILABLE") + '</div></div>' : '';
      panel.innerHTML = selected + (rows || '<div class="entry"><strong>ATM OPTION EXECUTION</strong><div>UNAVAILABLE: NO AUTHORITATIVE OPTION EXECUTION DATA</div></div>');
    }
    function renderPositions(state) {
      const panel = document.getElementById("positionsPanel");
      const items = state.position_details && state.position_details.length ? state.position_details : [];
      panel.innerHTML = items.length ? items.map((item) => { const exit = item.strategy_exit || {}; return '<div class="entry"><strong>' + (item.trade_id || "UNAVAILABLE") + ' | ' + (item.index || "UNAVAILABLE") + ' ' + (item.signal_type || "UNAVAILABLE") + ' ' + (item.direction || "UNAVAILABLE") + '</strong><div>' + (item.option || "UNAVAILABLE") + ' · Strike ' + (item.strike ?? "UNAVAILABLE") + ' · Qty ' + (item.quantity ?? "UNAVAILABLE") + '</div><div>Entry ' + fmtNumber(item.entry_price) + ' · LTP ' + fmtNumber(item.current_ltp) + ' · P&L ' + fmtNumber(item.pnl) + '</div><div>State: ' + (item.position_state || "UNAVAILABLE") + ' · Entry filter: ' + (item.entry_filter || "UNAVAILABLE") + '</div><div>CCI: ' + (item.cci_exit_state || exit.cci_state || "UNAVAILABLE") + ' · Stoch: ' + (exit.stochastic_state || "UNAVAILABLE") + ' · Prev ' + fmtNumber(exit.previous_stochastic, 2) + ' · Extreme ' + fmtNumber(exit.stochastic_extreme, 2) + '</div><div>Exit: ' + (item.exit_reason || "UNAVAILABLE") + '</div></div>'; }).join("") : '<div class="entry">UNAVAILABLE: NO POSITION DATA SUPPLIED</div>';
      document.getElementById("positionsState").textContent = items.length && items[0].position_state ? items[0].position_state : "UNAVAILABLE";
    }
    function renderOrders(state) {
      const panel = document.getElementById("ordersPanel");
      const items = state.orders && state.orders.length ? state.orders : [];
      panel.innerHTML = items.length ? items.map((item) => '<div class="entry"><strong>' + (item.order_id || "UNAVAILABLE") + '</strong><div>' + (item.instrument || "UNAVAILABLE") + ' · ' + (item.side || "UNAVAILABLE") + ' · Qty ' + (item.quantity ?? "UNAVAILABLE") + '</div><div>Status: ' + (item.status || "UNAVAILABLE") + ' · Broker: ' + (item.broker_status || "UNAVAILABLE") + '</div></div>').join("") : '<div class="entry">UNAVAILABLE: NO STRUCTURED ORDER DATA SUPPLIED</div>';
      document.getElementById("ordersState").textContent = items.length ? "AVAILABLE" : "UNAVAILABLE";
    }
    function renderClosedTrades(state) {
      const items = (state.position_details || []).filter(item => String(item.position_state || '').toUpperCase() === 'CLOSED');
      document.getElementById("closedTradesPanel").innerHTML = items.length ? items.slice(-12).reverse().map(item => '<div class="event-line"><strong>' + (item.index || 'UNAVAILABLE') + ' · ' + (item.direction || 'UNAVAILABLE') + ' · ' + (item.option || 'UNAVAILABLE') + '</strong><div>Entry ' + fmtNumber(item.entry_price) + ' · Exit ' + fmtNumber(item.exit_price) + ' · Qty ' + (item.quantity ?? 'UNAVAILABLE') + '</div><div>' + (item.exit_reason || 'UNAVAILABLE') + ' · Realized P&L ' + fmtNumber(item.realized_pnl) + '</div></div>').join('') : '<div class="event-line dim">NO CLOSED TRADE DATA SUPPLIED</div>';
    }
    function renderFills(state) {
      const items = state.fills || [];
      document.getElementById("fillsPanel").innerHTML = items.length ? items.map((item) => '<div class="entry"><strong>' + (item.fill_id || "UNAVAILABLE") + '</strong><div>Order: ' + (item.order_id || "UNAVAILABLE") + ' · ' + (item.instrument || "UNAVAILABLE") + '</div><div>Qty: ' + (item.quantity ?? "UNAVAILABLE") + ' · Price: ' + fmtNumber(item.average_price) + ' · ' + (item.status || "UNAVAILABLE") + '</div></div>').join("") : '<div class="entry">NO STRUCTURED FILL DATA AVAILABLE</div>';
      document.getElementById("fillsState").textContent = items.length ? "AVAILABLE" : "UNAVAILABLE";
    }
    function renderExits(state) {
      const items = state.exits || [];
      document.getElementById("exitsPanel").innerHTML = items.length ? items.map((item) => '<div class="entry"><strong>' + (item.trade_id || "UNAVAILABLE") + '</strong><div>Reason: ' + (item.exit_reason || "UNAVAILABLE") + '</div><div>Price: ' + fmtNumber(item.exit_price) + ' · Status: ' + (item.status || "UNAVAILABLE") + '</div></div>').join("") : '<div class="entry">UNAVAILABLE: NO STRUCTURED EXIT DATA SUPPLIED</div>';
      document.getElementById("exitsState").textContent = items.length ? "AVAILABLE" : "UNAVAILABLE";
    }
    function renderIncidents(state) {
      const items = state.incidents || [];
      document.getElementById("incidentsPanel").innerHTML = items.length ? items.map((item) => '<div class="event-line"><strong>' + (item.severity || "UNAVAILABLE") + ' · ' + (item.component || "UNAVAILABLE") + '</strong><div>' + (item.message || "UNAVAILABLE") + '</div><div class="dim">' + (item.timestamp || "UNAVAILABLE") + '</div></div>').join("") : '<div class="event-line">UNAVAILABLE: NO STRUCTURED INCIDENT DATA SUPPLIED</div>';
      document.getElementById("incidentsState").textContent = items.length ? "AVAILABLE" : "UNAVAILABLE";
    }
    function renderReport(state) {
      const report = state.report_summary;
      const panel = document.getElementById("reportPanel");
      if (!report || !report.status) {
        panel.innerHTML = '<div class="entry">UNAVAILABLE: NO AUTHORITATIVE REPORT SUPPLIED</div>';
        document.getElementById("reportState").textContent = "UNAVAILABLE";
        return;
      }
      panel.innerHTML = '<div class="entry"><strong>' + (report.report_date || "UNAVAILABLE") + '</strong><div>Status: ' + report.status + '</div><div>Events: ' + (report.total_events ?? "UNAVAILABLE") + ' · Orders: ' + (report.order_events ?? "UNAVAILABLE") + '</div></div>';
      document.getElementById("reportState").textContent = report.status;
    }
    function renderEvents(state) {
      const events = (state.events || []).slice(-8).reverse();
      document.getElementById("eventsPanel").innerHTML = events.length ? events.map((item) => '<div class="event-line">' + item + '</div>').join("") : '<div class="event-line dim">No events yet.</div>';
    }
    function renderSignalHistory(state) {
      const items = (state.signal_history || []).slice(-12).reverse();
      document.getElementById("signalHistoryPanel").innerHTML = items.length ? items.map((item) => '<div class="event-line"><strong>' + (item.timestamp || item.created_at || '--') + ' | ' + (item.underlying || '--') + ' | ' + (item.signal_type || 'TYPE_1') + ' | ' + (item.direction || '--') + '</strong><div class="dim">RSI ' + (item.rsi_filter_status || '--') + ' · ' + (item.status || '--') + ' · ' + (item.option || '--') + '</div></div>').join('') : '<div class="event-line dim">No signals yet.</div>';
    }
    function renderCandleChart(state) {
      const canvas = document.getElementById("candleChart");
      if (!canvas) return;
      const context = canvas.getContext("2d");
      const width = canvas.clientWidth || 640;
      const height = 220;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = width * ratio;
      canvas.height = height * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      const name = indexNames[0];
      const candles = [state.prev2?.[name], state.previous?.[name], state.candles?.[name]].filter(item => item && Number.isFinite(Number(item.open)));
      if (!candles.length) {
        context.fillStyle = "#8ba6aa";
        context.font = "12px Aptos, sans-serif";
        context.fillText("UNAVAILABLE: NO BACKEND CANDLE DATA", 16, 30);
        return;
      }
      const values = candles.flatMap(item => [Number(item.high), Number(item.low)]);
      const high = Math.max(...values), low = Math.min(...values), range = high - low || 1;
      const y = value => 18 + (high - value) / range * (height - 48);
      context.strokeStyle = "rgba(139,166,170,.22)";
      context.beginPath(); context.moveTo(16, height - 28); context.lineTo(width - 16, height - 28); context.stroke();
      candles.forEach((item, index) => {
        const x = 54 + index * ((width - 108) / Math.max(1, candles.length - 1));
        const open = y(Number(item.open)), close = y(Number(item.close));
        const top = Math.min(open, close), body = Math.max(4, Math.abs(close - open));
        const bullish = Number(item.close) >= Number(item.open);
        context.strokeStyle = bullish ? "#57dda3" : "#ff7182";
        context.fillStyle = context.strokeStyle;
        context.beginPath(); context.moveTo(x, y(Number(item.high))); context.lineTo(x, y(Number(item.low))); context.stroke();
        context.fillRect(x - 12, top, 24, body);
        context.fillStyle = "#8ba6aa";
        context.font = "11px Aptos, sans-serif";
        context.textAlign = "center";
        context.fillText(item.is_final === false ? "RUNNING" : "5M", x, height - 10);
      });
      context.textAlign = "left";
      context.fillStyle = "#8ba6aa";
      context.fillText(name + " | OHLC backend candles | SMA overlays: UNAVAILABLE", 16, 14);
    }
    let lastEvent = "";
    let noticeTimer = null;
    function notify(message) {
      if (!message || message === lastEvent) return;
      lastEvent = message;
      const notice = document.getElementById("notice");
      notice.textContent = message;
      notice.classList.add("visible");
      clearTimeout(noticeTimer);
      noticeTimer = setTimeout(() => notice.classList.remove("visible"), 5000);
      document.title = "RKL | " + message.slice(0, 48);
      if (document.visibilityState === "hidden" && "Notification" in window && Notification.permission === "granted") new Notification("RKL Algo Trading", { body: message });
    }
    function render(state) {
      if (Array.isArray(state.instrument_names) && state.instrument_names.length) {
        indexNames.splice(0, indexNames.length, ...state.instrument_names);
      }
      renderHeader(state);
      renderMarketStatus(state);
      renderPipeline(state);
      renderMarketGrid(state);
      renderCandleChart(state);
      renderQuality(state);
      renderIndicators(state);
      renderSignalPanel(state);
      renderSignalHistory(state);
      renderApprovalPanel(state);
      renderOptionPanel(state);
      renderPositions(state);
      renderClosedTrades(state);
      renderOrders(state);
      renderFills(state);
      renderExits(state);
      renderIncidents(state);
      renderReport(state);
      renderEvents(state);
      notify(state.last_event);
    }
    function canonicalView(payload) {
      const health = payload.SystemHealth || {};
      const marketStatus = payload.MarketStatus || {};
      const indexState = payload.IndexState || {};
      const candles = payload.CandleState || {};
      const indicators = payload.IndicatorState || {};
      const names = Object.keys(indexState);
      const latest = {};
      const previous = {};
      const prev2 = {};
      const healthByIndex = {};
      const sync = {};
      names.forEach((name) => {
        const index = indexState[name] || {};
        const current = candles[name] || index.current_candle || {};
        latest[name] = {
          ltp: index.ltp,
          timestamp: index.timestamp,
          exchange_timestamp: index.exchange_timestamp,
          received_timestamp: index.received_timestamp,
          source: index.source
        };
        previous[name] = index.previous_candle || {};
        prev2[name] = index.previous_previous_candle || {};
        candles[name] = current;
        healthByIndex[name] = index.health;
        sync[name] = index.sync || {};
      });
      const signal = payload.SignalState || {};
      const hasSignal = Object.values(signal).some((value) => value !== null && value !== undefined);
      return {
        instrument_names: names,
        market_status: marketStatus.market_state || "UNAVAILABLE",
        latest,
        candles,
        previous,
        prev2,
        health: healthByIndex,
        sync,
        indicators: Object.fromEntries(names.map((name) => {
          const item = indicators[name] || {};
          return [name, [item.cci5, item.rsi14]];
        })),
        indicator_details: indicators,
        stochastic14: Object.fromEntries(names.map((name) => [name, (indicators[name] || {}).stochastic14])),
        indicator_reason: Object.fromEntries(names.map((name) => [name, (indicators[name] || {}).reason || "UNAVAILABLE"])),
        signal: hasSignal ? signal : null,
        signal_history: payload.SignalHistory || [],
        signal_queue: payload.SignalQueue || [],
        option_universe: Object.fromEntries((payload.OptionUniverse || []).map((item, index) => [item.instrument_key || String(index), item])),
        option_quotes: {},
        position_details: payload.PositionState || [],
        positions: payload.PositionState || [],
        orders: payload.OrderState || [],
        fills: payload.FillState || [],
        exits: payload.ExitState || [],
        incidents: payload.IncidentState || [],
        report_summary: payload.ReportSummary || null,
        events: payload.IncidentState || [],
        components: health.components || {},
        system_status: health.status || "UNAVAILABLE",
        ws_status: health.ws_status || "UNAVAILABLE",
        startup_phase: health.startup_phase || "UNAVAILABLE",
        last_event: health.last_event,
        reconnects: health.reconnects,
        pipeline_state: {},
      };
    }
    let observerSocket = null;
    let observerReconnectTimer = null;
    let observerSequence = null;
    let observerState = "CONNECTING";
    function setObserverState(value) {
      observerState = value;
      document.getElementById("connectionDot").className = value === "CONNECTED" ? "dot" : "dot off";
      document.getElementById("connectionText").textContent = value;
    }
    async function refreshState() {
      try {
        const response = await fetch("/api/v1/observer/snapshot");
        if (!response.ok) return;
        const envelope = await response.json();
        if (envelope.protocol !== "rkl.observer.v1" || !envelope.payload) throw new Error("Invalid observer envelope");
        render(canonicalView(envelope.payload));
        return envelope;
      } catch (error) {
        document.getElementById("marketStatus").textContent = "DISCONNECTED";
        setObserverState("DISCONNECTED");
      }
    }
    async function resyncObserver() {
      setObserverState("STALE/RESYNCING");
      try {
        const response = await fetch("/api/v1/observer/snapshot");
        if (!response.ok) throw new Error("Observer resync HTTP " + response.status);
        const envelope = await response.json();
        if (envelope.protocol !== "rkl.observer.v1" || !envelope.payload) throw new Error("Invalid observer envelope");
        observerSequence = null;
        render(canonicalView(envelope.payload));
        setObserverState("CONNECTED");
      } catch (error) {
        setObserverState("DISCONNECTED");
      }
    }
    function observerSocketUrl() {
      const url = new URL(window.location.href);
      const port = Number(url.port || (url.protocol === "https:" ? 443 : 80));
      url.port = String(port + 1);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = "/api/v1/observer/stream";
      url.search = "";
      return url.toString();
    }
    function connectObserver() {
      if (observerReconnectTimer) {
        clearTimeout(observerReconnectTimer);
        observerReconnectTimer = null;
      }
      setObserverState("CONNECTING");
      try {
        observerSocket = new WebSocket(observerSocketUrl());
        observerSocket.onopen = () => setObserverState("CONNECTED");
        observerSocket.onmessage = async (event) => {
          try {
            const envelope = JSON.parse(event.data);
            if (envelope.event_type === "WELCOME") return;
            if (envelope.event_type === "HEARTBEAT") return;
            if (envelope.event_type === "RESYNC_REQUIRED") {
              await resyncObserver();
              return;
            }
            const sequence = envelope.sequence;
            if (observerSequence !== null && sequence !== observerSequence + 1) {
              await resyncObserver();
              return;
            }
            observerSequence = sequence;
            if (envelope.event_type === "STATE_SNAPSHOT" && envelope.payload) {
              render(canonicalView(envelope.payload));
            }
          } catch (error) {
            setObserverState("STALE/RESYNCING");
          }
        };
        observerSocket.onclose = () => {
          setObserverState("DISCONNECTED");
          observerReconnectTimer = setTimeout(connectObserver, 8000);
        };
        observerSocket.onerror = () => setObserverState("DISCONNECTED");
      } catch (error) {
        setObserverState("DISCONNECTED");
        observerReconnectTimer = setTimeout(connectObserver, 8000);
      }
    }
    function applyTheme(theme) {
      document.documentElement.dataset.theme = theme;
      localStorage.setItem("rkl-theme", theme);
      document.getElementById("themeSelect").value = theme;
    }
    document.addEventListener("DOMContentLoaded", () => {
      applyTheme(localStorage.getItem("rkl-theme") || "obsidian");
      document.getElementById("themeSelect").addEventListener("change", (event) => applyTheme(event.target.value));
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
      refreshState();
      connectObserver();
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
    def __init__(self, state, host="127.0.0.1", port=8765, *, mobile_token="", store=None,
                 mobile_ws_host="127.0.0.1", mobile_ws_port=None):
        self.state = state
        self.host = host
        self.port = port
        self.mobile_token = mobile_token
        self.store = store
        self.mobile_ws_host = mobile_ws_host
        self.mobile_ws_port = mobile_ws_port or port + 1
        self.server = None
        self.thread = None
        self.mobile_ws_server = None
        self.mobile_ws_thread = None
        self.mobile_ws_loop = None
        self.mobile_ws_stop = None
        self.mobile_ws_async_stop = None
        self._stop = threading.Event()
        self.browser_opened = False
        self.url = f"http://{self.host}:{self.port}/"

    def _mobile_payload(self, path, query=None):
        snapshot = self.state.snapshot()
        query = query or {}
        if path in {"/api/mobile/status", "/api/v1/mobile/status"}:
          return {key: snapshot.get(key) for key in (
            "components", "system_status", "ws_status", "startup_phase", "market_status",
            "execution_mode", "preflight", "last_event", "reconnects",
          )} | {
            "server_time": datetime.now().astimezone().isoformat(),
            "system_health": snapshot.get("system_health", {}),
            "pipeline_state": snapshot.get("pipeline_state", {}),
          }
        if path in {"/api/mobile/market", "/api/mobile/indices", "/api/v1/mobile/market"}:
          return {key: snapshot.get(key) for key in (
            "instrument_names", "latest", "candles", "previous", "prev2", "health", "sync",
            "market_status",
          )}
        for prefix in ("/api/mobile/indices/", "/api/v1/mobile/indices/"):
            if path.startswith(prefix):
                index = path[len(prefix):].upper()
                return {"index": index, "market": {
                    key: (snapshot.get(key) or {}).get(index)
                    for key in ("latest", "candles", "previous", "prev2", "health", "sync", "indicators")
                }}
        for prefix in ("/api/mobile/options/", "/api/v1/mobile/options/"):
            if path.startswith(prefix):
                index = path[len(prefix):].upper()
                return {"index": index, "option_universe": {
                    token: value for token, value in (snapshot.get("option_universe") or {}).items()
                    if value.get("underlying", "").upper() == index
                }, "option_quotes": snapshot.get("option_quotes", {}), "signal": snapshot.get("signal")}
        if path in {"/api/mobile/options", "/api/v1/mobile/options"}:
          return {key: snapshot.get(key) for key in ("option_universe", "option_quotes", "signal")}
        if path in {"/api/mobile/signals", "/api/v1/mobile/signals"}:
          return {key: snapshot.get(key) for key in ("signal", "signal_history", "signal_queue")}
        for prefix in ("/api/mobile/signals/", "/api/v1/mobile/signals/"):
            if path.startswith(prefix):
                signal_id = path[len(prefix):]
                signals = [item for item in snapshot.get("signal_history", []) if item.get("signal_id") == signal_id]
                if snapshot.get("signal", {}).get("signal_id") == signal_id:
                    signals.insert(0, snapshot["signal"])
                return {"signal_id": signal_id, "signal": signals[0] if signals else None}
        if path in {"/api/mobile/orders", "/api/v1/mobile/orders"}:
          return {"orders": snapshot.get("orders", [])}
        for prefix in ("/api/mobile/orders/", "/api/v1/mobile/orders/"):
            if path.startswith(prefix):
                order_id = path[len(prefix):]
                order = next((item for item in snapshot.get("orders", [])
                              if isinstance(item, dict) and str(item.get("order_id")) == order_id), None)
                return {"order_id": order_id, "order": order}
        if path in {"/api/mobile/positions", "/api/v1/mobile/positions"}:
          return {"positions": snapshot.get("positions", []), "position_details": snapshot.get("position_details", [])}
        for prefix in ("/api/mobile/positions/", "/api/v1/mobile/positions/"):
            if path.startswith(prefix):
                trade_id = path[len(prefix):]
                position = next((item for item in snapshot.get("position_details", [])
                                 if str(item.get("trade_id")) == trade_id), None)
                return {"trade_id": trade_id, "position": position}
        if path in {"/api/mobile/notifications", "/api/v1/mobile/notifications"}:
          return {"events": snapshot.get("events", []), "severity": query.get("severity", [None])[0],
                  "category": query.get("category", [None])[0]}
        if path in {"/api/mobile/reports", "/api/v1/mobile/reports"}:
          return {"reports": self.store.daily_reports() if self.store and hasattr(self.store, "daily_reports") else []}
        for prefix in ("/api/mobile/reports/", "/api/v1/mobile/reports/"):
            if path.startswith(prefix):
                report_date = path[len(prefix):]
                reports = self.store.daily_reports() if self.store and hasattr(self.store, "daily_reports") else []
                return {"report_date": report_date, "report": next((item for item in reports if item.get("report_date") == report_date), None)}
        if path in {"/api/mobile/sandbox", "/api/v1/mobile/sandbox"}:
          return {"execution_mode": snapshot.get("execution_mode"), "available": False, "status": "NO_SANDBOX_DATA", "results": []}
        return None

    def _mobile_authorized(self, headers):
        supplied = headers.get("Authorization", "")
        return bool(self.mobile_token) and hmac.compare_digest(supplied, f"Bearer {self.mobile_token}")

    def _observer_authorized(self, headers, client_host=None):
      if (client_host in {"127.0.0.1", "::1", "localhost"} or client_host is None) and self.host in {"127.0.0.1", "localhost", "::1"}:
        return True
      if self.mobile_token:
        supplied = headers.get("Authorization", "")
        if hmac.compare_digest(supplied, f"Bearer {self.mobile_token}"):
          return True
        return False
      return False

    def _observer_payload(self):
      snapshot = self.state.snapshot()
      if self.store and hasattr(self.store, "recent_records"):
        for source, target in (("orders", "orders"), ("fills", "fills"), ("exits", "exits")):
          try:
            snapshot[target] = self.store.recent_records(source)
          except Exception:
            snapshot[target] = []
      return build_observer_payload(snapshot)

    @staticmethod
    def _observer_server_time():
      return datetime.now().astimezone().isoformat()

    def _observer_envelope(self, payload, sequence, event_type, *, stale=None, stale_reason=None):
      return build_observer_envelope(
        payload=payload,
        sequence=sequence,
        event_type=event_type,
        server_time=self._observer_server_time(),
        source_timestamp=None,
        stale=stale,
        stale_reason=stale_reason,
        state_version=None,
      )

    async def _observer_ws_handler(self, websocket, path=None):
      request = getattr(websocket, "request", None)
      request_path = path or getattr(websocket, "path", "") or getattr(request, "path", "")
      parsed = urlsplit(request_path)
      headers = getattr(websocket, "request_headers", None) or getattr(request, "headers", {})
      if parsed.path != "/api/v1/observer/stream" or not self._observer_authorized(headers):
        await websocket.close(code=1008, reason="Authentication required")
        return
      sequence = 0
      previous = None
      last_heartbeat = time.monotonic()
      await websocket.send(json.dumps(self._observer_envelope(
        {"resync_required": False}, sequence, "WELCOME", stale=False,
      )))
      while not self._stop.is_set():
        payload = self._observer_payload()
        serialized = json.dumps(payload, default=_json_value, sort_keys=True)
        if serialized != previous:
          sequence += 1
          await websocket.send(json.dumps(self._observer_envelope(
            payload, sequence, "STATE_SNAPSHOT", stale=None,
          ), default=_json_value))
          previous = serialized
          last_heartbeat = time.monotonic()
        elif time.monotonic() - last_heartbeat >= 10:
          sequence += 1
          await websocket.send(json.dumps(self._observer_envelope(
            {}, sequence, "HEARTBEAT", stale=None,
          )))
          last_heartbeat = time.monotonic()
        await asyncio.sleep(1)

    async def _mobile_ws_handler(self, websocket, path=None):
        request = getattr(websocket, "request", None)
        request_path = path or getattr(websocket, "path", "") or getattr(request, "path", "")
        parsed = urlsplit(request_path)
        headers = getattr(websocket, "request_headers", None) or getattr(request, "headers", {})
        if parsed.path == "/api/v1/observer/stream":
          await self._observer_ws_handler(websocket, request_path)
          return
        if parsed.path != "/api/v1/mobile/stream" or not self._mobile_authorized(headers):
            await websocket.close(code=1008, reason="Authentication required")
            return
        sequence = 0
        previous = None
        last_heartbeat = time.monotonic()
        await websocket.send(json.dumps({
            "protocol": "rkl.mobile.v1", "sequence": sequence, "event_id": "welcome",
            "event_type": "WELCOME", "server_time": datetime.now().astimezone().isoformat(),
            "source_timestamp": None, "payload": {"resync_required": False},
        }))
        while not self._stop.is_set():
            serialized = json.dumps(self.state.snapshot(), default=_json_value, sort_keys=True)
            if serialized != previous:
                sequence += 1
                await websocket.send(json.dumps({
                    "protocol": "rkl.mobile.v1", "sequence": sequence,
                    "event_id": f"snapshot-{sequence}",
                    "event_type": "STATE_SNAPSHOT" if sequence == 1 else "STATE_DELTA",
                    "server_time": datetime.now().astimezone().isoformat(),
                    "source_timestamp": None, "payload": json.loads(serialized),
                }))
                previous = serialized
                last_heartbeat = time.monotonic()
            elif time.monotonic() - last_heartbeat >= 10:
                sequence += 1
                await websocket.send(json.dumps({
                  "protocol": "rkl.mobile.v1", "sequence": sequence,
                  "event_id": f"heartbeat-{sequence}", "event_type": "HEARTBEAT",
                  "server_time": datetime.now().astimezone().isoformat(),
                  "source_timestamp": None, "payload": {"stale": False},
                }))
                last_heartbeat = time.monotonic()
            await asyncio.sleep(1)

    def _start_mobile_ws(self):
        if not self.mobile_token or websockets is None:
            return
        self.mobile_ws_stop = threading.Event()
        self.mobile_ws_loop = asyncio.new_event_loop()
        self.mobile_ws_async_stop = asyncio.Event()

        def runner():
            asyncio.set_event_loop(self.mobile_ws_loop)

            async def serve():
                self.mobile_ws_server = await websockets.serve(
                    self._mobile_ws_handler, self.mobile_ws_host, self.mobile_ws_port,
                    max_size=2 * 1024 * 1024,
                )
                await self.mobile_ws_async_stop.wait()
                self.mobile_ws_server.close()
                await self.mobile_ws_server.wait_closed()

            try:
                self.mobile_ws_loop.run_until_complete(serve())
            except OSError as error:  # Mobile transport must not stop the trading engine.
                print(f"[MOBILE WS] DISABLED: {error}", flush=True)
            finally:
                self.mobile_ws_loop.close()

        self.mobile_ws_thread = threading.Thread(target=runner, name="mobile-websocket", daemon=True)
        self.mobile_ws_thread.start()

    def start(self, open_browser=True):
        state = self.state
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def do_GET(self):
                parsed_path = urlsplit(self.path)
                mobile_path = parsed_path.path
                if mobile_path in {"/api/observer/snapshot", "/api/v1/observer/snapshot"}:
                  if not owner._observer_authorized(self.headers, self.client_address[0]):
                    self.send_error(401, "Authentication required")
                    return
                  payload = json.dumps(owner._observer_envelope(
                    owner._observer_payload(), 0, "STATE_SNAPSHOT", stale=None,
                  ), default=_json_value).encode("utf-8")
                  self.send_response(200)
                  self.send_header("Content-Type", "application/json")
                  self.send_header("Cache-Control", "no-store")
                  self.send_header("Content-Length", str(len(payload)))
                  self.end_headers()
                  self.wfile.write(payload)
                  return
                if mobile_path.startswith("/api/mobile/") or mobile_path.startswith("/api/v1/mobile/"):
                    if not owner.mobile_token:
                        self.send_error(404, "Mobile API is not configured")
                        return
                    if not owner._mobile_authorized(self.headers):
                        self.send_error(401, "Authentication required")
                        return
                    mobile_payload = owner._mobile_payload(mobile_path, parse_qs(parsed_path.query))
                    if mobile_payload is None:
                        self.send_error(404)
                        return
                    payload = json.dumps(mobile_payload, default=_json_value).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/health":
                    snapshot = state.snapshot()
                    components = snapshot.get("components", {})
                    ready = all(components.get(name) == "READY" for name in ("AUTH", "DATABASE", "HISTORY"))
                    latest = list(snapshot.get("latest", {}).values())
                    previous = list(snapshot.get("previous", {}).values())
                    last_tick = max((item.timestamp for item in latest if hasattr(item, "timestamp")), default=None)
                    last_candle = max((item.timestamp for item in previous if hasattr(item, "timestamp")), default=None)
                    payload = json.dumps({
                        "status": "ok" if ready else "degraded",
                      "service": "running",
                        "ready": ready,
                      "market": snapshot.get("market_status", "unknown").lower(),
                      "websocket": snapshot.get("ws_status", "unknown"),
                      "timestamp": datetime.now().isoformat(),
                      "last_valid_tick": last_tick,
                      "last_finalized_candle": last_candle,
                        "components": components,
                      "feed": snapshot.get("ws_status", "UNKNOWN"),
                    }, default=_json_value).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                if self.path == "/ready":
                    snapshot = state.snapshot()
                    components = snapshot.get("components", {})
                    required = ("AUTH", "DATABASE", "HISTORY", "BROKER", "PREFLIGHT")
                    ready = all(components.get(name) == "READY" for name in required)
                    if snapshot.get("system_status") in {"TRADING_HALTED", "EMERGENCY", "SHUTTING_DOWN"}:
                      ready = False
                    payload = json.dumps({
                        "status": "ok" if ready else "degraded",
                        "components": components,
                        "feed": snapshot.get("ws_status", "UNKNOWN"),
                        "mode": snapshot.get("execution_mode", "UNKNOWN"),
                        "preflight": snapshot.get("preflight", {}),
                    }, default=_json_value).encode("utf-8")
                    self.send_response(200 if ready else 503)
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
        self._start_mobile_ws()
        self._wait_for_health(timeout=10)
        self._wait_for_root(timeout=10)
        if open_browser:
          self.browser_opened = self._open_browser()
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

    def _wait_for_root(self, timeout=10):
        try:
            with urllib.request.urlopen(self.url, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"Dashboard root returned HTTP {response.status}")
        except Exception as error:
            raise RuntimeError(f"Dashboard root check failed at {self.url}: {error}") from error

    def _open_browser(self):
        if os.environ.get("DISPLAY") is None and os.name != "nt":
            return False
        try:
            opened = webbrowser.open(self.url)
            if not opened:
                print("[BROWSER] AUTO-OPEN FAILED — dashboard remains available at configured URL", flush=True)
            else:
                print("[BROWSER] OPENED", flush=True)
            return opened
        except Exception as error:  # pragma: no cover - browser launch is environment-dependent
            print(f"[BROWSER] AUTO-OPEN FAILED — {error}", flush=True)
            return False

    def stop(self):
        self._stop.set()
        if self.mobile_ws_loop and self.mobile_ws_async_stop:
            self.mobile_ws_loop.call_soon_threadsafe(self.mobile_ws_async_stop.set)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
