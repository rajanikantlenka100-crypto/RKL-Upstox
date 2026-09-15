"""Environment-backed configuration for the Upstox signal service."""

import ipaddress
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
env_path = ROOT / ".env"
if env_path.exists():
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

UPSTOX_CLIENT_ID = os.getenv("UPSTOX_CLIENT_ID", "").strip()
UPSTOX_CLIENT_SECRET = os.getenv("UPSTOX_CLIENT_SECRET", "").strip()
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1:8766/callback").strip()
UPSTOX_ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
UPSTOX_AUTH_CODE = os.getenv("UPSTOX_AUTH_CODE", "").strip()
UPSTOX_API_BASE = os.getenv("UPSTOX_API_BASE", "https://api.upstox.com").rstrip("/")
UPSTOX_ORDER_BASE = os.getenv("UPSTOX_ORDER_BASE", "https://api-hft.upstox.com").rstrip("/")
SANDBOX_API_BASE = os.getenv("SANDBOX_API_BASE", "https://sandbox.upstox.com").rstrip("/")
SANDBOX_ACCESS_TOKEN = os.getenv("SANDBOX_ACCESS_TOKEN", "").strip()
ORDER_ENV = os.getenv("ORDER_ENV", "live").strip().lower()
MARKET_DATA_MODE = os.getenv("MARKET_DATA_MODE", "websocket").strip().lower()
_RAW_EXECUTION_MODE = os.getenv("EXECUTION_MODE", "").strip().upper()
_LEGACY_MODE = os.getenv("TRADING_MODE", "READ_ONLY").strip().upper()
_MODE_ALIASES = {"LIVE": "PRODUCTION", "AUTOMATIC": "READ_ONLY", "MANUAL": "READ_ONLY"}
EXECUTION_MODE = _RAW_EXECUTION_MODE or _MODE_ALIASES.get(_LEGACY_MODE, _LEGACY_MODE)
TRADING_MODE = EXECUTION_MODE
AUTO_TRADING_ENABLED = os.getenv("AUTO_TRADING_ENABLED", "OFF").strip().upper() == "ON"
AUTO_ENTRY_ENABLED = os.getenv("AUTO_ENTRY_ENABLED", "ON").strip().upper() == "ON"
SIGNAL_TYPE_1_ENABLED = os.getenv("SIGNAL_TYPE_1_ENABLED", "ON").strip().upper() == "ON"
SIGNAL_TYPE_2_ENABLED = os.getenv("SIGNAL_TYPE_2_ENABLED", "ON").strip().upper() == "ON"
MANUAL_APPROVAL_ENABLED = os.getenv("MANUAL_APPROVAL_ENABLED", "ON").strip().upper() == "ON"
WEBSOCKET_ENABLED = os.getenv("WEBSOCKET_ENABLED", "ON").strip().upper() == "ON"
HISTORICAL_SYNC_ENABLED = os.getenv("HISTORICAL_SYNC_ENABLED", "ON").strip().upper() == "ON"
UPSTOX_POLL_SECONDS = float(os.getenv("UPSTOX_POLL_SECONDS", "1.0"))
UPSTOX_REQUEST_TIMEOUT_SECONDS = float(os.getenv("UPSTOX_REQUEST_TIMEOUT_SECONDS", "15"))
WEBSOCKET_RECONNECT_SECONDS = int(os.getenv("WEBSOCKET_RECONNECT_SECONDS", "10"))
WEBSOCKET_RECONNECT_ATTEMPTS = int(os.getenv("WEBSOCKET_RECONNECT_ATTEMPTS", "20"))
WEBSOCKET_MODE = os.getenv("WEBSOCKET_MODE", "full").strip().lower()
INSTRUMENT_MASTER_URL = os.getenv("INSTRUMENT_MASTER_URL", "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz").strip()
INSTRUMENT_MASTER_PATH = Path(os.getenv("INSTRUMENT_MASTER_PATH", str(ROOT / "instrument_master.json")))
_DATABASE_OVERRIDE = os.getenv("DATABASE_PATH", "").strip()
_MODE_DATABASES = {
    "READ_ONLY": ROOT / "data" / "readonly.sqlite3",
    "BACKTEST": ROOT / "data" / "backtest.sqlite3",
    "SANDBOX": ROOT / "data" / "sandbox.sqlite3",
    "PRODUCTION": ROOT / "data" / "production.sqlite3",
}
DATABASE_PATH = Path(_DATABASE_OVERRIDE) if _DATABASE_OVERRIDE else _MODE_DATABASES.get(
    EXECUTION_MODE, ROOT / "data" / "readonly.sqlite3"
)
TIMEFRAME_MINUTES = int(os.getenv("TIMEFRAME_MINUTES", "5"))


