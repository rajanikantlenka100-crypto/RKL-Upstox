import unittest
import urllib.error
from unittest.mock import Mock, patch
import config

from broker.upstox import UpstoxClient, UpstoxAdapter
from instruments.options import select_atm_option
from instruments.resolver import Instrument, resolve_indices


class UpstoxSystemTests(unittest.TestCase):
    def test_active_index_universe_excludes_finnifty(self):
        self.assertEqual(config.INSTRUMENTS, ("NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY"))

    def test_authentication_status_does_not_claim_token_is_valid(self):
        statuses = []
        adapter = UpstoxAdapter(lambda tick: None, statuses.append)

        with patch("config.require_credentials"), patch("config.UPSTOX_ACCESS_TOKEN", ""), patch.object(
            adapter, "on_status", statuses.append
        ), patch("broker.upstox.UpstoxClient.request", return_value={"access_token": "unit-test-token"}) as request:
            adapter.authenticate()

        request.assert_called_once()
        self.assertIn("/v2/login/authorization/token", request.call_args.args[1])
        self.assertEqual(statuses[-2:], ["ACCESS TOKEN PRESENT", "CREDENTIAL LOADED"])
        self.assertNotIn("AUTHENTICATED", statuses)

    def test_token_validation_accepts_authenticated_profile(self):
        adapter = UpstoxAdapter(lambda tick: None, lambda status: None)
        adapter.client = Mock()
        adapter.client.user_profile.return_value = {"status": "success", "data": {"user_id": "safe"}}
        self.assertEqual(adapter.validate_token(), "TOKEN VALID")

    def test_token_validation_classifies_expired_rejected_and_network(self):
        for error, expected in (
            (urllib.error.HTTPError("https://upstox.test", 401, "expired", {}, None), "TOKEN EXPIRED"),
            (urllib.error.HTTPError("https://upstox.test", 403, "rejected", {}, None), "TOKEN REJECTED"),
            (urllib.error.URLError("offline"), "NETWORK ERROR: offline"),
        ):
            adapter = UpstoxAdapter(lambda tick: None, lambda status: None)
            adapter.client = Mock()
            adapter.client.user_profile.side_effect = error
            self.assertEqual(adapter.validate_token(), expected)
    def test_index_resolution_uses_instrument_keys(self):
        records = [
            {"instrument_key": "NSE_INDEX|Nifty 50", "trading_symbol": "NIFTY 50", "segment": "NSE_INDEX"},
            {"instrument_key": "BSE_INDEX|SENSEX", "trading_symbol": "SENSEX", "segment": "BSE_INDEX"},
            {"instrument_key": "NSE_INDEX|Nifty Bank", "trading_symbol": "Nifty Bank", "segment": "NSE_INDEX"},
            {"instrument_key": "NSE_INDEX|Nifty Fin Service", "trading_symbol": "Nifty Fin Service", "segment": "NSE_INDEX"},
            {"instrument_key": "NSE_INDEX|NIFTY MID SELECT", "trading_symbol": "NIFTY MID SELECT", "segment": "NSE_INDEX"},
        ]
        resolved = resolve_indices(records)
        self.assertEqual(resolved["NIFTY"].token, "NSE_INDEX|Nifty 50")

    def test_option_resolution_preserves_upstox_contract_identity(self):
        records = [{
            "instrument_key": "NSE_FO|123", "trading_symbol": "NIFTY26SEP25000CE", "segment": "NSE_FO",
            "instrument_type": "OPTIDX", "name": "NIFTY", "expiry": "2026-09-24",
            "strike": 25000, "option_type": "CE", "lot_size": 75, "tick_size": 0.05,
        }]
        contract = select_atm_option("NIFTY", "NSE_INDEX", 25010, "CALL", records)
        self.assertEqual(contract.instrument_key, "NSE_FO|123")
        self.assertEqual(contract.lotsize, 75)
        self.assertEqual(contract.tick_size, 0.05)

    def test_order_payload_is_upstox_v3_shape(self):
        client = UpstoxClient("token")
        client.request = Mock(return_value={"status": "success", "data": {"order_ids": ["U1"]}})
        response = client.place_order({
            "instrument_token": "NSE_FO|123", "transaction_type": "BUY", "order_type": "MARKET",
            "price": 0, "quantity": 75,
        })
        payload = client.request.call_args.args[2]
        self.assertEqual(payload["instrument_token"], "NSE_FO|123")
        self.assertEqual(payload["quantity"], 75)
        self.assertEqual(response["data"]["order_id"], "U1")

    def test_historical_rows_are_normalized_for_candles(self):
        adapter = UpstoxAdapter(lambda tick: None, lambda status: None)
        adapter.client = Mock()
        adapter.client.request.return_value = {"data": {"candles": [["2026-09-08T09:15:00+05:30", 100, 105, 99, 103, 500]]}}
        instrument = type("Instrument", (), {"token": "NSE_INDEX|Nifty 50"})()
        self.assertEqual(adapter.fetch_historical(instrument), [["2026-09-08T09:15:00+05:30", 100.0, 105.0, 99.0, 103.0, 500]])

    def test_malformed_websocket_item_does_not_block_valid_item(self):
        ticks = []
        raw_events = []
        adapter = UpstoxAdapter(ticks.append, lambda status: None, raw_events.append)
        adapter._token_to_instrument = {
            "BAD": Instrument("NIFTY", "NIFTY", "BAD", "NSE_INDEX"),
            "GOOD": Instrument("SENSEX", "SENSEX", "GOOD", "BSE_INDEX"),
        }
        adapter._on_stream_message({"feeds": {
            "BAD": {"ltpc": {"ltp": "not-a-number", "ltt": 1789000000000}},
            "GOOD": {"ltpc": {"ltp": 100.0, "ltt": 1789000000000}},
        }})
        self.assertEqual([event["error"] for event in raw_events if event.get("error")], ["INVALID_LTP"])
        self.assertEqual([tick.instrument for tick in ticks], ["SENSEX"])


if __name__ == "__main__":
    unittest.main()
