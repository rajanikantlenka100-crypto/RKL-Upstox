"""Official Upstox REST and V3 streaming adapter."""

import json
import math
import threading
import urllib.error
import urllib.parse
import urllib.request
import time
from datetime import datetime, timedelta
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

import config
from instruments.resolver import Instrument
from market_data.models import MarketTick

IST = ZoneInfo("Asia/Kolkata")


class UpstoxClient:
    def __init__(self, access_token, api_base=None, order_base=None, telemetry=None):
        self.access_token = access_token
        self.api_base = (api_base or config.UPSTOX_API_BASE).rstrip("/")
        self.order_base = (order_base or config.UPSTOX_ORDER_BASE).rstrip("/")
        self.telemetry = telemetry

    def request(self, method, url, payload=None, form=False, headers=None):
        started = time.perf_counter()
        body = None
        request_headers = {"Accept": "application/json", "User-Agent": "RKL-Upstox/1.0"}
        if self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"
        if headers:
            request_headers.update(headers)
        if payload is not None:
            if form:
                body = urllib.parse.urlencode(payload).encode()
                request_headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(payload).encode()
                request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=config.UPSTOX_REQUEST_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8"))
                if self.telemetry:
                    self.telemetry("API_RESPONSE", {"method": method, "url": url, "latency_ms": round((time.perf_counter() - started) * 1000, 3), "success": True})
                return result
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            if self.telemetry:
                self.telemetry("API_ERROR", {"method": method, "url": url, "latency_ms": round((time.perf_counter() - started) * 1000, 3), "error": str(error)})
            raise RuntimeError(f"Upstox HTTP {error.code}: {details[:500]}") from error
        except Exception as error:
            if self.telemetry:
                self.telemetry("API_ERROR", {"method": method, "url": url, "latency_ms": round((time.perf_counter() - started) * 1000, 3), "error": str(error)})
            raise

    def place_order(self, params):
        payload = {
            "quantity": int(params["quantity"]), "product": params.get("product", "I"), "validity": "DAY",
            "price": float(params.get("price", 0)), "tag": params.get("tag", "rkl-upstox"),
            "instrument_token": params["instrument_token"], "order_type": params.get("order_type", "MARKET"),
            "transaction_type": params["transaction_type"], "disclosed_quantity": 0,
            "trigger_price": float(params.get("trigger_price", 0)), "is_amo": False,
            "slice": bool(params.get("slice", False)), "market_protection": -1,
        }
        response = self.request("POST", f"{self.order_base}/v3/order/place", payload)
        ids = (response.get("data") or {}).get("order_ids") or []
        return {"status": response.get("status") == "success", "message": response.get("errors"),
                "data": {"order_id": ids[0]} if ids else None, "raw": response}

    def position(self):
        response = self.request("GET", f"{self.api_base}/v2/portfolio/short-term-positions")
        rows = response.get("data") or []
        return {"status": response.get("status") == "success", "data": [
            {"instrument_token": row.get("instrument_token"), "quantity": row.get("quantity", 0),
             "trading_symbol": row.get("trading_symbol"), "exchange": row.get("exchange")}
            for row in rows], "raw": response}

    def user_profile(self):
        return self.request("GET", f"{self.api_base}/v2/user/profile")

    def orderBook(self):
        response = self.request("GET", f"{self.api_base}/v2/order/retrieve-all")
        rows = response.get("data") or []
        return {"status": response.get("status") == "success", "data": [self._normalize_order(row) for row in rows], "raw": response}

    def order_details(self, order_id):
        response = self.request("GET", f"{self.api_base}/v2/order/details?order_id={urllib.parse.quote(str(order_id))}")
        row = response.get("data") or {}
        return {"status": response.get("status") == "success", "data": self._normalize_order(row), "raw": response}

    def order_history(self, order_id):
        response = self.request("GET", f"{self.api_base}/v2/order/history?order_id={urllib.parse.quote(str(order_id))}")
        return {"status": response.get("status") == "success", "data": [self._normalize_order(row) for row in response.get("data") or []], "raw": response}

    def order_trades(self, order_id):
        response = self.request("GET", f"{self.api_base}/v2/order/trades?order_id={urllib.parse.quote(str(order_id))}")
        return {"status": response.get("status") == "success", "data": response.get("data") or [], "raw": response}

    def cancelOrder(self, variety, order_id):
        response = self.request("DELETE", f"{self.api_base}/v2/order/cancel?order_id={urllib.parse.quote(str(order_id))}")
        return {"status": response.get("status") == "success", "data": response.get("data"), "raw": response}

    def option_contracts(self, underlying_key, expiry_date=None):
        query = {"instrument_key": underlying_key}
        if expiry_date:
            query["expiry_date"] = expiry_date
        url = f"{self.api_base}/v2/option/contract?{urllib.parse.urlencode(query)}"
        response = self.request("GET", url)
        if response.get("status") != "success":
            raise RuntimeError(f"Upstox option contract request failed: {response}")
        return response.get("data") or []

    def intraday_candles(self, instrument_key, unit="minutes", interval=5):
        encoded = urllib.parse.quote(instrument_key, safe="")
        url = f"{self.api_base}/v3/historical-candle/intraday/{encoded}/{unit}/{interval}"
        response = self.request("GET", url)
        return (response.get("data") or {}).get("candles") or []

    def registered_static_ips(self):
        return self.request("GET", f"{self.api_base}/v2/user/ip")

    @staticmethod
    def _normalize_order(row):
        status = str(row.get("status", "")).upper().replace(" ", "_")
        return {"order_id": row.get("order_id"), "status": status, "instrument_token": row.get("instrument_token"),
                "filled_quantity": row.get("filled_quantity", 0), "average_price": row.get("average_price", 0),
                "quantity": row.get("quantity", 0), "pending_quantity": row.get("pending_quantity", 0),
                "status_message": row.get("status_message"), "raw": row}