def _market_time(name, default):
    value = os.getenv(name, default).strip()
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return hour, minute
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{name} must use HH:MM format") from error


MARKET_OPEN = _market_time("MARKET_OPEN", "09:15")
MARKET_CLOSE = _market_time("MARKET_CLOSE", "15:30")
ACTIVE_INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY")
INSTRUMENTS = tuple(item.strip().upper() for item in os.getenv("INSTRUMENTS", ",".join(ACTIVE_INDEXES)).split(",") if item.strip())
INDEX_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank", "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT", "SENSEX": "BSE_INDEX|SENSEX"}
INDEX_EXCHANGES = {"NIFTY": "NSE_INDEX", "BANKNIFTY": "NSE_INDEX", "FINNIFTY": "NSE_INDEX", "MIDCPNIFTY": "NSE_INDEX", "SENSEX": "BSE_INDEX"}
STRIKE_INTERVALS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25, "SENSEX": 100}
CCI_PERIOD = int(os.getenv("CCI_PERIOD", "5"))
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_SMA_PERIOD = int(os.getenv("RSI_SMA_PERIOD", "5"))
RSI_LOOKBACK_PERIODS = int(os.getenv("RSI_LOOKBACK_PERIODS", "5"))
SL_BUFFER = float(os.getenv("SL_BUFFER", "1.0"))
LOT_COUNT = int(os.getenv("LOT_COUNT", "1"))
REST_SYNC_INTERVAL_SECONDS = int(os.getenv("REST_SYNC_INTERVAL_SECONDS", "7200"))
HISTORICAL_LOOKBACK_DAYS = int(os.getenv("HISTORICAL_LOOKBACK_DAYS", "10"))
HISTORICAL_COUNT = int(os.getenv("HISTORICAL_COUNT", "100"))
INTRADAY_RECONCILIATION_ENABLED = os.getenv("INTRADAY_RECONCILIATION_ENABLED", "ON").strip().upper() == "ON"
REAL_ORDERS_ENABLED = os.getenv("REAL_ORDERS_ENABLED", "OFF").strip().upper()
if REAL_ORDERS_ENABLED not in {"ON", "OFF"}:
    raise RuntimeError("REAL_ORDERS_ENABLED must be ON or OFF")
ENABLE_REAL_ORDERS = REAL_ORDERS_ENABLED == "ON"
LIVE_BROKER_VALIDATION = os.getenv("LIVE_BROKER_VALIDATION", "OFF").strip().upper()
if LIVE_BROKER_VALIDATION not in {"ON", "OFF"}:
    raise RuntimeError("LIVE_BROKER_VALIDATION must be ON or OFF")
LIVE_BROKER_VALIDATION_ENABLED = LIVE_BROKER_VALIDATION == "ON"
ORDER_IP_WHITELIST = os.getenv("UPSTOX_ORDER_IP", "").strip()
SL_MIN_TICK_DISTANCE = int(os.getenv("SL_MIN_TICK_DISTANCE", "2"))
SL_LIMIT_OFFSET = float(os.getenv("SL_LIMIT_OFFSET", "2.0"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "0"))
STALE_DATA_SECONDS = int(os.getenv("STALE_DATA_SECONDS", "15"))
DISPLAY_REFRESH_SECONDS = float(os.getenv("DISPLAY_REFRESH_SECONDS", "1.0"))
SIGNAL_TRACE_ENABLED = os.getenv("SIGNAL_TRACE_ENABLED", "ON").strip().upper() == "ON"
SIGNAL_TRACE_PATH = Path(os.getenv("SIGNAL_TRACE_PATH", str(ROOT / "logs" / "signal_candidate_trace.jsonl")))
SIGNAL_AUDIT_PATH = Path(os.getenv("SIGNAL_AUDIT_PATH", str(ROOT / "logs" / "signal_audit.jsonl")))
LIVE_VALIDATION_PATH = Path(os.getenv("LIVE_VALIDATION_PATH", str(ROOT / "logs" / "live_broker_validation.jsonl")))
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip()
DASHBOARD_HEALTH_HOST = os.getenv("DASHBOARD_HEALTH_HOST", "127.0.0.1").strip()
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8765"))
MOBILE_API_TOKEN = os.getenv("MOBILE_API_TOKEN", "").strip()
MOBILE_WS_HOST = os.getenv("MOBILE_WS_HOST", DASHBOARD_HOST).strip()
MOBILE_WS_PORT = int(os.getenv("MOBILE_WS_PORT", str(DASHBOARD_PORT + 1)))
DEFAULT_OPEN_BROWSER = "ON" if os.name == "nt" and not os.environ.get("CI") else "OFF"
OPEN_BROWSER = os.getenv("OPEN_BROWSER", DEFAULT_OPEN_BROWSER).strip().upper() == "ON"


