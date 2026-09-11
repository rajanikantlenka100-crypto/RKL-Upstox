"""Upstox market-data and signal service. Orders require explicit approval."""

import signal
import threading
import time
import traceback
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import config
from broker.upstox import UpstoxAdapter
from broker.order_manager import BrokerOrderRejected, OrderExecutor
from broker.validation_report import LiveBrokerValidationReport
from instruments.options import (select_atm_option, select_candidate_options, validate_live_option_contract,
                                  validate_option_candle, validate_option_candle_identity)
from instruments.resolver import resolve_indices
from market_data.candles import CandleEngine
from market_data.indicators import cci, rsi
from market_data.health import FeedHealth
from market_data.historical import parse_historical_row
from market_data.models import Candle, MarketTick
from network_diagnostics import PublicIpError, order_ip_allowed, public_ipv4
from signals.breakout import BreakoutEngine, Type2Engine
from signals.rsi_filter import validate_rsi_entry
from signals.audit import SignalAudit
from signals.candidate_trace import CandidateTrace
from storage.sqlite_store import CandleStore
from services.preflight import run_local_preflight
from terminal_display import TerminalDisplay
from web_dashboard import DashboardServer
from signals.coordinator import ApprovalController, KeyboardController, SignalCoordinator
from trading.approval import approval_summary
from trading.positions import Position, PositionManager
from trading.stop_loss_policy import build_stop_loss
from trading.safety import SafetyGate, SystemState

IST = ZoneInfo("Asia/Kolkata")


class AuthenticationStartupBlocked(RuntimeError):
    """Expected startup stop caused by an unusable broker credential."""

    def __init__(self, classification):
        self.classification = classification
        super().__init__(classification)


