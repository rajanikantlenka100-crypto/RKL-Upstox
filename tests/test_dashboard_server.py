import json
import threading
import time
import unittest
from urllib.request import urlopen

from web_dashboard import DashboardServer


class FakeState:
    def __init__(self):
        self.components = {"AUTH": "READY", "DATABASE": "READY", "HISTORY": "READY", "CANDLES": "READY", "SIGNALS": "READY", "BROKER": "READY", "RISK": "READY", "ORDERS": "DISABLED", "DASHBOARD": "READY"}
        self.ws_status = "CONNECTED"
        self.signal = None
        self.positions = []
        self.events = []
        self.latest = {}
        self.candles = {}
        self.previous = {}
        self.indicators = {}
        self.health = {}
        self.sync = {}
        self.last_event = "Starting"
        self.market_status = "CLOSED"

    def snapshot(self):
        return {
            "instrument_names": ["NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY"],
            "components": self.components,
            "ws_status": self.ws_status,
            "signal": self.signal,
            "positions": self.positions,
            "events": self.events,
            "latest": self.latest,
            "candles": self.candles,
            "previous": self.previous,
            "indicators": self.indicators,
            "health": self.health,
            "sync": self.sync,
            "last_event": self.last_event,
            "market_status": self.market_status,
        }


class DashboardServerTests(unittest.TestCase):
    def test_dashboard_health_endpoint(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8765)
        try:
            server.start(open_browser=False)
            with urlopen("http://127.0.0.1:8765/health", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["components"]["DATABASE"], "READY")
        finally:
            server.stop()

    def test_browser_open_attempt_uses_dashboard_url(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8766)
        opened = []
        import webbrowser
        original = webbrowser.open
        webbrowser.open = lambda url: opened.append(url) or True
        try:
            result = server.start(open_browser=True)
            self.assertEqual(result, "http://127.0.0.1:8766/")
            self.assertEqual(opened, ["http://127.0.0.1:8766/"])
        finally:
            webbrowser.open = original
            server.stop()

    def test_browser_open_failure_does_not_crash_service(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8767)
        import webbrowser
        original = webbrowser.open
        webbrowser.open = lambda url: (_ for _ in ()).throw(OSError("blocked"))
        try:
            result = server.start(open_browser=True)
            self.assertEqual(result, "http://127.0.0.1:8767/")
        finally:
            webbrowser.open = original
            server.stop()

    def test_dashboard_html_includes_market_sections(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8768)
        try:
            server.start(open_browser=False)
            with urlopen("http://127.0.0.1:8768/", timeout=2) as response:
                html = response.read().decode("utf-8")
            self.assertIn("NIFTY", html)
            self.assertIn("BANKNIFTY", html)
            self.assertIn("MIDCPNIFTY", html)
            self.assertIn("SENSEX", html)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
