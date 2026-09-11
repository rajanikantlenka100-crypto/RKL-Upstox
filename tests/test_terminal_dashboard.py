import contextlib
import io
import re
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_data.models import Candle, MarketTick
from terminal_display import TerminalDisplay, safe_print


class TerminalDashboardTests(unittest.TestCase):
    """UNIT: deterministic terminal dashboard fixtures; no broker or live market."""

    def setUp(self):
        names = ("NIFTY", "SENSEX", "BANKNIFTY", "MIDCPNIFTY")
        self.display = TerminalDisplay({name: object() for name in names}, live_updates=False)
        timestamp = datetime(2026, 9, 3, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.previous = Candle("NIFTY", "NSE", "1", timestamp, "5m", 98, 101, 97, 100, 8, "HISTORICAL")
        self.running = Candle("NIFTY", "NSE", "1", timestamp, "5m", 100, 105, 99, 104, 10, "LIVE")
        self.tick = MarketTick("NIFTY", "1", "NSE", timestamp, 104, 10, "LIVE")

    def render_text(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.display.render()
        return output.getvalue()

    def test_fixed_screen_contains_all_indexes_and_candles(self):
        self.display.set_previous("NIFTY", self.previous)
        self.display.update_tick(self.tick, self.running)
        self.display.set_health("NIFTY", "LIVE")
        text = self.render_text()
        lines = [re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", line) for line in text.splitlines() if line]
        self.assertLessEqual(max(map(len, lines)), 78)
        self.assertLessEqual(len(lines), 40)
        for name in ("NIFTY", "SENSEX", "BANKNIFTY", "MIDCPNIFTY"):
            self.assertIn(name, text)
        self.assertIn("104.00", text)
        self.assertIn("RUN 10:00", text)
        self.assertIn("PREV 10:00", text)
        self.assertIn("EXCHANGE LAST", text)

    def test_signal_and_position_panels_are_visible(self):
        self.display.set_signal({
            "direction": "CALL", "underlying": "NIFTY", "ltp": "104.00",
            "breakout": "101.00", "option": "NIFTY", "status": "APPROVAL REQUIRED",
        })
        self.display.set_positions(["T001 OPTION QTY:50 ENTRY:10.00 SL:8.00 STATUS:SL_ACTIVE"])
        text = self.render_text()
        self.assertIn("APPROVAL REQUIRED", text)
        self.assertIn("ACTIVE POSITIONS", text)
        self.assertIn("T001", text)

    def test_control_render_has_no_runtime_timezone_error(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.display.render_control()
        self.assertIn("RKL ALGO TRADING CONTROL CENTER", output.getvalue())

    def test_update_tick_redraws_when_live_updates_enabled(self):
        display = TerminalDisplay({"NIFTY": object()}, live_updates=True)
        timestamp = datetime.now(ZoneInfo("Asia/Kolkata"))
        tick = MarketTick("NIFTY", "1", "NSE", timestamp, 104, 10, "LIVE")
        running = Candle("NIFTY", "NSE", "1", timestamp, "5m", 100, 105, 99, 104, 10, "LIVE")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            display.set_health("NIFTY", "LIVE")
            display.update_tick(tick, running)
            display.render()
        self.assertIn("104.00", output.getvalue())
        self.assertIn("🕯️ RUN", output.getvalue())
        self.assertIn("O:100.0 H:105.0 L:99.0 C:104.0", output.getvalue())

    def test_safe_print_handles_ascii_only_stdout(self):
        class AsciiOnly(io.TextIOBase):
            encoding = "ascii"

            def write(self, data):
                if any(ord(ch) > 127 for ch in data):
                    raise UnicodeEncodeError("ascii", data, 0, len(data), "ordinal not in range(128)")
                return len(data)

        with contextlib.redirect_stdout(AsciiOnly()):
            safe_print("💾 DATABASE READY")
            safe_print("📡 UPSTOX FEED STARTING")


if __name__ == "__main__":
    unittest.main()