class MarketDataService:
    def __init__(self):
        self.stop_event = threading.Event()
        self.instruments = resolve_indices()
        self.store = CandleStore(config.DATABASE_PATH, mode=config.EXECUTION_MODE)
        self.display = TerminalDisplay(self.instruments)
        self.engines = {name: CandleEngine(self._on_candle_closed) for name in self.instruments}
        self.option_engines = {}
        self.option_contracts = {}
        self.option_centers = {}
        self.option_refresh_lock = threading.Lock()
        self.signal_trace = CandidateTrace(config.SIGNAL_TRACE_PATH, config.SIGNAL_TRACE_ENABLED)
        self.breakouts = {name: BreakoutEngine(self.signal_trace.write) for name in self.instruments}
        self.type2_engines = {name: Type2Engine(self.signal_trace.write) for name in self.instruments}
        self.coordinator = SignalCoordinator(expiry_seconds=60)
        self.approval_controller = ApprovalController(self.coordinator, self._on_approval_decision)
        self.keyboard_controller = KeyboardController(self.approval_controller, self._on_keyboard_command)
        self.pending_signals = {}
        self.signal_audit = SignalAudit(config.SIGNAL_AUDIT_PATH)
        self.live_validation_report = LiveBrokerValidationReport(config.LIVE_VALIDATION_PATH)
        self.health = FeedHealth(config.STALE_DATA_SECONDS)
        self.adapter = UpstoxAdapter(self._on_tick, self._on_status, self._on_raw_market_event, self._on_portfolio_event)
        self.adapter.set_instruments(self.instruments)
        self._restore_last_market_state()
        self.order_manager = None
        self.position_manager = None
        self.signals_enabled = False
        self.safety = SafetyGate()
        self.trading_state = SystemState.DEGRADED
        self.trading_halt_reason = None
        self.recovery_required = False
        self.reconciliation_blocked = set()
        self.recovery_lock = threading.Lock()
        self.public_ip = None
        self.option_history_cache = {}
        self.option_history_lock = threading.Lock()
        self.exit_lock = threading.Lock()
        self.websocket_started = False
        self.dashboard_started = False
        self.preflight_result = None
        self.stop_reason = None
        self.lifecycle_log = config.ROOT / "logs" / "service_lifecycle.log"
        self.dashboard = DashboardServer(self.display, config.DASHBOARD_HOST, config.DASHBOARD_PORT)

    def _lifecycle(self, message):
        line = f"{datetime.now(IST).isoformat()} {message}"
        self.lifecycle_log.parent.mkdir(parents=True, exist_ok=True)
        with self.lifecycle_log.open("a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")
        if message.startswith(("[SERVICE] STOP", "[CRITICAL]", "[WS]")):
            print(message, flush=True)

    def _restore_last_market_state(self):
        """Restore the last observed broker tick for outside-hours visibility."""
        for instrument in self.instruments.values():
            row = self.store.latest_market_event(instrument.token)
            if not row:
                continue
            try:
                exchange_timestamp = datetime.fromisoformat(row[2])
                received_timestamp = datetime.fromisoformat(row[3])
                tick = MarketTick(
                    instrument.name, row[0], row[1], exchange_timestamp,
                    float(row[4]), int(row[5] or 0), row[6],
                    exchange_timestamp, received_timestamp, row[7], row[8],
                )
                self.display.update_tick(tick, None)
                market_open = datetime.now(IST).weekday() < 5 and config.MARKET_OPEN <= (datetime.now(IST).hour, datetime.now(IST).minute) < config.MARKET_CLOSE
                self.display.set_health(instrument.name, "DATA_STALE" if market_open else "FROZEN-CLOSED")
            except (TypeError, ValueError):
                self.display.set_health(instrument.name, "STATE_INVALID")

    def start(self):
        print("=" * 60 + "\nRKL ALGO TRADING\n" + "=" * 60, flush=True)
        print(f"EXECUTION MODE: {config.execution_mode_label()}", flush=True)
        print(f"REAL ORDERS: {'ENABLED' if config.ENABLE_REAL_ORDERS else 'DISABLED'}", flush=True)
        print(f"AUTO ENTRY: {'ENABLED' if config.AUTO_ENTRY_ENABLED else 'DISABLED'}", flush=True)
        try:
            config.validate_runtime()
        except RuntimeError as error:
            self._halt_trading(f"Startup configuration safety failure: {error}")
            return
        print("[BOOT] CONFIG LOADED", flush=True)
        print("[BOOT] DATABASE READY", flush=True)

        def startup_phase(name, action):
            if self.stop_event.is_set():
                return False
            started = time.monotonic()
            boot_markers = {
                "AUTHENTICATION": "[BOOT] AUTH START",
                "HISTORICAL DATA SYNC": "[BOOT] HISTORY START",
                "POSITION RECONCILIATION": "[BOOT] DATABASE START",
            }
            if name in boot_markers:
                print(boot_markers[name], flush=True)
            self.display.set_startup_phase(name)
            self.display.add_event(f"STARTUP {name} STARTED")
            print(f"[STARTUP] {name} ...", flush=True)
            try:
                result = action()
            except AuthenticationStartupBlocked:
                self.display.set_startup_phase(f"BLOCKED: {name}")
                raise
            except Exception as error:
                elapsed = time.monotonic() - started
                self.display.add_event(f"STARTUP {name} FAILED: {error}")
                self.display.set_startup_phase(f"FAILED: {name}")
                print(f"[STARTUP] {name} FAILED after {elapsed:.1f}s: {error}", flush=True)
                raise
            elapsed = time.monotonic() - started
            if self.stop_event.is_set():
                return False
            self.display.add_event(f"STARTUP {name} READY ({elapsed:.1f}s)")
            self.display.set_startup_phase(f"READY: {name}")
            print(f"[STARTUP] {name} READY ({elapsed:.1f}s)", flush=True)
            return True

        if config.LIVE_BROKER_VALIDATION_ENABLED:
            print("*** LIVE BROKER VALIDATION MODE ***", flush=True)
            print("*** REAL UPSTOX ORDER REQUESTS MAY BE SENT ***", flush=True)
        if not startup_phase("AUTHENTICATION", self._authenticate_and_validate):
            return
        self.display.set_component("AUTH", "READY")
        print("[AUTH] TOKEN VALID - API RESPONSE VERIFIED", flush=True)
        print("[BOOT] AUTH COMPLETE", flush=True)
        if not startup_phase("PUBLIC IP CHECK", self._check_public_ip):
            return
        if config.ENABLE_REAL_ORDERS:
            self.display.add_event("⚠️ REAL BROKER ORDER EXECUTION ENABLED")
        else:
            self.display.add_event("REAL BROKER ORDER EXECUTION DISABLED")
        self.order_manager = OrderExecutor(self.adapter.order_client)
        self.position_manager = PositionManager(self.adapter.order_client)
        self.display.set_component("BROKER", "READY")
        print("DATABASE READY | BROKER READY", flush=True)
        if not startup_phase("POSITION RECONCILIATION", self._reconcile_positions):
            return
        if not startup_phase("ORDER RECONCILIATION", self._reconcile_order_requests):
            return
        if not startup_phase("HISTORICAL DATA SYNC", self._backfill):
            return
        print("[BOOT] HISTORY COMPLETE", flush=True)
        with self.display.lock:
            history_ready = all(self.display.rest_status.get(name) == "SYNCED" for name in self.instruments)
        if self.trading_state == SystemState.TRADING_HALTED or not history_ready:
            self.recovery_required = not history_ready
            self._halt_trading("Startup reconciliation or historical synchronization incomplete")
        else:
            self.safety.running()
            self.trading_state = SystemState.RUNNING
        self._initialize_option_universe()
        self.preflight_result = run_local_preflight(
            store=self.store, instruments=self.instruments, display=self.display,
            position_manager=self.position_manager, order_manager=self.order_manager,
            public_ip=self.public_ip,
        )
        config.set_preflight_passed(
            self.preflight_result.passed and config.EXECUTION_MODE not in {"PRODUCTION", "SANDBOX"}
        )
        self.display.set_preflight(self.preflight_result)
        self.display.set_component("PREFLIGHT", "READY" if self.preflight_result.passed else "FAILED")
        print(f"PRODUCTION PRE-FLIGHT: {self.preflight_result.summary}", flush=True)
        if config.EXECUTION_MODE in {"PRODUCTION", "SANDBOX"} and not self.preflight_result.passed:
            self._halt_trading("Execution preflight failed: " + self.preflight_result.summary)
        self.adapter.start()
        self.websocket_started = True
        print("[BOOT] WEBSOCKET START", flush=True)
        if config.portfolio_stream_enabled():
            self.adapter.start_portfolio_stream()
        print("[BOOT] WEBSOCKET COMPLETE", flush=True)
        self.trading_state = self.safety.state
        order_status = "ENABLED" if config.ENABLE_REAL_ORDERS else (
            "DISABLED-READ_ONLY" if config.EXECUTION_MODE == "READ_ONLY" else "DISABLED-PREFLIGHT"
        )
        self.display.set_component("ORDERS", order_status)
        self.display.set_component("DASHBOARD", "STARTING")
        print("[BOOT] DASHBOARD START", flush=True)
        print("[DASHBOARD] STARTING", flush=True)
        try:
            dashboard_url = self.dashboard.start(open_browser=config.OPEN_BROWSER)
            self.dashboard_started = True
        except RuntimeError as error:
            self.display.set_component("DASHBOARD", "FAILED")
            self._record_event("DASHBOARD_START_FAILURE", {"reason": str(error)})
            print(f"[DASHBOARD] FAILED: {type(error).__name__}: {error}", flush=True)
            dashboard_url = "dashboard unavailable"
        else:
            self.display.set_component("DASHBOARD", "READY")
            print("[BOOT] DASHBOARD HEALTH CHECK PASS", flush=True)
            print(f"[DASHBOARD] READY - {dashboard_url}", flush=True)

        print("[BOOT] CANDLE ENGINE START", flush=True)
        print("[BOOT] CANDLE ENGINE COMPLETE", flush=True)
        print("[BOOT] SIGNAL ENGINE START", flush=True)
        print("[BOOT] SIGNAL ENGINE COMPLETE", flush=True)
        print("RKL UPSTOX SERVICE RUNNING", flush=True)
        print(f"MARKET: {'OPEN' if datetime.now(IST).weekday() < 5 and config.MARKET_OPEN <= (datetime.now(IST).hour, datetime.now(IST).minute) < config.MARKET_CLOSE else 'CLOSED'}", flush=True)
        print(f"ORDERS: {order_status}", flush=True)
        print("UPSTOX FEED STARTING | WAITING FOR SIGNAL...", flush=True)
        threading.Thread(target=self.display.render_loop, args=(self.stop_event,),
                 name="terminal-display", daemon=True).start()
        threading.Thread(target=self._periodic_sync, name="rest-reconciliation", daemon=True).start()
        print("[BOOT] SERVICE LOOP STARTED", flush=True)
        self._lifecycle("[SERVICE] MAIN LOOP ENTERED")
        while not self.stop_event.wait(10):
            self._lifecycle("[SERVICE] MAIN LOOP HEARTBEAT")
        self._lifecycle(f"[SERVICE] STOP EVENT SET reason={self.stop_reason or 'unknown'}")

    def _authenticate_and_validate(self):
        print("[AUTH] STARTING UPSTOX AUTHENTICATION", flush=True)
        try:
            self.adapter.authenticate()
        except RuntimeError as error:
            classification = "TOKEN_MISSING" if "Missing" in str(error) else "AUTHENTICATION ERROR"
            raise AuthenticationStartupBlocked(classification) from error
        print("[AUTH] TOKEN LOADED", flush=True)
        print("[AUTH] VALIDATING TOKEN WITH UPSTOX...", flush=True)
        result = self.adapter.validate_token()
        if result != "TOKEN VALID":
            self.display.set_component("AUTH", result)
            raise AuthenticationStartupBlocked(result)

    def stop(self, *_):
        if not self.stop_event.is_set():
            self.stop_reason = self.stop_reason or "direct stop request"
            self._lifecycle(f"[SERVICE] STOP REQUESTED source={self.stop_reason}")
            print("[SHUTDOWN] STOPPING", flush=True)
            self.stop_event.set()
            self.trading_state = SystemState.SHUTTING_DOWN
            self.safety.shutdown()
            if self.websocket_started:
                self.adapter.stop()
                print("[SHUTDOWN] WEBSOCKET STOPPED", flush=True)
            self.keyboard_controller.stop()
            self.approval_controller.stop()
            if self.dashboard_started:
                self.dashboard.stop()
                print("[SHUTDOWN] DASHBOARD STOPPED", flush=True)
            elif not self.websocket_started:
                print("[SHUTDOWN] NO ACTIVE MARKET-DATA SERVICES", flush=True)
            self.store.close()
            print("[SHUTDOWN] DATABASE CLOSED", flush=True)
            self.display.restore_terminal()
            print("[SHUTDOWN] COMPLETE", flush=True)

    def _on_tick(self, tick):
        try:
            if self.stop_event.is_set():
                return
            if tick.instrument not in self.instruments:
                option_engine = self.option_engines.get(tick.token)
                if option_engine is None:
                    return
                option_engine.add(tick)
                self.display.set_option_quote(tick.token, tick)
                self._try_activate_execution_preflight()
                return
            if not self._is_market_open(tick.timestamp):
                self._lifecycle(
                    f"[MARKET-TIME] instrument={tick.instrument} raw_timestamp={tick.timestamp.isoformat()} "
                    f"exchange_time={(tick.exchange_timestamp or tick.timestamp).isoformat()} "
                    f"observed_time={(tick.received_timestamp or datetime.now(IST)).isoformat()} "
                    f"source={tick.source} market_state=CLOSED action=FROZEN"
                )
                if tick.instrument not in self.display.snapshot()["latest"]:
                    self.display.set_health(tick.instrument, "FROZEN-CLOSED")
                return
            engine = self.engines[tick.instrument]
            current_before_tick = engine.current.get(tick.instrument)
            if current_before_tick:
                previous_bucket = current_before_tick["timestamp"]
                current_bucket = engine.bucket(tick.timestamp)
                if current_bucket - previous_bucket > timedelta(minutes=config.TIMEFRAME_MINUTES):
                    self.breakouts[tick.instrument].reset_sequence()
                    self.type2_engines[tick.instrument].reset()
                    self.signals_enabled = False
                    self.recovery_required = True
                    self.safety.degrade(f"unsafe feed gap for {tick.instrument}")
                    self.trading_state = self.safety.state
                    self._record_event("UNSAFE_FEED_GAP", {
                        "instrument": tick.instrument,
                        "previous_bucket": previous_bucket.isoformat(),
                        "current_bucket": current_bucket.isoformat(),
                    })
                    threading.Thread(target=self._recover_after_reconnect, name="gap-recovery", daemon=True).start()
            self.health.update(tick.instrument, tick.timestamp)
            self.display.set_health(tick.instrument, "LIVE")
            self.display.set_component("DATA FEED", "LIVE")
            self.display.set_sync(tick.instrument, feed_health=self.health.diagnostics(tick.instrument),
                                  subscription_state="SUBSCRIBED", websocket_state=self.display.snapshot()["ws_status"])
            engine.add(tick)
            current_data = engine.current.get(tick.instrument)
            current = Candle(timeframe="5m", **current_data) if current_data else None
            context = engine.context(tick.instrument)
            self.display.set_candle_context(tick.instrument, context["prev2"],
                                            context["previous"], current)
            if current:
                self.store.save_running(Candle(
                    instrument=current.instrument, exchange=current.exchange, token=current.token,
                    timestamp=current.timestamp, timeframe=current.timeframe, open=current.open,
                    high=current.high, low=current.low, close=current.close, volume=current.volume,
                    source=current.source, status="RUNNING"))
            self.display.update_tick(tick, current)
            self._try_activate_execution_preflight()
            center = round(tick.ltp / config.STRIKE_INTERVALS[tick.instrument]) * config.STRIKE_INTERVALS[tick.instrument]
            if self.option_centers.get(tick.instrument) not in {None, center}:
                threading.Thread(target=self._refresh_option_universe,
                                 args=(tick.instrument, tick.ltp), name="option-universe-refresh", daemon=True).start()
            self.option_centers.setdefault(tick.instrument, center)
            if current:
                self._evaluate_running_exits(tick.instrument, current)
            previous = engine.previous.get(tick.instrument)
            signal_event = (self.breakouts[tick.instrument].evaluate(previous, current, tick.ltp, tick.timestamp)
                            if config.SIGNAL_TYPE_1_ENABLED and self.signals_enabled
                            and self.trading_state == SystemState.RUNNING
                            and self.health.can_signal(tick.instrument)
                            and tick.instrument not in self.reconciliation_blocked else None)
            if signal_event:
                rsi_result = validate_rsi_entry(
                    engine.history.get(tick.instrument, []),
                    signal_event.direction,
                    config.RSI_PERIOD,
                    config.RSI_SMA_PERIOD,
                    config.RSI_LOOKBACK_PERIODS,
                )
                signal_event = replace(
                    signal_event,
                    rsi_filter_status=rsi_result.result,
                    rsi_matching_periods=rsi_result.matching_periods,
                    rsi_evaluated_periods=rsi_result.evaluated_candle_timestamps,
                    rsi_evaluated_values=rsi_result.evaluated_rsi_values,
                    rsi_evaluated_sma_values=rsi_result.evaluated_sma_values,
                    rsi_first_matching_timestamp=(rsi_result.matching_candle_timestamps[0]
                                                   if rsi_result.matching_candle_timestamps else None),
                    rsi_reason=rsi_result.reason,
                )
                if rsi_result.result == "PASS":
                    self.signal_trace.write({
                        "stage": "RSI_FILTER", "reason_code": "RSI_PASS",
                        "signal_id": signal_event.signal_id, "underlying": signal_event.underlying,
                        "direction": signal_event.direction, "matching_periods": rsi_result.matching_periods,
                    })
                    self._show_signal(signal_event)
                else:
                    self.signal_trace.write({
                        "stage": "RSI_FILTER", "reason_code": "RSI_" + rsi_result.result,
                        "signal_id": signal_event.signal_id, "underlying": signal_event.underlying,
                        "direction": signal_event.direction, "matching_periods": rsi_result.matching_periods,
                        "reason": rsi_result.reason,
                    })
                    self._record_event("RSI_FILTER_" + rsi_result.result, {
                        "signal_id": signal_event.signal_id,
                        "direction": signal_event.direction,
                        "matching_periods": rsi_result.matching_periods,
                        "evaluated_periods": [timestamp.isoformat() for timestamp in rsi_result.evaluated_candle_timestamps],
                        "evaluated_rsi_values": rsi_result.evaluated_rsi_values,
                        "evaluated_sma_values": rsi_result.evaluated_sma_values,
                        "reason": rsi_result.reason,
                    }, "signal_events")
                    self.signal_audit.write(self._audit_record(signal_event, {
                        "status": "RSI_" + rsi_result.result,
                        "rsi_filter_status": rsi_result.result,
                        "rsi_matching_periods": rsi_result.matching_periods,
                        "rsi_evaluated_periods": [timestamp.isoformat() for timestamp in rsi_result.evaluated_candle_timestamps],
                        "rsi_evaluated_values": rsi_result.evaluated_rsi_values,
                        "rsi_evaluated_sma_values": rsi_result.evaluated_sma_values,
                        "rsi_matching_periods_timestamps": [timestamp.isoformat() for timestamp in rsi_result.matching_candle_timestamps],
                        "rsi_reason": rsi_result.reason,
                    }))
            if (config.SIGNAL_TYPE_2_ENABLED and self.signals_enabled and self.trading_state == SystemState.RUNNING
                    and self.health.can_signal(tick.instrument)
                    and tick.instrument not in self.reconciliation_blocked and current):
                history = engine.history.get(tick.instrument, [])
                prev2 = engine.prev2.get(tick.instrument)
                for direction in ("CALL", "PUT"):
                    type2_rsi = validate_rsi_entry(
                        history, direction, config.RSI_PERIOD,
                        config.RSI_SMA_PERIOD, config.RSI_LOOKBACK_PERIODS,
                    )
                    type2_event = self.type2_engines[tick.instrument].evaluate(
                        prev2, previous, current, tick.ltp, direction=direction,
                        rsi_pass=type2_rsi.result == "PASS",
                    )
                    if type2_event and type2_rsi.result == "PASS":
                        type2_event = replace(
                            type2_event,
                            rsi_filter_status=type2_rsi.result,
                            rsi_matching_periods=type2_rsi.matching_periods,
                            rsi_evaluated_periods=type2_rsi.evaluated_candle_timestamps,
                            rsi_evaluated_values=type2_rsi.evaluated_rsi_values,
                            rsi_evaluated_sma_values=type2_rsi.evaluated_sma_values,
                            rsi_first_matching_timestamp=(type2_rsi.matching_candle_timestamps[0]
                                                           if type2_rsi.matching_candle_timestamps else None),
                            rsi_reason=type2_rsi.reason,
                        )
                        self._show_signal(type2_event)
        except (KeyError, ValueError) as error:
            self._on_status(f"INVALID MARKET DATA: {error}")
        except Exception as error:
            self.display.set_health(tick.instrument, "PROCESSING_ERROR")
            self.display.add_event(f"MARKET DATA ERROR {tick.instrument}: {error}")
            self._on_status(f"MARKET DATA PROCESSING ERROR: {error}")

    def _try_activate_execution_preflight(self):
        if config.EXECUTION_MODE not in {"PRODUCTION", "SANDBOX"} or config.PREFLIGHT_PASSED:
            return
        result = run_local_preflight(
            store=self.store, instruments=self.instruments, display=self.display,
            position_manager=self.position_manager, order_manager=self.order_manager,
            public_ip=self.public_ip, require_live_feeds=True,
        )
        self.preflight_result = result
        self.display.set_preflight(result)
        if not result.passed:
            return
        config.set_preflight_passed(True)
        self.display.set_component("PREFLIGHT", "READY")
        self.display.add_event("PRODUCTION PRE-FLIGHT PASS | REAL ORDER GATE OPEN")

    def _on_candle_closed(self, candle):
        try:
            reconciliation = self.store.reconcile(candle)
        except Exception as error:
            self._halt_trading(f"Database candle persistence failed: {error}")
            self._record_event("DATABASE_FAILURE", {"instrument": candle.instrument, "reason": str(error)})
            return
        if reconciliation == "MISMATCH":
            self.store.record("reconciliation_events", str(uuid4()), {
                "entity_type": "CANDLE", "entity_id": f"{candle.instrument}:{candle.timestamp.isoformat()}",
                "action": "MISMATCH", "rest_ohlc": "stored", "ws_ohlc": [candle.open, candle.high, candle.low, candle.close],
            })
            self.display.set_sync(candle.instrument, status="🔴 MISMATCH",
                                  last_local=candle.timestamp.strftime("%H:%M"),
                                  checked=datetime.now(IST).strftime("%H:%M:%S"))
            engine_context = self.engines[candle.instrument].context(candle.instrument)
            self.display.set_candle_context(candle.instrument, engine_context["prev2"],
                                             engine_context["previous"], engine_context["running"])
        candles = self.engines[candle.instrument].history[candle.instrument]
        cci_value = cci(candles, config.CCI_PERIOD)
        rsi_value = rsi(candles, config.RSI_PERIOD)
        self.display.set_indicators(candle.instrument, cci_value, rsi_value, candle.timestamp)
        candles_before_close = self.engines[candle.instrument].history[candle.instrument]
        prior_candle = candles_before_close[-2] if len(candles_before_close) >= 2 else None
        self._evaluate_closed_exits(candle, prior_candle, cci_value)
        self.display.set_status(f"🕯️ 5M CANDLE CLOSED {candle.instrument} {candle.timestamp:%H:%M}")

    def _on_option_candle_closed(self, candle):
        try:
            self.store.reconcile(candle)
        except Exception as error:
            self._record_event("OPTION_CANDLE_PERSISTENCE_FAILED", {
                "instrument_key": candle.token, "reason": str(error),
            })

    def _initialize_option_universe(self, names=None, underlying_prices=None):
        names = tuple(names or self.instruments)
        tracked = []
        for name in names:
            instrument = self.instruments[name]
            latest = self.display.snapshot()["latest"].get(name)
            underlying_ltp = (underlying_prices or {}).get(name) or (latest.ltp if latest else self.adapter.ltp(instrument))
            try:
                rows = self.adapter.option_contracts(instrument.token)
                selected = []
                for direction in ("CALL", "PUT"):
                    selected.extend(select_candidate_options(
                        name, instrument.exchange, underlying_ltp, direction, rows,
                        underlying_key=instrument.token, count=5,
                    ))
                for contract in selected:
                    if contract.instrument_key in self.option_contracts:
                        continue
                    option_instrument = instrument.__class__(
                        contract.instrument_key, contract.tradingsymbol, contract.instrument_key,
                        contract.exchange, 2 if contract.exchange == "NSE_FO" else 4,
                    )
                    self.option_contracts[contract.instrument_key] = contract
                    engine = CandleEngine(self._on_option_candle_closed)
                    try:
                        option_candles = []
                        for row in self.adapter.fetch_historical(option_instrument, count=10):
                            timestamp, open_price, high, low, close, volume = parse_historical_row(row)
                            if timestamp + timedelta(minutes=config.TIMEFRAME_MINUTES) > datetime.now(IST):
                                continue
                            candle = Candle(contract.instrument_key, contract.exchange, contract.instrument_key,
                                            timestamp, "5m", open_price, high, low, close, volume, "HISTORICAL")
                            self.store.reconcile(candle)
                            option_candles.append(candle)
                        engine.seed(option_candles)
                    except Exception as error:
                        self._record_event("OPTION_HISTORY_UNAVAILABLE", {
                            "instrument_key": contract.instrument_key, "reason": str(error),
                        })
                    self.option_engines[contract.instrument_key] = engine
                    tracked.append(option_instrument)
            except Exception as error:
                self._record_event("OPTION_UNIVERSE_UNAVAILABLE", {
                    "instrument": name, "reason": str(error),
                })
        if tracked:
            self.adapter.set_option_instruments(tracked)
            self.display.set_option_universe(tuple(self.option_contracts.values()))
            self.display.add_event(f"OPTION UNIVERSE READY ({len(tracked)} CONTRACTS)")

    def _refresh_option_universe(self, name, ltp):
        if not self.option_refresh_lock.acquire(blocking=False):
            return
        try:
            center = round(ltp / config.STRIKE_INTERVALS[name]) * config.STRIKE_INTERVALS[name]
            if self.option_centers.get(name) == center:
                return
            self._initialize_option_universe((name,), {name: ltp})
            self.option_centers[name] = center
            self._record_event("OPTION_UNIVERSE_REFRESHED", {"instrument": name, "atm_center": center})
        finally:
            self.option_refresh_lock.release()

    def _evaluate_running_exits(self, instrument, running):
        if not self.position_manager:
            return
        with self.position_manager.lock:
            positions = [position for position in self.position_manager.positions.values()
                         if position.underlying == instrument and position.state in {"OPEN", "SL_ACTIVE"}]
        for position in positions:
            if not position.strategy_exit:
                continue
            reason = position.strategy_exit.on_running_candle(running)
            if not reason:
                continue
            position.five_r_state = "HIT"
            position.exit_reason = reason
            self._record_event("FIVE_R_EXIT_TRIGGERED", {
                "trade_id": position.trade_id, "instrument": instrument,
                "initial_risk": position.initial_risk, "five_r": position.strategy_exit.five_r,
                "running_range": running.high - running.low,
            }, "position_events")
            self.display.add_event(f"{position.trade_id} 5R EXIT TRIGGERED")
            threading.Thread(target=self._execute_exit, args=(position.trade_id,),
                             name="five-r-exit", daemon=True).start()

    def _evaluate_closed_exits(self, candle, previous_candle, cci_value):
        if not self.position_manager:
            return
        with self.position_manager.lock:
            positions = [position for position in self.position_manager.positions.values()
                         if position.underlying == candle.instrument and position.state in {"OPEN", "SL_ACTIVE"}]
        for position in positions:
            if not position.strategy_exit:
                continue
            before = position.strategy_exit.cci_state
            reason = position.strategy_exit.on_closed_candle(candle, previous_candle, cci_value)
            position.cci_exit_state = position.strategy_exit.cci_state
            if before != position.cci_exit_state:
                self._record_event("CCI_EXIT_ARMED", {
                    "trade_id": position.trade_id, "instrument": candle.instrument,
                    "cci": cci_value, "candle_timestamp": candle.timestamp.isoformat(),
                }, "position_events")
                self.display.add_event(f"{position.trade_id} CALL/PUT EXIT {position.cci_exit_state}")
            if reason:
                position.exit_reason = reason
                self._record_event("CCI_EXIT_CONFIRMED", {
                    "trade_id": position.trade_id, "instrument": candle.instrument,
                    "confirmation_candle": candle.timestamp.isoformat(),
                }, "position_events")
                threading.Thread(target=self._execute_exit, args=(position.trade_id,),
                                 name="cci-exit", daemon=True).start()

    def _on_raw_market_event(self, event):
        if self.stop_event.is_set():
            return
        try:
            self.store.record_market_event(event["event_id"], event)
        except Exception as error:
            self._halt_trading(f"Raw market-event persistence failed: {error}")

    def _on_portfolio_event(self, event):
        self._record_event("PORTFOLIO_STREAM_EVENT", {"payload": event})
        if self.position_manager and not self.stop_event.is_set():
            threading.Thread(target=self._reconcile_positions,
                             name="portfolio-reconciliation", daemon=True).start()
    def _on_status(self, status):
        if status in {"WEBSOCKET CONNECTED", "UPSTOX FEED CONNECTED"} or status.startswith("UPSTOX FEED CONNECTED "):
            self.display.set_component("DATA FEED", "LIVE")
            self.display.set_component("CANDLES", "READY")
            if self.recovery_required:
                threading.Thread(target=self._recover_after_reconnect, name="feed-recovery", daemon=True).start()
            else:
                self.signals_enabled = self.safety.ready()
                self.display.set_component("SIGNALS", "READY" if self.signals_enabled else "PAUSED")
                if not self.signals_enabled:
                    self.display.add_event("🛑 SIGNALS BLOCKED: safety gate is not READY")
        elif status in {"WEBSOCKET DISCONNECTED", "WEBSOCKET RECONNECTING", "UPSTOX FEED DISCONNECTED"} or status.startswith(("WEBSOCKET ERROR", "UPSTOX FEED ERROR")):
            self.display.set_component("DATA FEED", "STALE" if "DISCONNECTED" in status else "RECOVERING")
            self.signals_enabled = False
            self.recovery_required = True
            self.safety.degrade(status)
            self.trading_state = self.safety.state
            self.display.set_component("SIGNALS", "PAUSED")
        self.display.set_status(status)

    def _record_event(self, event_type, values, table="system_events"):
        try:
            primary_id = str(uuid4())
            created_at = datetime.now(IST).isoformat()
            details = dict(values)
            if table == "signal_events":
                self.store.record(table, primary_id, {
                    "signal_id": details.pop("signal_id", ""), "event_type": event_type,
                    "created_at": created_at, "payload": details,
                })
            elif table == "position_events":
                self.store.record(table, primary_id, {
                    "trade_id": details.pop("trade_id", ""), "event_type": event_type,
                    "created_at": created_at, "payload": details,
                })
            elif table == "stop_orders":
                self.store.record(table, primary_id, {
                    "trade_id": details.pop("trade_id", ""), "status": event_type,
                    "created_at": created_at, "payload": details,
                })
            elif table == "orders":
                self.store.record(table, details.pop("order_id", primary_id), {
                    "signal_id": details.pop("signal_id", ""), "trade_id": details.pop("trade_id", ""),
                    "status": event_type, "created_at": created_at, "payload": details,
                })
            elif table == "fills":
                self.store.record(table, primary_id, {
                    "order_id": details.pop("order_id", ""), "trade_id": details.pop("trade_id", ""),
                    "quantity": details.pop("quantity", 0), "average_price": details.pop("average_price", 0),
                    "created_at": created_at, "payload": details,
                })
            elif table == "exits":
                self.store.record(table, primary_id, {
                    "trade_id": details.pop("trade_id", ""), "status": event_type,
                    "created_at": created_at, "payload": details,
                })
            elif table == "reconciliation_events":
                self.store.record(table, primary_id, {
                    "entity_type": details.pop("entity_type", ""), "entity_id": details.pop("entity_id", ""),
                    "action": event_type, "created_at": created_at, "payload": details,
                })
            else:
                self.store.record("system_events", primary_id, {
                    "event_type": event_type,
                    "created_at": created_at,
                    "payload": {"entity_table": table, **details},
                })
        except Exception as error:
            self.trading_state = SystemState.TRADING_HALTED
            self.display.add_event(f"🚨 JOURNAL FAILURE: {error}")

    def _halt_trading(self, reason):
        self.safety.halt(reason)
        self.trading_state = SystemState.TRADING_HALTED
        self.trading_halt_reason = reason
        self.signals_enabled = False
        self.display.set_component("SIGNALS", "HALTED")
        self.display.add_event(f"🛑 TRADING HALTED: {reason}")
        self._record_event("TRADING_HALTED", {"reason": reason})

    def _on_keyboard_command(self, command):
        """Keep the terminal notification-only; exits are strategy or broker driven."""
        if command.startswith("UNKNOWN:"):
            self.display.add_event(f"ℹ️ {command}")
            return
        self.display.add_event(f"⌨️ COMMAND: {command}")

    def _check_public_ip(self):
        if not config.ENABLE_REAL_ORDERS:
            self.public_ip = "NOT REQUIRED (ORDERS DISABLED)"
            self.display.set_network(self.public_ip, "NOT REQUIRED")
            self.display.add_event("PUBLIC IP CHECK SKIPPED: REAL ORDERS DISABLED")
            return
        try:
            self.public_ip = public_ipv4()
            allowed, reason = order_ip_allowed(self.public_ip, require_config=config.ENABLE_REAL_ORDERS)
            if config.ENABLE_REAL_ORDERS:
                registered = self.adapter.client.registered_static_ips()
                registered_data = registered.get("data") or {}
                registered_ips = {str(value) for value in (registered_data.get("primary_ip"), registered_data.get("secondary_ip")) if value}
                if self.public_ip not in registered_ips:
                    allowed = False
                    reason = "PUBLIC IP DOES NOT MATCH UPSTOX REGISTERED STATIC IP"
            self.display.set_network(self.public_ip, "MATCH" if allowed else "NOT WHITELISTED")
            if not allowed:
                self.display.set_component("ORDERS", "IP BLOCKED")
                if config.ENABLE_REAL_ORDERS:
                    self._halt_trading(f"Order IP safety policy failed: {reason}")
                    self._record_event("CRITICAL_ORDER_IP_FAILURE", {"reason": reason})
        except PublicIpError as error:
            self.public_ip = "UNAVAILABLE"
            self.display.set_network(self.public_ip, "UNAVAILABLE")
            self._on_status(f"PUBLIC IP CHECK UNAVAILABLE: {error}")
            if config.ENABLE_REAL_ORDERS:
                self._halt_trading(f"Order IP safety check failed: {error}")
                self._record_event("CRITICAL_ORDER_IP_FAILURE", {"reason": str(error)})

    def _recover_after_reconnect(self):
        if not self.recovery_lock.acquire(blocking=False):
            return
        try:
            self.signals_enabled = False
            self._on_status("FEED RECOVERY: HISTORICAL RECONCILIATION")
            self._backfill()
            recovered = all(self.display.rest_status.get(name) == "SYNCED" for name in self.instruments)
            self.recovery_required = not recovered
            hard_halt = self.trading_state == SystemState.TRADING_HALTED and self.trading_halt_reason != "Startup reconciliation or historical synchronization incomplete"
            if recovered and not hard_halt:
                self.safety.running()
                self.trading_state = SystemState.RUNNING
            self.signals_enabled = recovered and not hard_halt and self.safety.ready()
            self.display.set_component("SIGNALS", "READY" if self.signals_enabled else "PAUSED")
            self._on_status("FEED RECOVERY COMPLETE" if self.signals_enabled else "FEED RECOVERY INCOMPLETE")
        finally:
            self.recovery_lock.release()

    def _backfill(self):
        for instrument in self.instruments.values():
            try:
                rows = self.adapter.fetch_historical(instrument, count=config.HISTORICAL_COUNT)
                candles = []
                mismatch = False
                seen_timestamps = set()
                previous_timestamp = None
                for row in rows:
                    timestamp, open_price, high, low, close, volume = parse_historical_row(row)
                    if timestamp in seen_timestamps:
                        raise ValueError(f"Duplicate historical candle timestamp {timestamp.isoformat()}")
                    if previous_timestamp is not None and timestamp <= previous_timestamp:
                        raise ValueError(f"Historical candle timestamps are not strictly chronological for {instrument.name}")
                    seen_timestamps.add(timestamp)
                    previous_timestamp = timestamp
                    if timestamp + timedelta(minutes=config.TIMEFRAME_MINUTES) > datetime.now(IST):
                        continue
                    candle = Candle(instrument=instrument.name, exchange=instrument.exchange, token=instrument.token,
                                    timestamp=timestamp, timeframe="5m", open=open_price, high=high,
                                    low=low, close=close, volume=volume, source="HISTORICAL")
                    reconciliation = self.store.reconcile(candle)
                    if reconciliation == "MISMATCH":
                        mismatch = True
                        local = self.store.existing_ohlc(candle)
                        self._record_event("BROKER_MISMATCH", {
                            "instrument": instrument.name, "timestamp": timestamp.isoformat(),
                            "rest_ohlc": [open_price, high, low, close, volume],
                            "local_ohlc": list(local) if local else None,
                        }, "reconciliation_events")
                        self._on_status(f"RECONCILIATION MISMATCH {instrument.name} {timestamp.isoformat()} REST={open_price:.2f},{high:.2f},{low:.2f},{close:.2f} LOCAL={local[:4] if local else 'missing'}")
                        self.store.replace(candle)
                    candles.append(candle)
                minimum_warmup = config.RSI_PERIOD + config.RSI_SMA_PERIOD + config.RSI_LOOKBACK_PERIODS
                if len(candles) < minimum_warmup:
                    raise ValueError(f"Insufficient historical warm-up for {instrument.name}: {len(candles)} < {minimum_warmup}")
                self.engines[instrument.name].seed(candles)
                running_row = self.store.latest_running(instrument.name)
                if running_row:
                    running = Candle(instrument=running_row[0], exchange=running_row[1], token=running_row[2],
                                     timestamp=datetime.fromisoformat(running_row[3]), timeframe=running_row[5],
                                     open=running_row[6], high=running_row[7], low=running_row[8],
                                     close=running_row[9], volume=running_row[10], source=running_row[11], status="RUNNING")
                    if running.timestamp.date() == datetime.now(IST).date() and running.timestamp >= (candles[-1].timestamp if candles else running.timestamp):
                        self.engines[instrument.name].restore_running(running)
                self.reconciliation_blocked.discard(instrument.name)
                if config.INTRADAY_RECONCILIATION_ENABLED:
                    self._reconcile_intraday(instrument, candles)
                checked = datetime.now(IST).strftime("%H:%M:%S")
                last_hist = candles[-1].timestamp.strftime("%H:%M") if candles else "--"
                self.display.set_sync(instrument.name, status="SYNCED", last_hist=last_hist,
                                      last_local=last_hist, gap=0, checked=checked)
                self.display.set_rest_status(instrument.name, "SYNCED")
                if candles:
                    context = self.engines[instrument.name].context(instrument.name)
                    self.display.set_candle_context(instrument.name, context["prev2"],
                                                     context["previous"], context["running"])
                    self.display.set_indicators(
                        instrument.name,
                        cci(candles, config.CCI_PERIOD),
                        rsi(candles, config.RSI_PERIOD),
                        candles[-1].timestamp,
                    )
                history_label = "history reconciled" if not mismatch else "history mismatches repaired"
                self.display.add_event(f"{instrument.name} {history_label} ({len(candles)})")
            except Exception as error:
                self.display.set_rest_status(instrument.name, "FAILED")
                self.display.set_sync(instrument.name, status="FAILED", reason=str(error),
                                      last_hist="--", last_local="--", gap="--",
                                      checked=datetime.now(IST).strftime("%H:%M:%S"))
                self._on_status(f"REST SYNC FAILED {instrument.name}: {error}")
        with self.display.lock:
            synced = all(self.display.rest_status.get(name) == "SYNCED" for name in self.instruments) and not self.reconciliation_blocked
        self.display.set_component("HISTORY", "READY" if synced else "DEGRADED")
        self.display.set_component("CANDLES", "READY" if synced else "DEGRADED")

    def _reconcile_intraday(self, instrument, historical_candles):
        try:
            rows = self.adapter.fetch_intraday(instrument, count=config.HISTORICAL_COUNT)
            historical_by_time = {candle.timestamp: candle for candle in historical_candles}
            for row in rows:
                timestamp, open_price, high, low, close, volume = parse_historical_row(row)
                if timestamp + timedelta(minutes=config.TIMEFRAME_MINUTES) > datetime.now(IST):
                    continue
                historical = historical_by_time.get(timestamp)
                if not historical:
                    continue
                intraday_values = (open_price, high, low, close, volume)
                historical_values = (historical.open, historical.high, historical.low, historical.close, historical.volume)
                if intraday_values != historical_values:
                    self.reconciliation_blocked.add(instrument.name)
                    self.display.set_rest_status(instrument.name, "MISMATCH")
                    self._record_event("DATA_RECONCILIATION_MISMATCH", {
                        "instrument": instrument.name, "timestamp": timestamp.isoformat(),
                        "historical_ohlcv": historical_values, "intraday_ohlcv": intraday_values,
                        "source": "UPSTOX_HISTORICAL_V3_VS_INTRADAY_V3", "resolution_status": "UNRESOLVED",
                    }, "reconciliation_events")
                    self.display.set_sync(instrument.name, status="🔴 MISMATCH", reason="historical/intraday disagreement")
                    return
        except Exception as error:
            self.reconciliation_blocked.add(instrument.name)
            self.display.set_rest_status(instrument.name, "FAILED")
            self._record_event("DATA_RECONCILIATION_UNAVAILABLE", {
                "instrument": instrument.name, "reason": str(error), "resolution_status": "UNRESOLVED",
            }, "reconciliation_events")
            self._on_status(f"INTRADAY RECONCILIATION FAILED {instrument.name}: {error}")

    def _periodic_sync(self):
        last_reconciliation = datetime.now(IST)
        while not self.stop_event.wait(1):
            for name in self.instruments:
                status = self.health.check(name)
                self.display.set_health(name, status)
                self.display.set_sync(name, feed_health=self.health.diagnostics(name),
                                      subscription_state="SUBSCRIBED",
                                      websocket_state=self.display.snapshot()["ws_status"])
            if (datetime.now(IST) - last_reconciliation).total_seconds() < config.REST_SYNC_INTERVAL_SECONDS:
                continue
            last_reconciliation = datetime.now(IST)
            if self.recovery_required:
                self._recover_after_reconnect()
            else:
                self._on_status("REST RECONCILIATION STARTED")
                self._backfill()
                with self.display.lock:
                    synced = all(self.display.rest_status.get(name) == "SYNCED" for name in self.instruments)
                if not synced:
                    self.signals_enabled = False
                    self.recovery_required = True
                    self.safety.degrade("periodic historical synchronization incomplete")
                    self.trading_state = self.safety.state
                    self.display.set_component("SIGNALS", "PAUSED")
            if self.position_manager:
                self._reconcile_positions()

    def _show_signal(self, signal_event):
        created_at = datetime.now(IST)
        self.coordinator.submit(signal_event, created_at)
        self.store.record("signals", signal_event.signal_id, {
            "instrument": signal_event.underlying, "direction": signal_event.direction,
            "status": "DETECTED", "created_at": created_at.isoformat(),
            "payload": self._audit_record(signal_event, {}),
        })
        self._record_event("SIGNAL_CREATED", {"signal_id": signal_event.signal_id}, "signal_events")
        self._validation_record({
            "event": "SIGNAL_DETECTED", "signal_id": signal_event.signal_id,
            "timestamp": created_at.isoformat(), "index": signal_event.underlying,
            "direction": signal_event.direction,
            "data_classification": "LOCAL SYSTEM DATA",
        })
        self._record_event("SIGNAL_QUEUED", {"signal_id": signal_event.signal_id}, "signal_events")
        expires_at = created_at + timedelta(seconds=60)
        self.pending_signals[signal_event.signal_id] = signal_event
        self.signal_audit.write(self._audit_record(signal_event, {
            "status": "WAITING", "approval": "PENDING", "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }))
        self.display.set_signal({
            "signal_type": signal_event.signal_type, "direction": signal_event.direction, "underlying": signal_event.underlying,
            "ltp": f"{signal_event.ltp:.2f}", "breakout": f"{signal_event.breakout_price:.2f}",
            "status": "OPTION DATA PENDING",
            "signal_id": signal_event.signal_id, "priority": "PRIMARY" if signal_event.underlying in {"NIFTY", "SENSEX"} else "SECONDARY",
            "type2_conditions": signal_event.type2_conditions,
            "created_at": created_at.isoformat(), "expires_at": expires_at.isoformat(),
        })
        self.display.add_event(f"SIGNAL #{signal_event.signal_id[:8]} {signal_event.underlying} {signal_event.direction} | OPTION DATA PENDING")
        self._publish_signal_queue()
        threading.Thread(target=self._resolve_signal_option, args=(signal_event, created_at, expires_at),
                     name="option-resolution", daemon=True).start()

    def _resolve_signal_option(self, signal_event, created_at, expires_at):
        try:
            with self.coordinator.lock:
                active = any(item and item["signal"].signal_id == signal_event.signal_id
                             for item in self.coordinator.active.values())
                queued = any(item["signal"].signal_id == signal_event.signal_id for item in self.coordinator.pending)
            if not active and not queued:
                return
            underlying_instrument = self.instruments[signal_event.underlying]
            option_rows = self.adapter.option_contracts(underlying_instrument.token)
            occupied_tokens = self.position_manager.active_tokens() if self.position_manager else set()
            option_quotes = {
                token: {"ltp": quote.ltp, "volume": quote.volume,
                        "timestamp": quote.timestamp,
                        "fresh": (datetime.now(IST) - quote.timestamp.astimezone(IST)).total_seconds() <= config.STALE_DATA_SECONDS}
                for token, quote in self.display.snapshot().get("option_quotes", {}).items()
            }
            option = select_atm_option(signal_event.underlying, underlying_instrument.exchange,
                                       signal_event.ltp, signal_event.direction, option_rows,
                                       underlying_key=underlying_instrument.token,
                                       occupied_tokens=occupied_tokens, quote_data=option_quotes,
                                       require_live_quote=True)
            option_instrument = self.instruments[signal_event.underlying].__class__(
                signal_event.underlying, option["symbol"], option["token"], option["exchange"],
                2 if option["exchange"] == "NFO" else 4
            )
            live_quote = option_quotes.get(option["token"])
            if not live_quote or (datetime.now(IST) - live_quote["timestamp"].astimezone(IST)).total_seconds() > config.STALE_DATA_SECONDS:
                raise RuntimeError("OPTION_LTP_MISSING_OR_STALE")
            option_quote = {"ltp": live_quote["ltp"], "timestamp": live_quote["timestamp"],
                            "instrument_key": option["token"]}
            option_ltp = option_quote["ltp"]
            if option_quote["instrument_key"] != option["token"]:
                raise RuntimeError("OPTION_LTP_IDENTITY_MISMATCH")
            if option_quote["timestamp"] is None:
                raise RuntimeError("OPTION_LTP_TIMESTAMP_MISSING")
            if (datetime.now(IST) - option_quote["timestamp"].astimezone(IST)).total_seconds() > config.STALE_DATA_SECONDS:
                raise RuntimeError("OPTION_LTP_STALE")
            cache_key = option["token"]
            with self.option_history_lock:
                cached = self.option_history_cache.get(cache_key)
            live_context = self.option_engines.get(option["token"])
            live_previous = live_context.context(option["token"])["previous"] if live_context else None
            if live_previous is not None:
                option_rows = [[live_previous.timestamp.isoformat(), live_previous.open,
                                 live_previous.high, live_previous.low, live_previous.close,
                                 live_previous.volume]]
            elif cached and (datetime.now(IST) - cached[0]).total_seconds() < 60:
                option_rows = cached[1]
            else:
                option_rows = self.adapter.fetch_historical(option_instrument, count=2)
                with self.option_history_lock:
                    self.option_history_cache[cache_key] = (datetime.now(IST), option_rows)
            if len(option_rows) < 1:
                raise RuntimeError("Insufficient real option history for SL")
            if live_previous is not None:
                option_rows = [option_rows[0], option_rows[0]]
            option_previous = option_rows[-2]
            option_timestamp, option_open, option_high, option_low, option_close, option_volume = parse_historical_row(option_previous)
            option_candle = {
                "instrument_key": option["token"],
                "expiry": option["expiry"],
                "strike": option["strike"],
                "option_type": option["option_type"],
            }
            validate_option_candle_identity(option_candle, option)
            validate_option_candle(option_previous, option, timestamp=option_timestamp)
            option_previous_low = option_low
            self.display.set_signal({
                "signal_type": signal_event.signal_type, "direction": signal_event.direction, "underlying": signal_event.underlying,
                "ltp": f"{signal_event.ltp:.2f}", "breakout": f"{signal_event.breakout_price:.2f}",
                "expiry": option["expiry"], "strike": option["strike"], "option": option["symbol"],
                "option_ltp": f"{option_ltp:.2f}", "option_ohlc": option_previous[1:5],
                "sl": f"{option_previous_low - config.SL_BUFFER:.2f}", "quantity": option["lot_size"],
                "capital": f"{option_ltp * option['lot_size']:.2f}",
                "risk": f"{max(0.0, (option_ltp - option_previous_low + config.SL_BUFFER) * option['lot_size']):.2f}",
                "status": "AUTO ENTRY PENDING" if config.AUTO_ENTRY_ENABLED else "APPROVAL REQUIRED",
            })
            self.pending_signals[signal_event.signal_id] = (signal_event, option, option_ltp, option_previous_low)
            self.display.set_signal({**approval_summary(signal_event, option, option_ltp, option_previous_low, option["lot_size"]),
                                     "signal_id": signal_event.signal_id, "priority": "PRIMARY" if signal_event.underlying in {"NIFTY", "SENSEX"} else "SECONDARY",
                                     "signal_type": signal_event.signal_type,
                                     "type2_conditions": signal_event.type2_conditions,
                                     "created_at": created_at.isoformat(), "expires_at": expires_at.isoformat(),
                                     "option_ohlc": option_previous[1:5]})
            self.display.add_event(f"OPTION READY {option['symbol']} | SL:{option_previous_low - config.SL_BUFFER:.2f} | QTY:{option['lot_size']}")
            self._validation_record({
                "event": "OPTION_RESOLVED", "signal_id": signal_event.signal_id,
                "symbol": option["symbol"], "token": option["token"],
                "expiry": option["expiry"], "strike": option["strike"],
                "option_type": option["option_type"], "option_ltp": option_ltp,
                "option_ltp_timestamp": option_quote["timestamp"].isoformat(),
                "option_candle_timestamp": option_timestamp.isoformat(),
                "option_candle_ohlc": [option_open, option_high, option_low, option_close],
                "option_candle_identity": option_candle,
                "sl": option_previous_low - config.SL_BUFFER, "lot_size": option["lot_size"],
                "quantity": option["lot_size"], "data_classification": "REAL BROKER DATA",
            })
            self.signal_audit.write(self._audit_record(signal_event, {
                "status": "WAITING", "approval": "PENDING", "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(), "option_symbol": option["symbol"],
                "option_token": option["token"], "option_ltp": option_ltp,
                "option_ltp_timestamp": option_quote["timestamp"].isoformat(),
                "option_candle_timestamp": option_timestamp.isoformat(),
                "option_candle_ohlc": [option_open, option_high, option_low, option_close],
                "option_candle_identity": option_candle,
                "sl": option_previous_low - config.SL_BUFFER, "quantity": option["lot_size"],
                "risk": max(0.0, (option_ltp - option_previous_low + config.SL_BUFFER) * option["lot_size"]),
            }))
            if config.AUTO_ENTRY_ENABLED:
                resolved = self.coordinator.resolve(signal_event.signal_id, "AUTO_ENTRY")
                self._on_approval_decision(resolved)
        except Exception as error:
            self.coordinator.resolve(signal_event.signal_id, "REJECTED")
            self._validation_record({
                "event": "OPTION_RESOLUTION_REJECTED", "signal_id": signal_event.signal_id,
                "underlying": signal_event.underlying, "direction": signal_event.direction,
                "reason": str(error), "data_classification": "REAL BROKER DATA",
            })
            self._on_status(f"OPTION RESOLUTION FAILED: {error}")

    def _on_approval_decision(self, resolved):
        if not resolved:
            return
        signal_id = resolved["signal"].signal_id
        payload = self.pending_signals.get(signal_id)
        with self.coordinator.lock:
            if resolved["status"] == "AUTO_ENTRY" and datetime.now(IST) >= resolved["created_at"] + self.coordinator.expiry:
                resolved["status"] = "EXPIRED"
        self.display.add_event(f"AUTO ENTRY STARTED {signal_id}" if resolved["status"] == "AUTO_ENTRY" else f"{resolved['status']} {signal_id}")
        self._publish_signal_queue()
        self.signal_audit.write({"signal_id": signal_id, "status": resolved["status"],
                     "approval": resolved["status"], "updated_at": datetime.now(IST).isoformat()})
        self._record_event(f"SIGNAL_{resolved['status']}", {"signal_id": signal_id}, "signal_events")
        self.store.record("approvals", str(uuid4()), {
            "signal_id": signal_id, "decision": resolved["status"],
            "created_at": datetime.now(IST).isoformat(),
        })
        self._validation_record({
            "event": "AUTO_ENTRY_ELIGIBLE" if resolved["status"] == "AUTO_ENTRY" else "APPROVAL", "signal_id": signal_id,
            "approval_time": datetime.now(IST).isoformat(), "operator_action": resolved["status"],
            "data_classification": "LOCAL SYSTEM DATA",
        })
        if resolved["status"] != "AUTO_ENTRY" or not isinstance(payload, tuple):
            self.pending_signals.pop(signal_id, None)
            self.display.clear_signal(f"Signal {resolved['status'].lower()}")
            self._publish_signal_queue()
            return
        signal_event, option, option_ltp, option_previous_low = payload
        if not config.ENABLE_REAL_ORDERS:
            self.pending_signals.pop(signal_id, None)
            self.display.set_signal({
                "signal_id": signal_id, "underlying": signal_event.underlying,
                "direction": signal_event.direction, "signal_type": signal_event.signal_type,
                "status": "PAPER ENTRY | REAL ORDER DISABLED",
            })
            self.display.add_event(f"PAPER ENTRY {option['symbol']} | REAL ORDER DISABLED")
            self._record_event("PAPER_ENTRY", {
                "signal_id": signal_id, "symbol": option["symbol"],
                "quantity": option["lot_size"], "option_ltp": option_ltp,
            }, "orders")
            self._publish_signal_queue()
            return
        threading.Thread(target=self._execute_approved_order,
                         args=(signal_event, option, option_ltp, option_previous_low, resolved["created_at"]),
                         name="order-execution", daemon=True).start()

    def _publish_signal_queue(self):
        with self.coordinator.lock:
            items = [item for item in self.coordinator.active.values() if item]
            items.extend(self.coordinator.pending)
            values = [{
                "underlying": item["signal"].underlying,
                "direction": item["signal"].direction,
                "priority": "PRIMARY" if item["signal"].underlying in {"NIFTY", "SENSEX"} else "SECONDARY",
                "status": item["status"],
                "expires_at": (item["created_at"] + self.coordinator.expiry).isoformat(),
            } for item in items]
        self.display.set_signal_queue(values)

    def _execute_approved_order(self, signal_event, option, option_ltp, option_previous_low, created_at):
        if self.trading_state != SystemState.RUNNING:
            self.display.add_event(f"ORDER BLOCKED: trading state {self.trading_state}")
            return
        if datetime.now(IST) >= created_at + timedelta(seconds=60):
            self.display.add_event("SIGNAL EXPIRED — NO ORDER PLACED")
            return
        option_instrument = self.instruments[signal_event.underlying].__class__(
            signal_event.underlying, option["symbol"], option["token"], option["exchange"],
            2 if option["exchange"] == "NFO" else 4
        )
        current_quote = self.adapter.ltp_snapshot(option_instrument)
        current_ltp = current_quote["ltp"]
        if current_quote["timestamp"] is None:
            self.display.add_event("ORDER BLOCKED: OPTION_LTP_TIMESTAMP_MISSING")
            return
        current_ltp_age = (datetime.now(IST) - current_quote["timestamp"].astimezone(IST)).total_seconds()
        if current_ltp_age > config.STALE_DATA_SECONDS:
            self.display.add_event("ORDER BLOCKED: OPTION_LTP_STALE")
            return
        if not self.health.can_signal(signal_event.underlying):
            self.display.add_event(f"ORDER BLOCKED: {signal_event.underlying} feed stale")
            return
        allowed, reason = order_ip_allowed(self.public_ip, require_config=config.ENABLE_REAL_ORDERS)
        if config.ENABLE_REAL_ORDERS and not allowed:
            self.display.add_event("ORDER BLOCKED — IP NOT WHITELISTED")
            return
        try:
            validate_live_option_contract(option, self.adapter.option_contracts(self.instruments[signal_event.underlying].token))
            trigger, limit = build_stop_loss(option, option_previous_low, current_ltp,
                                              config.SL_BUFFER, config.SL_LIMIT_OFFSET)
        except ValueError as error:
            self.display.add_event(f"RISK/SL VALIDATION FAILED: {error}")
            return
        self.display.add_event("LIVE ORDER ABOUT TO BE SENT")
        self.display.add_event(f"{option['symbol']} QTY:{option['lot_size']} LTP:{current_ltp:.2f}")
        clear, reason = self.order_manager.duplicate_guard(option, self.position_manager)
        if not clear:
            self.display.add_event(f"ORDER BLOCKED: {reason}")
            return
        unresolved_order = bool(self.store.unfinished_order_requests())
        unknown_position = False
        unprotected_position = False
        with self.position_manager.lock:
            for position in self.position_manager.positions.values():
                if position.state == "UNKNOWN":
                    unknown_position = True
                if position.state == "UNPROTECTED_POSITION":
                    unprotected_position = True
        gate_ok, gate_reason = self.safety.allow_buy(
            feed_healthy=self.health.can_signal(signal_event.underlying),
            broker_authenticated=self.display.snapshot()["components"].get("AUTH") == "READY",
            history_ready=self.display.snapshot()["components"].get("HISTORY") == "READY",
            contract_valid=bool(option["symbol"] and option["token"] and option["expiry"]),
            option_ltp_fresh=current_ltp > 0 and current_ltp_age <= config.STALE_DATA_SECONDS,
            risk_valid=config.MAX_RISK_PER_TRADE <= 0 or (current_ltp - trigger) * option["lot_size"] <= config.MAX_RISK_PER_TRADE,
            signal_valid=datetime.now(IST) < created_at + timedelta(seconds=60),
            unresolved_order=unresolved_order,
            unknown_position=unknown_position,
            unprotected_position=unprotected_position,
            database_ready=self.store.is_healthy(),
        )
        if not gate_ok:
            self.display.add_event(f"ORDER BLOCKED BY SAFETY GATE: {gate_reason}")
            self._record_event("BUY_BLOCKED", {"signal_id": signal_event.signal_id, "reason": gate_reason})
            return
        try:
            existing_request = self.store.order_request(signal_event.signal_id)
            if existing_request and existing_request[1] in {"PENDING", "SUBMITTED", "OPEN", "PARTIALLY_FILLED", "UNKNOWN"}:
                self._halt_trading(f"Duplicate or unresolved order request {signal_event.signal_id}")
                return
            reserved = self.store.reserve_order_request(signal_event.signal_id, {
                "signal_id": signal_event.signal_id, "position_id": "", "order_type": "BUY",
                "symbol": option["symbol"], "token": option["token"], "quantity": option["lot_size"],
                "created_at": datetime.now(IST).isoformat(), "state": "PENDING",
            })
            if not reserved:
                self._halt_trading(f"Duplicate or unresolved order request {signal_event.signal_id}")
                return
            order = self.order_manager.place_approved_buy(option, option["lot_size"], request_id=signal_event.signal_id)
            self.store.update_order_request(signal_event.signal_id, "SUBMITTED", order["order_id"])
            self.display.set_orders([f"{order['order_id']} BUY {option['symbol']} QTY:{option['lot_size']} STATUS:SUBMITTED"])
            self._validation_record({
                "event": "REAL_BROKER_RESPONSE", "signal_id": signal_event.signal_id,
                "request_timestamp": order["submitted_at"],
                "response_timestamp": order["broker_response_at"],
                "broker_order_id": order["order_id"], "broker_response": order["broker_response"],
                "data_classification": "REAL BROKER DATA",
            })
            if config.LIVE_BROKER_VALIDATION_ENABLED:
                self.display.add_event("REAL BROKER RESPONSE")
                self.display.add_event("REAL BROKER ORDER ACCEPTED")
        except Exception as error:
            message = str(error)
            event_type = "BUY_UNKNOWN" if "ORDER_STATUS_UNKNOWN" in message else "ORDER_REJECTED"
            self.store.update_order_request(signal_event.signal_id, event_type)
            rejection_details = {"signal_id": signal_event.signal_id, "reason": message}
            if isinstance(error, BrokerOrderRejected):
                rejection_details.update({
                    "broker_order_id": error.order_id,
                    "broker_response": error.response,
                    "symbol": option["symbol"], "token": option["token"],
                    "quantity": option["lot_size"],
                })
            self._record_event(event_type, rejection_details)
            if config.LIVE_BROKER_VALIDATION_ENABLED:
                order_book_status = None
                broker_order_id = getattr(error, "order_id", None)
                if broker_order_id:
                    try:
                        order_book_status = (self.order_manager.order_book_entry(broker_order_id) or {}).get("status")
                    except Exception as reconcile_error:
                        order_book_status = f"RECONCILIATION_UNKNOWN: {reconcile_error}"
                self._validation_record({
                    "event": "REAL_BROKER_ORDER_REJECTED" if event_type == "ORDER_REJECTED" else "REAL_BROKER_ORDER_UNKNOWN",
                    "signal_id": signal_event.signal_id,
                    "request_timestamp": getattr(error, "request_timestamp", None),
                    "response_timestamp": getattr(error, "response_timestamp", datetime.now(IST).isoformat()),
                    "broker_order_id": broker_order_id,
                    "order_book_status": order_book_status,
                    "broker_error_message": message,
                    "broker_response": getattr(error, "response", None),
                    "data_classification": "REAL BROKER DATA",
                })
                if event_type == "ORDER_REJECTED":
                    self.display.add_event("REAL BROKER ORDER REJECTED")
            self.display.add_event(f"BROKER ORDER REJECTED {signal_event.signal_id}: {message}" if event_type == "ORDER_REJECTED" else f"{event_type}: {message}")
            if event_type == "BUY_UNKNOWN":
                self._halt_trading("BUY result unknown; broker reconciliation required")
            return
        self._record_event("BUY_SUBMITTED", {"order_id": order["order_id"], "signal_id": signal_event.signal_id}, "orders")
        self.display.add_event(f"BROKER ACCEPTED ORDER {order['order_id']}")
        self.store.record("orders", order["order_id"], {
            "signal_id": signal_event.signal_id, "trade_id": "", "status": "BROKER_ACCEPTED",
            "created_at": datetime.now(IST).isoformat(),
        })
        self.display.add_event(f"ORDER SUBMITTED: {order['order_id']} | AWAITING FILL")
        position = None
        trade_id = None
        try:
            order_state, fill_values = self.order_manager.wait_for_fill(order["order_id"])
            order_book_entry = self.order_manager.order_book_entry(order["order_id"])
            self._validation_record({
                "event": "REAL_BROKER_ORDER_STATUS", "signal_id": signal_event.signal_id,
                "broker_order_id": order["order_id"], "order_book_status": (order_book_entry or {}).get("status"),
                "filled_quantity": fill_values[1], "average_price": fill_values[0],
                "remaining_quantity": max(0, option["lot_size"] - fill_values[1]),
                "data_classification": "REAL BROKER DATA",
            })
            trade_id = f"T{uuid4().hex[:10].upper()}"
            if order_state == "PARTIALLY_FILLED":
                fill_price, filled_quantity = fill_values
                self.store.update_order_request(signal_event.signal_id, "PARTIALLY_FILLED", order["order_id"])
                self.store.record("orders", order["order_id"], {
                    "signal_id": signal_event.signal_id, "trade_id": trade_id, "status": "PARTIALLY_FILLED",
                    "created_at": datetime.now(IST).isoformat(),
                    "payload": {"filled_quantity": filled_quantity, "remaining_quantity": option["lot_size"] - filled_quantity},
                })
                position = Position(trade_id, "UPSTOX", signal_event.underlying, option["expiry"], option["strike"],
                                    option["option_type"], option["token"], filled_quantity, fill_price,
                                    trigger, order_id=order["order_id"],
                                    symbol=option["symbol"], exchange=option["exchange"],
                                    signal_id=signal_event.signal_id, signal_type=signal_event.signal_type)
                self.display.add_event(f"🟡 PARTIALLY FILLED {filled_quantity} @ {fill_price:.2f}")
                self.position_manager.register_partial_fill(position, order["order_id"], fill_price, filled_quantity)
                self._record_event("BUY_PARTIAL", {"order_id": order["order_id"], "trade_id": trade_id,
                                                    "quantity": filled_quantity, "average_price": fill_price}, "fills")
                self.store.record("positions", trade_id, {
                    "signal_id": signal_event.signal_id, "signal_type": signal_event.signal_type,
                    "underlying": signal_event.underlying, "direction": signal_event.direction,
                    "instrument_key": option["token"], "expiry": option["expiry"], "strike": option["strike"],
                    "quantity": filled_quantity, "entry_price": fill_price,
                    "initial_sl": position.initial_sl, "initial_risk": position.initial_risk,
                    "exit_state": "OPEN", "order_id": order["order_id"], "sl_order_id": "", "state": "PARTIALLY_FILLED",
                    "created_at": datetime.now(IST).isoformat(),
                    "payload": {"symbol": option["symbol"], "token": option["token"]},
                })
                partial_sl = self.order_manager.place_stop_loss(option, filled_quantity, trigger, limit, current_ltp)
                self.order_manager.confirm_order(partial_sl, expected_statuses=("OPEN", "TRIGGER PENDING"))
                self.position_manager.mark_sl(trade_id, partial_sl)
                self._record_event("SL_ACTIVE", {"sl_order_id": partial_sl, "trade_id": trade_id}, "stop_orders")
                self.store.record("stop_losses", partial_sl, {
                    "trade_id": trade_id, "status": "ACTIVE", "created_at": datetime.now(IST).isoformat(),
                    "payload": {"quantity": filled_quantity, "trigger": trigger, "limit": limit},
                })
                self.store.record("positions", trade_id, {
                    "order_id": order["order_id"], "sl_order_id": partial_sl, "state": "SL_ACTIVE",
                    "created_at": datetime.now(IST).isoformat(),
                    "payload": {"symbol": option["symbol"], "token": option["token"]},
                })
                self._halt_trading("Partial BUY fill requires explicit remaining-order reconciliation")
                return
            fill_price, filled_quantity = fill_values
            self.store.update_order_request(signal_event.signal_id, "FILLED", order["order_id"])
            self.store.record("orders", order["order_id"], {
                "signal_id": signal_event.signal_id, "trade_id": trade_id, "status": "FILLED",
                "created_at": datetime.now(IST).isoformat(),
                "payload": {"filled_quantity": filled_quantity, "average_price": fill_price},
            })
            self.display.set_orders([f"{order['order_id']} BUY {option['symbol']} QTY:{option['lot_size']} STATUS:BROKER_ACCEPTED"])
            self.display.set_orders([f"{order['order_id']} BUY {option['symbol']} QTY:{filled_quantity} PRICE:{fill_price:.2f} STATUS:FILLED"])
            position = Position(trade_id, "UPSTOX", signal_event.underlying, option["expiry"], option["strike"],
                                option["option_type"], option["token"], filled_quantity, fill_price,
                                trigger, order_id=order["order_id"],
                                symbol=option["symbol"], exchange=option["exchange"],
                                signal_id=signal_event.signal_id, signal_type=signal_event.signal_type)
            self.position_manager.register_fill(position, order["order_id"], fill_price, filled_quantity)
            self._record_event("BUY_FILLED", {"order_id": order["order_id"], "trade_id": trade_id,
                                               "quantity": filled_quantity, "average_price": fill_price}, "fills")
            self.store.record("positions", trade_id, {
                    "signal_id": signal_event.signal_id, "signal_type": signal_event.signal_type,
                    "underlying": signal_event.underlying, "direction": signal_event.direction,
                    "instrument_key": option["token"], "expiry": option["expiry"], "strike": option["strike"],
                    "quantity": filled_quantity, "entry_price": fill_price,
                    "initial_sl": position.initial_sl, "initial_risk": position.initial_risk,
                    "exit_state": "OPEN", "order_id": order["order_id"], "sl_order_id": "", "state": "OPEN",
                "created_at": datetime.now(IST).isoformat(),
                "payload": {"symbol": option["symbol"], "token": option["token"], "quantity": filled_quantity,
                            "entry_price": fill_price},
            })
            self.display.add_event(f"💰 FILLED {filled_quantity} @ {fill_price:.2f}")
            self.display.set_positions([f"{trade_id} {option['symbol']} QTY:{filled_quantity} ENTRY:{fill_price:.2f} SL:{position.sl_reference:.2f} STATUS:OPEN"])
            self._publish_position_details()
            sl_order_id = self.order_manager.place_stop_loss(option, filled_quantity, trigger, limit, current_ltp)
            self.display.add_event(f"🛡 SL REQUEST SENT {sl_order_id}")
            self.order_manager.confirm_order(sl_order_id, expected_statuses=("OPEN", "TRIGGER PENDING"))
            self.position_manager.mark_sl(trade_id, sl_order_id)
            self._record_event("SL_ACTIVE", {"sl_order_id": sl_order_id, "trade_id": trade_id}, "stop_orders")
            self.store.record("stop_losses", sl_order_id, {
                "trade_id": trade_id, "status": "ACTIVE", "created_at": datetime.now(IST).isoformat(),
                "payload": {"quantity": filled_quantity, "trigger": trigger, "limit": limit},
            })
            self.store.record("positions", trade_id, {
                "signal_id": signal_event.signal_id, "signal_type": signal_event.signal_type,
                "underlying": signal_event.underlying, "direction": signal_event.direction,
                "instrument_key": option["token"], "expiry": option["expiry"], "strike": option["strike"],
                "quantity": filled_quantity, "entry_price": fill_price,
                "initial_sl": position.initial_sl, "initial_risk": position.initial_risk,
                "exit_state": "OPEN", "order_id": order["order_id"], "sl_order_id": sl_order_id, "state": "SL_ACTIVE",
                "created_at": datetime.now(IST).isoformat(),
                "payload": {"symbol": option["symbol"], "token": option["token"], "quantity": filled_quantity,
                            "entry_price": fill_price},
            })
            self.display.add_event(f"🟢 SL ACTIVE {sl_order_id}")
            self.display.set_positions([f"{trade_id} {option['symbol']} QTY:{filled_quantity} ENTRY:{fill_price:.2f} SL:{position.sl_reference:.2f} STATUS:SL_ACTIVE"])
            self._publish_position_details()
            self.display.add_event(f"🛡️ POSITION {trade_id}: SL_ACTIVE fill={fill_price:.2f} SL:{sl_order_id}")
        except Exception as error:
            if position is not None and position.state in {"OPEN", "PARTIALLY_FILLED", "SL_ACTIVE", "UNPROTECTED_POSITION"}:
                self.position_manager.mark_unprotected(trade_id)
                self._halt_trading(f"Unprotected position {trade_id}: {error}")
            else:
                self._halt_trading(f"Entry result unknown for broker order {order['order_id']}: {error}")
            trade_label = trade_id or order["order_id"]
            self.display.add_event(f"🔴 BROKER/SL FAILURE {trade_label}: {error}")
            self.display.add_event(f"🚨 POSITION/ORDER {trade_label} REQUIRES ACTION: {error}")

    def _publish_position_details(self):
        if not self.position_manager:
            return
        with self.position_manager.lock:
            values = []
            for position in self.position_manager.positions.values():
                strategy_exit = position.strategy_exit
                values.append({
                    "trade_id": position.trade_id, "signal_id": position.signal_id,
                    "signal_type": position.signal_type, "index": position.underlying,
                    "direction": "CALL" if position.option_type == "CE" else "PUT",
                    "option": position.symbol, "instrument_key": position.token,
                    "expiry": position.expiry, "strike": position.strike,
                    "quantity": position.quantity, "entry_price": position.entry_price,
                    "initial_sl": position.initial_sl or position.sl_reference,
                    "initial_risk": position.initial_risk,
                    "five_r": strategy_exit.five_r if strategy_exit else None,
                        "current_ltp": (self.display.snapshot().get("option_quotes", {}).get(position.token).ltp
                                if self.display.snapshot().get("option_quotes", {}).get(position.token) else None),
                        "unrealized_pnl": ((self.display.snapshot().get("option_quotes", {}).get(position.token).ltp - position.entry_price) * position.quantity
                            if self.display.snapshot().get("option_quotes", {}).get(position.token) else None),
                        "realized_pnl": position.realized_pnl,
                        "pnl": ((self.display.snapshot().get("option_quotes", {}).get(position.token).ltp - position.entry_price) * position.quantity
                            if self.display.snapshot().get("option_quotes", {}).get(position.token) else position.realized_pnl),
                        "pnl_state": "LIVE" if self.display.snapshot().get("option_quotes", {}).get(position.token) else "LAST KNOWN / STALE",
                    "cci_exit_state": position.cci_exit_state,
                    "five_r_state": position.five_r_state,
                    "protective_sl_state": "ACTIVE" if position.sl_order_id else "PENDING",
                    "position_state": position.state, "exit_reason": position.exit_reason,
                    "fixed_sl": True, "trailing_sl": False,
                })
        self.display.set_position_details(values)

    def _execute_exit(self, trade_id):
        if not self.order_manager or not self.position_manager:
            return
        with self.exit_lock, self.position_manager.lock:
            position = self.position_manager.positions.get(trade_id)
            if not position or position.state in {"CLOSED", "ERROR", "UNKNOWN"}:
                return
            self.position_manager.mark_exit_pending(trade_id)
            quantity = position.quantity
        exit_id = str(uuid4())
        self.store.record("exits", exit_id, {
            "trade_id": trade_id, "status": "REQUESTED", "created_at": datetime.now(IST).isoformat(),
        })
        try:
            if position.sl_order_id:
                self.display.add_event(f"CANCELLING PROTECTIVE SL {trade_id}")
                self.order_manager.cancel_and_confirm(position.sl_order_id)
                self._record_event("SL_CANCEL_CONFIRMED", {
                    "trade_id": trade_id, "sl_order_id": position.sl_order_id,
                }, "stop_orders")
                self.display.add_event(f"SL CANCEL CONFIRMED {trade_id}")
            self._record_event("EXIT_REQUEST_SENT", {"trade_id": trade_id, "quantity": quantity}, "exits")
            order_id = self.order_manager.place_exit(position, quantity)
            self._record_event("EXIT_SUBMITTED", {
                "trade_id": trade_id, "order_id": order_id, "quantity": quantity,
            }, "exits")
            self.display.add_event(f"📤 EXIT ORDER SUBMITTED {trade_id} ORDER:{order_id}")
            self.store.record("orders", order_id, {
                "signal_id": "", "trade_id": trade_id, "status": "SUBMITTED",
                "created_at": datetime.now(IST).isoformat(),
            })
            exit_state, exit_values = self.order_manager.wait_for_fill(order_id)
            if exit_state != "FILLED" or exit_values[1] != quantity:
                self.position_manager.mark_unknown(trade_id)
                self._halt_trading(f"Exit fill incomplete for {trade_id}")
                self._record_event("EXIT_PARTIAL", {
                    "trade_id": trade_id, "order_id": order_id,
                    "quantity": exit_values[1], "requested_quantity": quantity,
                }, "exits")
                return
            position.exit_price = exit_values[0]
            position.exit_timestamp = datetime.now(IST)
            position.realized_pnl = (position.exit_price - position.entry_price) * exit_values[1]
            self.position_manager.mark_closed(trade_id)
            self._publish_position_details()
            self.store.record("exits", exit_id, {
                "trade_id": trade_id, "status": "FILLED", "created_at": datetime.now(IST).isoformat(),
            })
            self.display.add_event(f"✅ EXIT FILLED {trade_id} ORDER:{order_id}")
        except BrokerOrderRejected as error:
            self.position_manager.mark_unknown(trade_id)
            self._halt_trading(f"Exit broker rejection for {trade_id}: {error}")
            self.store.record("exits", exit_id, {
                "trade_id": trade_id, "status": "ORDER_REJECTED", "created_at": datetime.now(IST).isoformat(),
                "payload": {"reason": str(error), "broker_order_id": error.order_id},
            })
            self.display.add_event(f"🔴 BROKER ORDER REJECTED EXIT {trade_id}: {error}")
        except Exception as error:
            self.position_manager.mark_unknown(trade_id)
            self._halt_trading(f"Exit result unknown for {trade_id}: {error}")
            self._record_event("EXIT_UNKNOWN", {"trade_id": trade_id, "reason": str(error)}, "exits")

    def _audit_record(self, signal_event, values):
        indicator_values = self.display.snapshot()["indicators"].get(signal_event.underlying, (None, None))
        breakout_state = self.breakouts[signal_event.underlying]
        return {
            "signal_id": signal_event.signal_id, "signal_type": signal_event.signal_type,
            "instrument": signal_event.underlying,
            "direction": signal_event.direction, "priority": "PRIMARY" if signal_event.underlying in {"NIFTY", "SENSEX"} else "SECONDARY",
            "index_ltp": signal_event.ltp, "running_ohlc": [signal_event.running_candle.open, signal_event.running_candle.high, signal_event.running_candle.low, signal_event.running_candle.close],
            "previous_ohlc": [signal_event.previous_candle.open, signal_event.previous_candle.high, signal_event.previous_candle.low, signal_event.previous_candle.close],
            "prev2_ohlc": ([signal_event.prev2_candle.open, signal_event.prev2_candle.high,
                             signal_event.prev2_candle.low, signal_event.prev2_candle.close]
                            if signal_event.prev2_candle else None),
            "type2_conditions": signal_event.type2_conditions,
            "breakout_condition": "running_high > previous_high" if signal_event.direction == "CALL" else "running_low < previous_low",
            "breakout_result": "TRUE", "breakout_reference": signal_event.previous_candle.high if signal_event.direction == "CALL" else signal_event.previous_candle.low,
            "breakout_value": signal_event.running_candle.high if signal_event.direction == "CALL" else signal_event.running_candle.low,
            "first_break_side": signal_event.first_break_side,
            "first_break_time": signal_event.first_break_time,
            "first_break_price": signal_event.first_break_price,
            "second_break_side": "HIGH" if signal_event.direction == "CALL" else "LOW",
            "second_break_time": signal_event.second_break_time,
            "second_break_price": signal_event.breakout_price,
            "candle_colour_at_second_break": signal_event.candle_colour,
            "call_fired": breakout_state.call_fired,
            "put_fired": breakout_state.put_fired,
            "cci": indicator_values[0], "rsi": indicator_values[1],
            "rsi_filter_status": signal_event.rsi_filter_status,
            "rsi_matching_periods": signal_event.rsi_matching_periods,
            "rsi_evaluated_periods": [timestamp.isoformat() for timestamp in signal_event.rsi_evaluated_periods],
            "rsi_evaluated_values": signal_event.rsi_evaluated_values,
            "rsi_evaluated_sma_values": signal_event.rsi_evaluated_sma_values,
            "rsi_first_matching_timestamp": signal_event.rsi_first_matching_timestamp,
            "rsi_reason": signal_event.rsi_reason,
            **values,
        }

    def _validation_record(self, values):
        if not config.LIVE_BROKER_VALIDATION_ENABLED:
            return
        self.live_validation_report.record(values)
        self._record_event(values.get("event", "LIVE_VALIDATION"), values, "system_events")

    def _reconcile_positions(self):
        try:
            self.position_manager.restore(self.store.load_positions())
            result = self.position_manager.reconcile()
            if result["unknown_external"]:
                self._record_event("UNKNOWN_EXTERNAL_POSITION", {"tokens": list(result["unknown_external"])})
                self._halt_trading("Unknown external broker position")
            if result["missing_local"]:
                self._record_event("BROKER_MISMATCH", {"tokens": list(result["missing_local"])})
            for trade_id in result.get("externally_closed", set()):
                self._record_event("EXTERNAL_MANUAL_EXIT", {"trade_id": trade_id}, "position_events")
                self.display.add_event(f"EXTERNAL MANUAL EXIT {trade_id}")
            self._on_status("BROKER POSITIONS RECONCILED")
        except Exception as error:
            self._halt_trading(f"Broker reconciliation failed: {error}")
            self._on_status(f"BROKER RECONCILIATION FAILED: {error}")

    def _reconcile_order_requests(self):
        unfinished = self.store.unfinished_order_requests()
        if not unfinished:
            return
        try:
            broker_orders = self.order_manager.order_book()
        except Exception as error:
            self._halt_trading(f"Order reconciliation failed: {error}")
            self._record_event("UNKNOWN_ORDER", {"reason": str(error), "requests": unfinished})
            return
        by_id = {str(order.get("order_id")): order for order in broker_orders}
        unresolved = []
        for request_id, signal_id, state, broker_order_id in unfinished:
            order = by_id.get(str(broker_order_id)) if broker_order_id else None
            if order is None:
                unresolved.append(request_id)
                continue
            status = str(order.get("status", "UNKNOWN")).upper()
            mapped = {"COMPLETE": "FILLED", "REJECTED": "ORDER_REJECTED", "CANCELLED": "CANCELLED"}.get(status, "UNKNOWN")
            self.store.update_order_request(request_id, mapped, broker_order_id)
            if mapped == "UNKNOWN":
                unresolved.append(request_id)
        if unresolved:
            self._halt_trading(f"Unknown broker order state for {len(unresolved)} request(s)")
            self._record_event("UNKNOWN_ORDER", {"requests": unresolved})

    @staticmethod
    def _is_market_open(timestamp):
        if timestamp.tzinfo is None or timestamp.weekday() >= 5:
            return False
        current = timestamp.astimezone(IST).time()
        market_open = datetime.strptime("%02d:%02d" % config.MARKET_OPEN, "%H:%M").time()
        market_close = datetime.strptime("%02d:%02d" % config.MARKET_CLOSE, "%H:%M").time()
        return market_open <= current < market_close


if __name__ == "__main__":
    print("[BOOT] main() ENTERED", flush=True)
    service = None
    exit_code = 0
    try:
        service = MarketDataService()
        def request_shutdown(signum, _frame):
            source = "USER INTERRUPT" if signum == signal.SIGINT else f"SIGNAL {signum}"
            service.stop_reason = source
            service._lifecycle(f"[SERVICE] STOP REQUESTED source={source}")
            service.stop()

        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)
        service.start()
        if service and not service.stop_event.is_set():
            print("[CRITICAL] MAIN RETURNED UNEXPECTEDLY", flush=True)
    except AuthenticationStartupBlocked as error:
        log_path = config.ROOT / "logs" / "application.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"AUTHENTICATION STARTUP BLOCKED: {error.classification}\n")
        print(f"[AUTH] {error.classification}", flush=True)
        print("[AUTH] AUTHENTICATION FAILED", flush=True)
        print("[AUTH] STARTUP BLOCKED", flush=True)
        print("", flush=True)
        print("RKL UPSTOX - STARTUP BLOCKED", flush=True)
        print(f"REASON:\nUPSTOX ACCESS TOKEN {error.classification.replace('TOKEN ', '').replace('_', ' ')}", flush=True)
        print("ACTION REQUIRED:\nUPDATE UPSTOX_ACCESS_TOKEN WITH A NEW VALID TOKEN", flush=True)
        print("TRADING:\nNOT STARTED\n\nORDERS:\nDISABLED", flush=True)
        exit_code = 2
    except Exception as error:
        error_path = config.ROOT / "logs" / "startup_crash.log"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"[CRITICAL] UNHANDLED STARTUP EXCEPTION: {type(error).__name__}: {error}", flush=True)
        print(f"[STARTUP] TRACEBACK SAVED: {error_path}", flush=True)
        exit_code = 1
    finally:
        if service:
            service.stop()
    if exit_code:
        raise SystemExit(exit_code)