def require_credentials():
    missing = []
    placeholder_names = {
        name for name, value in {
            "UPSTOX_CLIENT_ID": UPSTOX_CLIENT_ID,
            "UPSTOX_CLIENT_SECRET": UPSTOX_CLIENT_SECRET,
            "UPSTOX_ACCESS_TOKEN": UPSTOX_ACCESS_TOKEN,
            "UPSTOX_AUTH_CODE": UPSTOX_AUTH_CODE,
        }.items() if value.upper() in {"CHANGE_ME", "YOUR_TOKEN_HERE"}
    }
    if placeholder_names:
        missing.extend(sorted(placeholder_names))
    if not UPSTOX_ACCESS_TOKEN:
        missing.extend(name for name, value in {"UPSTOX_CLIENT_ID": UPSTOX_CLIENT_ID, "UPSTOX_CLIENT_SECRET": UPSTOX_CLIENT_SECRET, "UPSTOX_REDIRECT_URI": UPSTOX_REDIRECT_URI}.items() if not value)
        if not UPSTOX_AUTH_CODE:
            missing.append("UPSTOX_AUTH_CODE")
    if missing:
        raise RuntimeError("Missing or placeholder environment variables: " + ", ".join(dict.fromkeys(missing)))
    if ORDER_ENV == "sandbox" and not SANDBOX_ACCESS_TOKEN:
        raise RuntimeError("SANDBOX_ACCESS_TOKEN is required when ORDER_ENV=sandbox")


def validate_runtime():
    valid_modes = {"READ_ONLY", "BACKTEST", "SANDBOX", "PRODUCTION"}
    if ORDER_ENV not in {"live", "sandbox"}:
        raise RuntimeError("ORDER_ENV must be live or sandbox")
    if EXECUTION_MODE not in valid_modes:
        raise RuntimeError("EXECUTION_MODE must be one of: " + ", ".join(sorted(valid_modes)))
    if _DATABASE_OVERRIDE and EXECUTION_MODE != "READ_ONLY" and DATABASE_PATH.name == "market_data.sqlite3":
        raise RuntimeError("Legacy shared database path is allowed only in READ_ONLY mode")
    if MARKET_DATA_MODE not in {"websocket", "polling"}:
        raise RuntimeError("MARKET_DATA_MODE must be websocket or polling")
    if WEBSOCKET_MODE not in {"ltpc", "full", "full_d30"}:
        raise RuntimeError("WEBSOCKET_MODE must be ltpc, full, or full_d30")
    if not INSTRUMENTS:
        raise RuntimeError("INSTRUMENTS must contain at least one index")
    if "FINNIFTY" in INSTRUMENTS:
        raise RuntimeError("FINNIFTY is not an active trading index; use NIFTY,BANKNIFTY,SENSEX,MIDCPNIFTY")
    unsupported = sorted(set(INSTRUMENTS) - set(ACTIVE_INDEXES))
    if unsupported:
        raise RuntimeError("Unsupported active index(es): " + ", ".join(unsupported))
    if not AUTO_ENTRY_ENABLED:
        raise RuntimeError("AUTO_ENTRY_ENABLED must be ON; manual approval is not part of the active entry architecture")
    if (TIMEFRAME_MINUTES <= 0 or HISTORICAL_COUNT <= 0 or HISTORICAL_LOOKBACK_DAYS <= 0
            or UPSTOX_REQUEST_TIMEOUT_SECONDS <= 0):
        raise RuntimeError("TIMEFRAME_MINUTES, HISTORICAL_COUNT, HISTORICAL_LOOKBACK_DAYS, and UPSTOX_REQUEST_TIMEOUT_SECONDS must be positive")
    if MARKET_OPEN >= MARKET_CLOSE:
        raise RuntimeError("MARKET_OPEN must be earlier than MARKET_CLOSE")
    if MARKET_DATA_MODE == "polling" and WEBSOCKET_ENABLED:
        raise RuntimeError("WEBSOCKET_ENABLED=ON requires MARKET_DATA_MODE=websocket")
    if ENABLE_REAL_ORDERS and ORDER_ENV == "live" and not ORDER_IP_WHITELIST:
        raise RuntimeError("UPSTOX_ORDER_IP is required when REAL_ORDERS_ENABLED=ON")
    if EXECUTION_MODE in {"READ_ONLY", "BACKTEST"} and ENABLE_REAL_ORDERS:
        raise RuntimeError("REAL_ORDERS_ENABLED=ON requires SANDBOX or PRODUCTION mode")
    if EXECUTION_MODE == "BACKTEST" and MARKET_DATA_MODE == "websocket":
        raise RuntimeError("BACKTEST mode cannot use live WebSocket market data")
    if EXECUTION_MODE == "PRODUCTION" and ORDER_ENV != "live":
        raise RuntimeError("PRODUCTION requires ORDER_ENV=live")
    if EXECUTION_MODE == "PRODUCTION" and not AUTO_TRADING_ENABLED:
        raise RuntimeError("PRODUCTION requires AUTO_TRADING_ENABLED=ON")
    if EXECUTION_MODE == "SANDBOX" and (not ENABLE_REAL_ORDERS or ORDER_ENV != "sandbox"):
        raise RuntimeError("SANDBOX requires REAL_ORDERS_ENABLED=ON and ORDER_ENV=sandbox")
    if ORDER_ENV == "sandbox" and EXECUTION_MODE != "SANDBOX":
        raise RuntimeError("ORDER_ENV=sandbox requires EXECUTION_MODE=SANDBOX")
    if not HISTORICAL_SYNC_ENABLED:
        raise RuntimeError("HISTORICAL_SYNC_ENABLED must be ON because signals require broker history")
    if LIVE_BROKER_VALIDATION_ENABLED and not ENABLE_REAL_ORDERS:
        raise RuntimeError("LIVE_BROKER_VALIDATION=ON requires REAL_ORDERS_ENABLED=ON")
    if not ENABLE_REAL_ORDERS:
        return
    if ORDER_ENV == "sandbox":
        return
    if not ORDER_IP_WHITELIST:
        raise RuntimeError("UPSTOX_ORDER_IP is required when REAL_ORDERS_ENABLED=ON")
    try:
        ipaddress.ip_address(ORDER_IP_WHITELIST)
    except ValueError as error:
        raise RuntimeError("UPSTOX_ORDER_IP is invalid") from error


