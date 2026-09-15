import json
import socket
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from websockets.sync.client import connect

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
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = DashboardServer(state, "127.0.0.1", port)
        try:
            server.start(open_browser=False)
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["components"]["DATABASE"], "READY")
        finally:
            server.stop()

    def test_dashboard_reports_degraded_but_available_while_startup_not_ready(self):
        state = FakeState()
        state.components = {"AUTH": "WAITING", "DATABASE": "READY", "HISTORY": "WAITING",
                            "BROKER": "WAITING", "PREFLIGHT": "WAITING", "DASHBOARD": "READY"}
        server = DashboardServer(state, "127.0.0.1", 8770)
        try:
            server.start(open_browser=False)
            with urlopen("http://127.0.0.1:8770/health", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "degraded")
            self.assertFalse(payload["ready"])
            try:
                with urlopen("http://127.0.0.1:8770/ready", timeout=2) as response:
                    ready_payload = json.loads(response.read().decode("utf-8"))
                    self.fail("/ready should report not ready during startup")
            except Exception as error:
                self.assertEqual(getattr(error, "code", None), 503)
        finally:
            server.stop()

    def test_browser_open_attempt_uses_dashboard_url(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8766)
        try:
            with patch("web_dashboard.os", SimpleNamespace(name="nt", environ={})), \
                 patch("web_dashboard.webbrowser.open", return_value=True) as open_browser:
                result = server.start(open_browser=True)
            self.assertEqual(result, "http://127.0.0.1:8766/")
            open_browser.assert_called_once_with("http://127.0.0.1:8766/")
        finally:
            server.stop()

    def test_browser_open_failure_does_not_crash_service(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8767)
        try:
            with patch("web_dashboard.os", SimpleNamespace(name="nt", environ={})), \
                 patch("web_dashboard.webbrowser.open", side_effect=OSError("blocked")):
                result = server.start(open_browser=True)
            self.assertEqual(result, "http://127.0.0.1:8767/")
        finally:
            server.stop()

    def test_headless_start_does_not_attempt_browser_open(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8769)
        import os
        try:
            with patch("web_dashboard.os", SimpleNamespace(name="posix", environ=os.environ)), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch("web_dashboard.webbrowser.open") as open_browser:
                result = server.start(open_browser=True)
            self.assertEqual(result, "http://127.0.0.1:8769/")
            open_browser.assert_not_called()
        finally:
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

    def test_mobile_api_requires_bearer_token(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8771, mobile_token="test-token")
        try:
            server.start(open_browser=False)
            with self.assertRaises(HTTPError) as error:
                urlopen("http://127.0.0.1:8771/api/mobile/status", timeout=2)
            self.assertEqual(error.exception.code, 401)
        finally:
            server.stop()

    def test_mobile_api_returns_authoritative_status_with_token(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8772, mobile_token="test-token")
        try:
            server.start(open_browser=False)
            request = Request(
                "http://127.0.0.1:8772/api/mobile/status",
                headers={"Authorization": "Bearer test-token"},
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["execution_mode"], None)
            self.assertEqual(payload["components"]["DATABASE"], "READY")
        finally:
            server.stop()

    def test_versioned_mobile_status_route_is_read_only(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8773, mobile_token="test-token")
        try:
            server.start(open_browser=False)
            request = Request(
                "http://127.0.0.1:8773/api/v1/mobile/status",
                headers={"Authorization": "Bearer test-token"},
            )
            with urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["components"]["DATABASE"], "READY")
            self.assertNotIn("control", payload)
        finally:
            server.stop()

    def test_mobile_websocket_requires_authentication_and_streams_state(self):
        state = FakeState()
        server = DashboardServer(state, "127.0.0.1", 8774, mobile_token="test-token")
        try:
            server.start(open_browser=False)
            with self.assertRaises(Exception):
                with connect("ws://127.0.0.1:8775/api/v1/mobile/stream", open_timeout=2) as websocket:
                    websocket.recv(timeout=2)
            with connect(
                "ws://127.0.0.1:8775/api/v1/mobile/stream",
                additional_headers={"Authorization": "Bearer test-token"},
                open_timeout=2,
            ) as websocket:
                welcome = json.loads(websocket.recv(timeout=3))
                snapshot = json.loads(websocket.recv(timeout=3))
            self.assertEqual(welcome["event_type"], "WELCOME")
            self.assertEqual(snapshot["protocol"], "rkl.mobile.v1")
            self.assertIn("sequence", snapshot)
            self.assertIn("payload", snapshot)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
