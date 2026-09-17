"""Event notifications and shared UI state for real market data."""

import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config

IST = ZoneInfo("Asia/Kolkata")


def safe_print(*values, sep=" ", end="\n", flush=False):
    text = sep.join(str(value) for value in values) + end
    try:
        print(text, end="", flush=flush)
    except UnicodeEncodeError:
        ascii_text = text.encode("ascii", "replace").decode("ascii")
        print(ascii_text, end="", flush=flush)


class TerminalDisplay:
    def __init__(self, instruments, window_size=6, live_updates=False):
        self.instruments = instruments
        self.window_size = window_size
        self.live_updates = live_updates
        self.latest = {}
        self.option_quotes = {}
        self.option_universe = {}
        self.candles = {}
        self.history = {}
        self.previous = {}
        self.prev2 = {}
        self.indicators = {}
        self.indicator_base = {}
        self.indicator_updated = {}
        self.indicator_reason = {}
        self.stochastic14 = {}
        self.last_candle_update = {}
        self.rest_status = {}
        self.health = {}
        self.status = "STARTING"
        self.ws_status = "DISCONNECTED"
        self.system_status = "STARTING"
        self.startup_phase = "STARTING"
        self.reconnects = 0
        self.components = {
            "AUTH": "WAITING", "DATABASE": "READY", "HISTORY": "WAITING", "DATA FEED": "WAITING",
            "AUTO ENTRY": "ENABLED" if config.effective_auto_entry_enabled() else "DISABLED",
            "EXECUTION MODE": "REAL" if config.order_execution_enabled() else "READ_ONLY",
            "PREFLIGHT": "WAITING",
            "CANDLES": "WAITING", "SIGNALS": "WAITING", "BROKER": "WAITING",
            "RISK": "READY", "ORDERS": "DISABLED", "EXTERNAL": "UNAVAILABLE",
        }
        self.signal = None
        self.signal_history = []
        self.signal_queue = []
        self.orders = []
        self.positions = []
        self.position_details = []
        self.sync = {}
        self.last_event = "Starting"
        self.events = []
        self.public_ip = "UNAVAILABLE"
        self.order_ip = "NOT CHECKED"
        self.preflight = {}
        self.storage = {}
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()

    def update_tick(self, tick, candle):
        with self.lock:
            self.latest[tick.instrument] = tick
            if candle:
                self.candles[tick.instrument] = candle
            self.last_event = f"Tick {tick.instrument}"

    def set_option_quote(self, token, tick):
        with self.lock:
            self.option_quotes[token] = tick

    def set_option_universe(self, contracts):
        with self.lock:
            self.option_universe = {contract.instrument_key: {
                "instrument_key": contract.instrument_key, "symbol": contract.tradingsymbol,
                "underlying": contract.underlying, "expiry": contract.expiry,
                "strike": contract.strike, "option_type": contract.option_type,
                "lot_size": contract.lotsize, "tick_size": contract.tick_size,
            } for contract in contracts}

    def set_status(self, status):
        with self.lock:
            self.system_status = status
            if "FEED" in status or "WEBSOCKET" in status:
                self.ws_status = status.replace("WEBSOCKET ", "")
            self.last_event = status
            if not status.startswith("Tick "):
                self.events.append(f"{datetime.now(IST):%H:%M:%S} {status}")
                self.events = self.events[-5:]
        if not status.startswith("Tick ") and self._is_important(status):
            self._print_event(status)

    def add_event(self, message):
        with self.lock:
            self.events.append(f"{datetime.now(IST):%H:%M:%S} {message}")
            self.events = self.events[-5:]
            self.last_event = message
        if self._is_important(message):
            self._print_event(message)

    @staticmethod
    def _print_event(message):
        text = f"{datetime.now(IST):%H:%M:%S} {message}"
        safe_print(text, flush=True)

    @staticmethod
    def _is_important(message):
        important = ("STARTUP", "AUTH", "DASHBOARD", "FEED", "WEBSOCKET", "HISTORY",
                     "CANDLE", "RECOVERY", "SIGNAL", "APPROV", "REJECT", "EXPIRED",
                     "ORDER", "FILLED", "SL ", "POSITION", "RISK", "EXIT", "ERROR",
                     "HALT", "SHUTDOWN")
        return any(token in str(message).upper() for token in important)
    def set_ws_status(self, status):
        with self.lock:
            self.ws_status = status

    @staticmethod
    def _end_time(candle):
        return (candle.timestamp.hour * 60 + candle.timestamp.minute + 5) % (24 * 60)

    @classmethod
    def _range_text(cls, candle):
        end = cls._end_time(candle)
        return f"{candle.timestamp:%H:%M} - {end // 60:02d}:{end % 60:02d}"

    def set_reconnects(self, count):
        with self.lock:
            self.reconnects = count

    def set_component(self, name, status):
        with self.lock:
            self.components[name] = status

    def set_startup_phase(self, phase):
        with self.lock:
            self.startup_phase = phase

    def set_signal(self, signal_data):
        with self.lock:
            self.signal = dict(signal_data)
            signal_id = self.signal.get("signal_id")
            if signal_id and not any(item.get("signal_id") == signal_id for item in self.signal_history):
                self.signal_history.append(dict(self.signal))
                self.signal_history = self.signal_history[-100:]
            self.last_event = "Signal received"

    def clear_signal(self, message="Signals waiting"):
        with self.lock:
            self.signal = None
            self.last_event = message

    def set_signal_queue(self, signals):
        with self.lock:
            self.signal_queue = list(signals)

    def set_positions(self, positions):
        with self.lock:
            self.positions = list(positions)

    def set_position_details(self, positions):
        with self.lock:
            self.position_details = [dict(position) for position in positions]

    def set_orders(self, orders):
        with self.lock:
            self.orders = list(orders)

    def set_sync(self, instrument, **values):
        with self.lock:
            self.sync[instrument] = dict(values)

    def set_network(self, public_ip, order_ip):
        with self.lock:
            self.public_ip = public_ip
            self.order_ip = order_ip

    def set_preflight(self, result):
        with self.lock:
            self.preflight = {
                "passed": result.passed,
                "checked_at": result.checked_at,
                "checks": dict(result.checks),
                "failures": list(result.failures),
                "reasons": dict(getattr(result, "reasons", {})),
                "summary": result.summary,
            }

    def set_storage_metrics(self, metrics):
        with self.lock:
            self.storage = dict(metrics)

    def set_previous(self, instrument, candle):
        with self.lock:
            self.previous[instrument] = candle
            self.last_candle_update[instrument] = datetime.now(IST)

    def set_candle_context(self, instrument, prev2, previous, running):
        with self.lock:
            if prev2 is not None:
                self.prev2[instrument] = prev2
            if previous is not None:
                self.previous[instrument] = previous
            if running is not None:
                self.candles[instrument] = running
            self.last_candle_update[instrument] = datetime.now(IST)

    def set_history(self, instrument, candles):
        with self.lock:
            self.history[instrument] = list(candles)[-self.window_size:]

    def set_indicators(self, instrument, cci_value, rsi_value, base_timestamp=None, reason=None):
        with self.lock:
            self.indicators[instrument] = (cci_value, rsi_value)
            self.indicator_base[instrument] = base_timestamp
            self.indicator_updated[instrument] = datetime.now(IST)
            self.indicator_reason[instrument] = reason or ("insufficient completed candles" if cci_value is None or rsi_value is None else "LIVE")

    def set_stochastic(self, instrument, value):
        with self.lock:
            self.stochastic14[instrument] = value

    def set_rest_status(self, instrument, status):
        with self.lock:
            self.rest_status[instrument] = status

    def set_health(self, instrument, status):
        with self.lock:
            self.health[instrument] = status

    def snapshot(self):
        with self.lock:
            now = datetime.now(IST)
            market_open = now.weekday() < 5 and config.MARKET_OPEN <= (now.hour, now.minute) < config.MARKET_CLOSE
            market_status = "OPEN" if market_open else "CLOSED"
            components = dict(self.components)
            if market_status == "CLOSED" and components.get("SIGNALS") == "READY":
                components["SIGNALS"] = "BLOCKED-CLOSED"

            pipeline_state = {
                "market_data": "READY" if self.latest else "UNAVAILABLE",
                "candle_engine": "HEALTHY" if self.candles else "UNAVAILABLE",
                "indicators": "READY" if self.indicators else "UNAVAILABLE",
                "strategy": "READY" if self.signal or self.signal_queue else "WAITING",
                "signal": "READY" if self.signal else "WAITING",
                "option": "ATM RESOLVED" if self.option_universe else "UNAVAILABLE",
                "order": "NOT ACTIVE" if not self.orders else "ACTIVE",
                "fill": "REPORTED" if self.orders else "UNAVAILABLE",
                "position": "OPEN" if self.position_details else "NONE",
                "exit": "MONITORING" if self.position_details else "IDLE",
                "broker_close": "READY" if components.get("BROKER") == "READY" else "WAITING",
                "reconciliation": "READY" if components.get("BROKER") == "READY" else "UNAVAILABLE",
            }

            return {
                "instrument_names": list(self.instruments),
                "latest": dict(self.latest), "candles": dict(self.candles),
                "option_quotes": dict(self.option_quotes),
                "option_universe": dict(self.option_universe),
                "prev2": dict(self.prev2), "previous": dict(self.previous), "indicators": dict(self.indicators),
                "stochastic14": dict(self.stochastic14),
                "indicator_base": dict(self.indicator_base), "indicator_updated": dict(self.indicator_updated),
                "indicator_reason": dict(self.indicator_reason), "last_candle_update": dict(self.last_candle_update),
                "rest_status": dict(self.rest_status), "health": dict(self.health),
                "system_status": self.system_status, "ws_status": self.ws_status,
                "reconnects": self.reconnects, "components": components,
                "startup_phase": self.startup_phase,
                "signal": dict(self.signal) if self.signal else None, "positions": list(self.positions),
                "signal_history": [dict(item) for item in self.signal_history],
                "position_details": [dict(item) for item in self.position_details],
                "signal_queue": list(self.signal_queue), "orders": list(self.orders),
                "events": list(self.events),
                "sync": {name: dict(values) for name, values in self.sync.items()},
                "last_event": self.last_event, "public_ip": self.public_ip, "order_ip": self.order_ip,
                "market_status": market_status,
                "execution_mode": config.EXECUTION_MODE,
                "preflight": dict(self.preflight),
                "storage": dict(self.storage),
                "pipeline_state": pipeline_state,
                "system_health": {
                    "server_time_utc": datetime.now(IST).isoformat(),
                    "execution_mode": config.EXECUTION_MODE,
                    "real_orders_enabled": config.ENABLE_REAL_ORDERS,
                    "market_open": market_status == "OPEN",
                    "feed_connected": self.ws_status.upper() in {"CONNECTED", "LIVE", "READY"},
                    "database_healthy": components.get("DATABASE") == "READY",
                    "history_sync": "SYNCED" if all(status == "SYNCED" for status in self.rest_status.values()) else "WAITING",
                    "preflight": "PASSED" if self.preflight.get("passed") else "FAILED",
                    "status": "HEALTHY" if components.get("DATABASE") == "READY" else "DEGRADED",
                },
            }

    def render_loop(self, stop_event, interval_seconds=None):
        """Legacy hook retained for compatibility; terminal output is event-driven."""
        return

    @staticmethod
    def restore_terminal():
        return

    def render(self):
        width = 78
        state = self.snapshot()
        latest = state["latest"]
        candles = state["candles"]
        previous = state["previous"]
        indicators = state["indicators"]
        indicator_base = state["indicator_base"]
        indicator_updated = state["indicator_updated"]
        indicator_reason = state.get("indicator_reason", self.indicator_reason)
        last_candle_update = state.get("last_candle_update", self.last_candle_update)
        rest_status = state["rest_status"]
        health = state["health"]
        system_status = state["system_status"]
        ws_status = state["ws_status"]
        reconnects = state["reconnects"]
        components = state["components"]
        signal_data = state["signal"]
        signal_queue = state["signal_queue"]
        positions = state["positions"]
        events = state["events"]
        sync = state["sync"]
        last_event = state["last_event"]
        public_ip = state["public_ip"]
        order_ip = state["order_ip"]
        now = datetime.now(IST)
        market_open = now.weekday() < 5 and (now.hour, now.minute) >= config.MARKET_OPEN and (now.hour, now.minute) < config.MARKET_CLOSE
        green = "\033[92m"
        yellow = "\033[93m"
        red = "\033[91m"
        cyan = "\033[96m"
        white = "\033[97m"
        reset = "\033[0m"
        market_label = f"{green}OPEN{reset}" if market_open else f"{yellow}CLOSED{reset}"
        lines = ["=" * width,
             f"{cyan}📊 RKL ALGO TRADING TERMINAL{reset}", "=" * width,
                 f"🟢 {market_label}  🕒 LOCAL {now:%H:%M:%S} IST  🏦 UPSTOX  🔄 LIVE TICKS",
             f"🔐 AUTH:{components['AUTH']}  📡 WS:{ws_status}  💾 DB:{components['DATABASE']}  📚 HIST:{components['HISTORY']}",
             f"{white}INDEX        LTP       CCI     RSI     FEED       AGE   REST{reset}",
             "-" * width]
        symbols = {"NIFTY": "🔷", "SENSEX": "🔶", "BANKNIFTY": "🏦", "MIDCPNIFTY": "📈"}
        for name in self.instruments:
            tick = latest.get(name)
            running = candles.get(name) if tick and health.get(name) == "LIVE" else None
            prior = previous.get(name)
            cci_value, rsi_value = indicators.get(name, (None, None))
            health_value = health.get(name, "WAITING")
            color = green if health_value == "LIVE" else yellow if health_value == "WAITING" else red
            ltp = f"{tick.ltp:>10,.2f}" if running else "       --"
            cci_text = f"{cci_value:>9.2f}" if cci_value is not None else "      --"
            rsi_text = f"{rsi_value:>9.2f}" if rsi_value is not None else "      --"
            rest_text = rest_status.get(name, "PENDING")
            age = (now - tick.timestamp.astimezone(IST)).total_seconds() if tick else None
            age_text = f"{age:>5.1f}s" if age is not None else "  --"
            if age is not None and age > config.STALE_DATA_SECONDS:
                health_value = "DATA_STALE"
            color = green if health_value == "LIVE" else yellow if health_value == "WAITING" else red
            feed_label = "🟢 LIVE" if health_value == "LIVE" else "🔴 STALE" if health_value == "DATA_STALE" else "🟡 WAIT"
            lines.append(f"{color}{symbols.get(name, '•')} {name:<10} {ltp} {cci_text} {rsi_text} "
                         f"{feed_label:<9} {age_text} {rest_text:<8}{reset}")
            lines.append(f"   🕯️ RUN {self._short_candle(running)}")
            lines.append(f"   🕯️ PREV {self._short_candle(prior)}")
            details = sync.get(name, {})
            lines.append(f"   📚 {details.get('status', '⚪ UNAVAILABLE')} HIST:{details.get('last_hist', '--')} "
                         f"LOCAL:{details.get('last_local', '--')} GAP:{details.get('gap', '--')} CHECK:{details.get('checked', '--')} "
                         f"{details.get('reason', '')[:18]}")
        lines.extend(["-" * width, "🎯 SIGNAL / TRADE SETUP"])
        if signal_data:
            lines.append(f"🚨 {signal_data.get('direction', '--')} {signal_data.get('underlying', '--')} "
                         f"LTP:{signal_data.get('ltp', '--')} BRK:{signal_data.get('breakout', '--')} "
                         f"OPT:{signal_data.get('option', 'resolving...')} {signal_data.get('status', '--')}")
            lines.append(f"   EXP:{signal_data.get('expiry', '--')} STRIKE:{signal_data.get('strike', '--')} "
                         f"OPT LTP:{signal_data.get('option_ltp', '--')} SL:{signal_data.get('sl', '--')} "
                         f"QTY:{signal_data.get('quantity', '--')} RISK:{signal_data.get('risk', '--')}")
            lines.append(f"   🕯️ OPTION PREV OHLC: {signal_data.get('option_ohlc', '--')}")
        else:
            lines.append("🎯 SIGNALS: WAITING")
        lines.append("💼 ACTIVE POSITIONS")
        if positions:
            for position in positions:
                lines.append(f"   {position}")
        else:
            lines.append("   No active positions")
        lines.extend(["-" * width,
                  f"📋 EVENTS: {' | '.join(events[-2:]) if events else 'none'}",
                  "-" * width,
                  "❤️ HEALTH " + " ".join(f"{name}:{components[name]}" for name in ("AUTH", "DATABASE", "HISTORY", "CANDLES")),
                      "          " + " ".join(f"{name}:{components[name]}" for name in ("SIGNALS", "BROKER", "RISK", "ORDERS")),
                      f"          EXTERNAL:{components['EXTERNAL']}",
                      f"📊 IND BASE:{max((value.strftime('%H:%M') for value in indicator_base.values() if value), default='--')} "
                      f"UPD:{max((value.strftime('%H:%M:%S') for value in indicator_updated.values() if value), default='--')} "
                      f"STATE:{'WAIT' if any(value != 'LIVE' for value in indicator_reason.values()) else 'LIVE'} "
                      f"REASON:{next((value for value in indicator_reason.values() if value != 'LIVE'), 'ready')[:12]}",
                      f"🕯️ LAST CANDLE UPDATE: {max((value.strftime('%H:%M:%S') for value in last_candle_update.values() if value), default='--')}",
                      f"⚙️ {system_status}  🔁 {reconnects}  🌐 PUBLIC IPV4:{public_ip} ORDER IP:{order_ip}",
                      f"📝 {last_event}",
                  f"🕘 EXCHANGE LAST: {max((tick.timestamp.isoformat() for tick in latest.values()), default='--')}",
                  "=" * width])
        output = "\n".join(lines)
        try:
            safe_print("\033[2J\033[H\033[?25l", end="")
            safe_print(output, flush=True)
        except UnicodeEncodeError:
            safe_print(output.encode("ascii", "replace").decode("ascii"), flush=True)

    def render_control(self):
        """Render the action-focused terminal; market detail belongs in the browser."""
        with self.render_lock:
            self._render_control()

    def _render_control(self):
        state = self.snapshot()
        now = datetime.now(IST)
        lines = [
            "=" * 112,
            "RKL ALGO TRADING CONTROL CENTER | MARKET, SIGNALS, ORDERS",
            f"MARKET:{state['market_status']}  STARTUP:{state.get('startup_phase', 'STARTING')}  "
            f"WS:{state['ws_status']}  AUTH:{state['components'].get('AUTH', '--')}  "
            f"HISTORY:{state['components'].get('HISTORY', '--')}",
            "-" * 112,
            "MARKET OHLC / LTP",
            "INDEX       LTP          PREVIOUS 5M OHLC                         RUNNING 5M OHLC",
        ]
        for name in self.instruments:
            tick = state["latest"].get(name)
            previous = state["previous"].get(name)
            running = state["candles"].get(name)
            ltp = f"{tick.ltp:>10,.2f}" if tick else "        --"
            previous_text = (f"O:{previous.open:.2f} H:{previous.high:.2f} L:{previous.low:.2f} C:{previous.close:.2f}"
                             if previous else "--")
            running_text = (f"O:{running.open:.2f} H:{running.high:.2f} L:{running.low:.2f} C:{running.close:.2f}"
                            if running else "--")
            lines.append(f"{name:<11} {ltp}   {previous_text:<45} {running_text}")
        lines.extend(["-" * 112, "SIGNALS"])
        signal_data = state.get("signal")
        if signal_data:
            lines.append(f"ACTIVE {signal_data.get('underlying', '--')} {signal_data.get('direction', '--')} "
                         f"LTP:{signal_data.get('ltp', '--')} STATUS:{signal_data.get('status', '--')} "
                         f"OPTION:{signal_data.get('option', '--')}")
        else:
            lines.append("NONE")
        for index, item in enumerate(state.get("signal_queue", [])[:4], 1):
            lines.append(f"QUEUE {index}: {item.get('underlying', '--')} {item.get('direction', '--')} {item.get('status', '--')}")
        lines.extend(["ORDERS"])
        orders = state.get("orders", [])
        positions = state.get("positions", [])
        lines.extend([f"{order}" for order in orders[-4:]] or ["NONE"])
        lines.extend(["POSITIONS", *positions[-4:]] if positions else ["POSITIONS", "NONE"])
        lines.append("CONTROLS: AUTOMATIC ENTRY  STRATEGY EXIT  BROWSER=DETAILS")
        output = "\n".join(lines)
        try:
            safe_print("\033[2J\033[H\033[?25l", end="")
            safe_print(output, flush=True)
        except UnicodeEncodeError:
            safe_print(output.encode("ascii", "replace").decode("ascii"), flush=True)

    def _render_control_legacy(self):
        width = 100
        state = self.snapshot()
        components = state["components"]
        signal_data = state["signal"]
        signal_queue = state["signal_queue"]
        positions = state["positions"]
        events = state["events"]
        now = datetime.now(IST)
        lines = ["=" * width, "🖥️  RKL ALGO TRADING CONTROL CENTER", "=" * width,
                 f"MARKET:{state['market_status']}  SYSTEM:{state['system_status']}  📡 WS:{state['ws_status']}  "
                 f"🔐 AUTH:{components['AUTH']}  💾 DB:{components['DATABASE']}",
                 f"📚 HIST:{components['HISTORY']}  🎯 SIGNALS:{components['SIGNALS']}  "
                f"💰 ORDERS:{components['ORDERS']}  MODE:{state['execution_mode']}  DASHBOARD:{components.get('DASHBOARD', '--')}",
                 "-" * width, "INDEX MARKET DATA"]
        for name in self.instruments:
            tick = state["latest"].get(name)
            running = state["candles"].get(name)
            previous = state["previous"].get(name)
            health = state["health"].get(name, "WAITING")
            if state["market_status"] == "CLOSED" and tick:
                health = "FROZEN-CLOSED"
            age = f"{(now - tick.timestamp.astimezone(IST)).total_seconds():.1f}s" if tick else "--"
            ltp = f"{tick.ltp:.2f}" if tick else "--"
            last_tick = tick.timestamp.astimezone(IST).strftime("%H:%M:%S") if tick else "--"
            prev_text = f"{previous.timestamp:%H:%M} O:{previous.open:.2f} H:{previous.high:.2f} L:{previous.low:.2f} C:{previous.close:.2f}" if previous else "--"
            run_text = f"{running.timestamp:%H:%M} O:{running.open:.2f} H:{running.high:.2f} L:{running.low:.2f} C:{running.close:.2f}" if running else "--"
            lines.extend([f"{name:<11} LTP:{ltp:>10} AGE:{age:>7} LAST:{last_tick} STATE:{health}",
                          f"  PREV 5M: {prev_text}", f"  RUN  5M: {run_text}"])
        lines.append("-" * width)
        lines.append("🎯 SIGNAL QUEUE")
        if signal_queue:
            for index, item in enumerate(signal_queue, 1):
                lines.append(f"   #{index} {item.get('priority', '--')} {item.get('underlying', '--')} "
                             f"{item.get('direction', '--')} {item.get('status', '--')} EXPIRES:{item.get('expires_at', '--')[-8:]}")
        else:
            lines.append("   No pending signals")
        lines.append("🚨 CURRENT SIGNAL / APPROVAL")
        if signal_data:
            expires_at = signal_data.get("expires_at")
            try:
                remaining = max(0, int((datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                remaining = "--"
            lines.extend([
                f"#{signal_data.get('signal_id', '--')[:8]} {signal_data.get('priority', '--')} "
                f"{signal_data.get('direction', '--')} {signal_data.get('underlying', '--')}  "
                f"LTP:{signal_data.get('ltp', '--')}  BRK:{signal_data.get('breakout', '--')}  "
                f"STATUS:{signal_data.get('status', '--')}  ⏳ {remaining}s",
                f"EXP:{signal_data.get('expiry', '--')} STRIKE:{signal_data.get('strike', '--')} "
                f"OPT:{signal_data.get('option', '--')} LTP:{signal_data.get('option_ltp', '--')}",
                f"OPTION PREV OHLC:{signal_data.get('option_ohlc', '--')}  SL:{signal_data.get('sl', '--')} "
                f"QTY:{signal_data.get('quantity', '--')} RISK:{signal_data.get('risk', '--')}",
                "⏳ A/A1..A4 APPROVE    R/R1..R4 REJECT",
            ])
        else:
            lines.append("🎯 SIGNALS: WAITING")
        lines.extend(["-" * width, "💼 ACTIVE POSITIONS"])
        lines.extend([f"   {position}" for position in positions] or ["   No active positions"])
        lines.extend(["-" * width, f"📋 EVENTS: {' | '.join(events[-3:]) if events else 'none'}",
                  "❤️ HEALTH " + " ".join(f"{name}:{components[name]}" for name in ("AUTH", "DATABASE", "HISTORY", "CANDLES")),
                  "          " + " ".join(f"{name}:{components[name]}" for name in ("SIGNALS", "BROKER", "RISK", "ORDERS")),
                  "AUTOMATIC STRATEGY EXIT   BROWSER=VIEW ONLY",
                  "=" * width])
        output = "\n".join(lines)
        try:
            safe_print("\033[2J\033[H\033[?25l", end="")
            safe_print(output, flush=True)
        except UnicodeEncodeError:
            safe_print(output.encode("ascii", "replace").decode("ascii"), flush=True)

    @classmethod
    def _candle_text(cls, candle):
        if candle is None:
            return "--"
        return (f"{cls._range_text(candle)} | O {candle.open:,.2f} | H {candle.high:,.2f} | "
                f"L {candle.low:,.2f} | C {candle.close:,.2f} | V {candle.volume}")

    @classmethod
    def _short_candle(cls, candle):
        if candle is None:
            return "--"
        return (f"{cls._range_text(candle)} O:{candle.open:,.1f} H:{candle.high:,.1f} "
                f"L:{candle.low:,.1f} C:{candle.close:,.1f}")