def effective_auto_entry_enabled():
    return AUTO_ENTRY_ENABLED and EXECUTION_MODE not in {"READ_ONLY", "BACKTEST"}


def effective_auto_trading_enabled():
    return AUTO_TRADING_ENABLED and EXECUTION_MODE not in {"READ_ONLY", "BACKTEST"}


def execution_status_label():
    if EXECUTION_MODE == "PRODUCTION" and ENABLE_REAL_ORDERS and ORDER_ENV == "live":
        return "LIVE"
    if EXECUTION_MODE == "SANDBOX" and ENABLE_REAL_ORDERS and ORDER_ENV == "sandbox":
        return "SANDBOX"
    if EXECUTION_MODE == "READ_ONLY":
        return "READ_ONLY"
    return EXECUTION_MODE


def order_execution_enabled():
    return ENABLE_REAL_ORDERS and EXECUTION_MODE in {"SANDBOX", "PRODUCTION"} and PREFLIGHT_PASSED


PREFLIGHT_PASSED = False


def set_preflight_passed(value):
    global PREFLIGHT_PASSED
    PREFLIGHT_PASSED = bool(value)


def execution_mode_label():
    return EXECUTION_MODE


def live_order_status():
    if not ENABLE_REAL_ORDERS:
        return "BLOCKED", "REAL_ORDERS_ENABLED=OFF"
    if EXECUTION_MODE not in {"SANDBOX", "PRODUCTION"}:
        return "BLOCKED", f"EXECUTION_MODE={EXECUTION_MODE}"
    if ORDER_ENV != ("sandbox" if EXECUTION_MODE == "SANDBOX" else "live"):
        return "BLOCKED", f"ORDER_ENV={ORDER_ENV}"
    if not AUTO_TRADING_ENABLED:
        return "BLOCKED", "AUTO_TRADING_ENABLED=OFF"
    if not PREFLIGHT_PASSED:
        return "BLOCKED", "PREFLIGHT_NOT_PASSED"
    return "ENABLED", "READY"


def portfolio_stream_enabled():
    return ENABLE_REAL_ORDERS and ORDER_ENV == "live"