class UpstoxAdapter:
    def __init__(self, on_tick: Callable[[MarketTick], None], on_status: Callable[[str], None], on_raw_event=None, on_portfolio_event=None, telemetry=None):
        self.on_tick = on_tick
        self.on_status = on_status
        self.on_raw_event = on_raw_event or (lambda event: None)
        self.on_portfolio_event = on_portfolio_event or (lambda event: None)
        self.telemetry = telemetry
        self.client = None
        self.order_client = None
        self.instruments: dict[str, Instrument] = {}
        self._stop = threading.Event()
        self._thread = None
        self._streamer = None
        self._portfolio_streamer = None
        self._poll_fallback_started = False
        self._fallback_lock = threading.Lock()
        self._token_to_instrument = {}
        self._option_instruments = {}
        self._sequence = 0
        self._last_cumulative_volume = {}

    def authenticate(self):
        config.require_credentials()
        self.on_status("AUTHENTICATING")
        access_token = config.UPSTOX_ACCESS_TOKEN
        if not access_token:
            response = UpstoxClient("", telemetry=self.telemetry).request("POST", f"{config.UPSTOX_API_BASE}/v2/login/authorization/token", {
                "code": config.UPSTOX_AUTH_CODE, "client_id": config.UPSTOX_CLIENT_ID,
                "client_secret": config.UPSTOX_CLIENT_SECRET, "redirect_uri": config.UPSTOX_REDIRECT_URI,
                "grant_type": "authorization_code",
            }, form=True)
            access_token = response.get("access_token", "")
        if not access_token:
            self.on_status("AUTHENTICATION FAILED")
            raise RuntimeError("Upstox did not return an access_token")
        self.client = UpstoxClient(access_token, telemetry=self.telemetry)
        self.order_client = (
            UpstoxClient(config.SANDBOX_ACCESS_TOKEN, config.SANDBOX_API_BASE, config.SANDBOX_API_BASE, telemetry=self.telemetry)
            if config.ORDER_ENV == "sandbox" else self.client
        )
        self.on_status("ACCESS TOKEN PRESENT")
        self.on_status("CREDENTIAL LOADED")

    def validate_token(self):
        if not self.client:
            raise RuntimeError("TOKEN NOT LOADED")
        try:
            response = self.client.user_profile()
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                return "TOKEN EXPIRED" if error.code == 401 else "TOKEN REJECTED"
            return f"UPSTOX API ERROR ({error.code})"
        except urllib.error.URLError as error:
            return f"NETWORK ERROR: {error.reason}"
        except Exception as error:
            message = str(error)
            if "HTTP 401" in message:
                return "TOKEN EXPIRED"
            if "HTTP 403" in message:
                return "TOKEN REJECTED"
            return f"UNKNOWN: {message}"
        if not isinstance(response, dict) or response.get("status") not in {None, "success"}:
            return "UPSTOX API ERROR"
        return "TOKEN VALID"

    def set_instruments(self, instruments: dict[str, Instrument]):
        self.instruments = instruments
        self._token_to_instrument = {instrument.token: instrument for instrument in instruments.values()}

    def set_option_instruments(self, instruments):
        self._option_instruments = {instrument.token: instrument for instrument in instruments}
        self._token_to_instrument.update(self._option_instruments)

    def start(self):
        if not self.client or not self.instruments:
            raise RuntimeError("Authenticate and resolve instruments before starting the feed")
        self._stop.clear()
        if config.MARKET_DATA_MODE == "websocket" and config.WEBSOCKET_ENABLED:
            self._thread = threading.Thread(target=self._websocket_loop, name="upstox-market-v3", daemon=True)
        else:
            self._thread = threading.Thread(target=self._poll_loop, name="upstox-market-poll", daemon=True)
        self._thread.start()

    def start_portfolio_stream(self):
        if not self.client:
            raise RuntimeError("Authenticate before starting the Upstox portfolio stream")
        thread = threading.Thread(target=self._portfolio_loop, name="upstox-portfolio-stream", daemon=True)
        thread.start()

    def stop(self):
        self._stop.set()
        if self._streamer:
            try:
                self._streamer.disconnect()
            except Exception as error:
                self.on_status(f"UPSTOX FEED STOP ERROR: {error}")
        if self._portfolio_streamer:
            try:
                self._portfolio_streamer.disconnect()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _start_polling_fallback(self):
        with self._fallback_lock:
            if self._poll_fallback_started or self._stop.is_set():
                return
            self._poll_fallback_started = True
            self._thread = threading.Thread(target=self._poll_loop, name="upstox-market-poll-fallback", daemon=True)
            self._thread.start()
        self.on_status("UPSTOX FEED FALLBACK: REST POLLING")

    def fetch_historical(self, instrument: Instrument, count=50):
        end = datetime.now(IST).date()
        start = end - timedelta(days=config.HISTORICAL_LOOKBACK_DAYS)
        encoded = urllib.parse.quote(instrument.token, safe="")
        url = f"{config.UPSTOX_API_BASE}/v3/historical-candle/{encoded}/minutes/5/{end.isoformat()}/{start.isoformat()}"
        response = self.client.request("GET", url)
        return self._normalize_candles((response.get("data") or {}).get("candles") or [], count)

    def fetch_intraday(self, instrument: Instrument, count=50):
        return self._normalize_candles(self.client.intraday_candles(instrument.token, "minutes", 5), count)

    def option_contracts(self, underlying_key, expiry_date=None):
        return self.client.option_contracts(underlying_key, expiry_date)

    def ltp(self, instrument: Instrument):
        return self.ltp_snapshot(instrument)["ltp"]

    def ltp_snapshot(self, instrument: Instrument):
        query = urllib.parse.urlencode({"instrument_key": instrument.token})
        response = self.client.request("GET", f"{config.UPSTOX_API_BASE}/v3/market-quote/ltp?{query}")
        row = next(iter((response.get("data") or {}).values()), {})
        value = row.get("last_price")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise RuntimeError(f"OPTION_LTP_INVALID: {instrument.token}") from None
        if value <= 0:
            raise RuntimeError(f"OPTION_LTP_ZERO: {instrument.token}")
        timestamp = row.get("timestamp") or row.get("ltt") or row.get("last_trade_time")
        parsed_timestamp = self._timestamp(timestamp) if timestamp is not None else None
        return {"ltp": value, "timestamp": parsed_timestamp, "instrument_key": instrument.token}

    def _websocket_loop(self):
        try:
            import upstox_client
        except ImportError as error:
            self.on_status(f"UPSTOX FEED ERROR: official SDK missing: {error}")
            self._start_polling_fallback()
            return
        try:
            configuration = upstox_client.Configuration()
            configuration.access_token = self.client.access_token
            self._streamer = upstox_client.MarketDataStreamerV3(
                upstox_client.ApiClient(configuration), list(self._token_to_instrument), config.WEBSOCKET_MODE)
            self._streamer.on("open", lambda *args: self.on_status("UPSTOX FEED CONNECTED"))
            self._streamer.on("message", self._on_stream_message)
            self._streamer.on("error", lambda error: self.on_status(f"UPSTOX FEED ERROR: {error}"))
            self._streamer.on("close", lambda *args: self.on_status("UPSTOX FEED DISCONNECTED"))
            self._streamer.on("reconnecting", lambda message: self.on_status(f"UPSTOX FEED RECONNECTING: {message}"))
            self._streamer.auto_reconnect(True, config.WEBSOCKET_RECONNECT_SECONDS, config.WEBSOCKET_RECONNECT_ATTEMPTS)
            self._streamer.connect()
        except Exception as error:
            self.on_status(f"UPSTOX FEED ERROR: {error}")
            self._start_polling_fallback()

    def _on_stream_message(self, message):
        received = datetime.now(IST)
        payload = self._as_dict(message)
        feeds = payload.get("feeds") if isinstance(payload, dict) else None
        if not isinstance(feeds, dict):
            self.on_raw_event({"event_id": str(uuid4()), "source": "UPSTOX_WEBSOCKET_V3", "received_timestamp": received.isoformat(), "payload": payload})
            return
        for token, feed in feeds.items():
            instrument = self._token_to_instrument.get(token)
            if not instrument:
                self.on_raw_event({"event_id": str(uuid4()), "instrument_key": token, "source": "UPSTOX_WEBSOCKET_V3",
                                   "received_timestamp": received.isoformat(), "payload": payload, "error": "UNKNOWN_INSTRUMENT"})
                continue
            ltpc = self._find_mapping(feed, "ltpc") or {}
            raw_ltp = ltpc.get("ltp")
            if raw_ltp is None:
                self.on_raw_event({"event_id": str(uuid4()), "instrument_key": token, "exchange": instrument.exchange,
                                   "source": "UPSTOX_WEBSOCKET_V3", "received_timestamp": received.isoformat(),
                                   "payload": payload, "error": "MISSING_LTP"})
                continue
            try:
                ltp = float(raw_ltp)
            except (TypeError, ValueError):
                self.on_raw_event({"event_id": str(uuid4()), "instrument_key": token,
                                   "exchange": instrument.exchange, "source": "UPSTOX_WEBSOCKET_V3",
                                   "received_timestamp": received.isoformat(), "payload": payload,
                                   "error": "INVALID_LTP"})
                continue
            if not math.isfinite(ltp) or ltp <= 0:
                self.on_raw_event({"event_id": str(uuid4()), "instrument_key": token,
                                   "exchange": instrument.exchange, "source": "UPSTOX_WEBSOCKET_V3",
                                   "received_timestamp": received.isoformat(), "payload": payload,
                                   "error": "INVALID_LTP"})
                continue
            raw_timestamp = ltpc.get("ltt") or payload.get("currentTs")
            exchange_timestamp = self._timestamp(raw_timestamp)
            if exchange_timestamp is None:
                self.on_raw_event({"event_id": str(uuid4()), "instrument_key": token, "exchange": instrument.exchange,
                                   "source": "UPSTOX_WEBSOCKET_V3", "received_timestamp": received.isoformat(),
                                   "payload": payload, "error": "MISSING_EXCHANGE_TIMESTAMP" if raw_timestamp is None else "INVALID_TIMESTAMP"})
                self.on_status(f"UPSTOX FEED ERROR: missing exchange timestamp for {token}")
                continue
            cumulative_volume = self._find_number_any(feed, ("volume", "vtt", "volumeTradeForTheDay"))
            try:
                volume = self._volume_delta(token, cumulative_volume)
            except (TypeError, ValueError, OverflowError):
                self.on_raw_event({"event_id": str(uuid4()), "instrument_key": token,
                                   "exchange": instrument.exchange, "source": "UPSTOX_WEBSOCKET_V3",
                                   "received_timestamp": received.isoformat(), "payload": payload,
                                   "error": "INVALID_VOLUME"})
                continue
            self._sequence += 1
            event_id = str(uuid4())
            raw = {"event_id": event_id, "instrument_key": token, "exchange": instrument.exchange,
                   "exchange_timestamp": exchange_timestamp.isoformat(), "received_timestamp": received.isoformat(),
                   "ltp": ltp, "volume": volume, "source": "UPSTOX_WEBSOCKET_V3",
                   "sequence": self._sequence, "payload": payload}
            self.on_raw_event(raw)
            self.on_tick(MarketTick(instrument=instrument.name, token=token, exchange=instrument.exchange,
                                    timestamp=exchange_timestamp, ltp=ltp, volume=volume,
                                    source="UPSTOX_WEBSOCKET_V3", exchange_timestamp=exchange_timestamp,
                                    received_timestamp=received, sequence=self._sequence, raw_event_id=event_id))

    def _poll_loop(self):
        import time
        self.on_status("UPSTOX FEED CONNECTED (POLLING FALLBACK)")
        while not self._stop.wait(config.UPSTOX_POLL_SECONDS):
            for instrument in self.instruments.values():
                try:
                    received = datetime.now(IST)
                    tick = MarketTick(instrument=instrument.name, token=instrument.token, exchange=instrument.exchange,
                                      timestamp=received, ltp=self.ltp(instrument), volume=0,
                                      source="UPSTOX_REST_POLL", received_timestamp=received)
                    self.on_tick(tick)
                except Exception as error:
                    self.on_status(f"UPSTOX FEED ERROR: {error}")
        self.on_status("UPSTOX FEED DISCONNECTED")

    def _portfolio_loop(self):
        try:
            import upstox_client
            configuration = upstox_client.Configuration()
            configuration.access_token = self.client.access_token
            self._portfolio_streamer = upstox_client.PortfolioDataStreamer(
                upstox_client.ApiClient(configuration), order_update=True, position_update=True)
            self._portfolio_streamer.on("open", lambda *args: self.on_status("UPSTOX PORTFOLIO CONNECTED"))
            self._portfolio_streamer.on("message", lambda message: self.on_portfolio_event(self._as_dict(message)))
            self._portfolio_streamer.on("error", lambda error: self.on_status(f"UPSTOX PORTFOLIO ERROR: {error}"))
            self._portfolio_streamer.on("close", lambda *args: self.on_status("UPSTOX PORTFOLIO DISCONNECTED"))
            self._portfolio_streamer.auto_reconnect(True, config.WEBSOCKET_RECONNECT_SECONDS, config.WEBSOCKET_RECONNECT_ATTEMPTS)
            self._portfolio_streamer.connect()
        except ImportError as error:
            self.on_status(f"UPSTOX PORTFOLIO ERROR: official SDK missing: {error}")
        except Exception as error:
            self.on_status(f"UPSTOX PORTFOLIO ERROR: {error}")

    @staticmethod
    def _as_dict(message):
        if isinstance(message, dict):
            return message
        for method in ("to_dict", "to_dict_recursive"):
            converter = getattr(message, method, None)
            if converter:
                value = converter()
                if isinstance(value, dict):
                    return value
        if isinstance(message, (bytes, bytearray)):
            return {"raw_bytes": bytes(message).hex()}
        return {"message": str(message)}

    @staticmethod
    def _find_mapping(value, key):
        if isinstance(value, dict):
            if key in value and isinstance(value[key], dict):
                return value[key]
            for child in value.values():
                result = UpstoxAdapter._find_mapping(child, key)
                if result is not None:
                    return result
        elif isinstance(value, list):
            for child in value:
                result = UpstoxAdapter._find_mapping(child, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _find_number(value, key):
        mapping = UpstoxAdapter._find_mapping(value, key)
        if mapping is not None:
            return None
        if isinstance(value, dict):
            if key in value and isinstance(value[key], (int, float)):
                return float(value[key])
            for child in value.values():
                result = UpstoxAdapter._find_number(child, key)
                if result is not None:
                    return result
        elif isinstance(value, list):
            for child in value:
                result = UpstoxAdapter._find_number(child, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _find_number_any(value, keys):
        for key in keys:
            result = UpstoxAdapter._find_number(value, key)
            if result is not None:
                return result
        return None

    def _volume_delta(self, token, cumulative):
        if cumulative is None:
            return 0
        previous = self._last_cumulative_volume.get(token)
        self._last_cumulative_volume[token] = cumulative
        return max(0, int(cumulative - previous)) if previous is not None else 0

    @staticmethod
    def _timestamp(value):
        if value is None:
            return None
        try:
            numeric = float(value)
            return datetime.fromtimestamp(numeric / 1000, tz=IST)
        except (TypeError, ValueError, OSError):
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)
            except ValueError:
                return None

    @staticmethod
    def _normalize_candles(candles, count):
        normalized = []
        for row in candles:
            if len(row) < 6:
                continue
            normalized.append([row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4]), int(row[5] or 0)])
        return sorted(normalized, key=lambda row: row[0])[-count:]
