import unittest
from unittest.mock import patch

import config
from network_diagnostics import PublicIpError, order_ip_allowed, public_ipv4


class NetworkDiagnosticsTests(unittest.TestCase):
    """UNIT: deterministic network-policy checks; no network or broker calls."""

    def test_unconfigured_order_ip_does_not_block_market_reads(self):
        with patch.object(config, "ORDER_IP_WHITELIST", ""):
            self.assertEqual(order_ip_allowed("203.0.113.1"), (True, "ORDER IP CHECK NOT CONFIGURED"))

    def test_configured_order_ip_mismatch_blocks(self):
        with patch.object(config, "ORDER_IP_WHITELIST", "198.51.100.7"):
            self.assertEqual(order_ip_allowed("203.0.113.1"), (False, "ORDER IP NOT WHITELISTED"))

    def test_real_orders_require_order_ip_configuration(self):
        with patch.object(config, "ORDER_IP_WHITELIST", ""):
            self.assertEqual(
                order_ip_allowed("203.0.113.1", require_config=True),
                (False, "ORDER IP POLICY NOT CONFIGURED"),
            )

    def test_invalid_order_ip_policy_blocks(self):
        with patch.object(config, "ORDER_IP_WHITELIST", "not-an-ip"):
            self.assertEqual(
                order_ip_allowed("203.0.113.1", require_config=True),
                (False, "ORDER IP POLICY INVALID"),
            )

    def test_runtime_validation_requires_valid_ip_for_real_orders(self):
        with patch.object(config, "ENABLE_REAL_ORDERS", True), patch.object(config, "ORDER_IP_WHITELIST", ""):
            with self.assertRaisesRegex(RuntimeError, "UPSTOX_ORDER_IP is required"):
                config.validate_runtime()

    def test_live_validation_requires_real_orders(self):
        with patch.object(config, "LIVE_BROKER_VALIDATION_ENABLED", True), patch.object(config, "ENABLE_REAL_ORDERS", False):
            with self.assertRaisesRegex(RuntimeError, "LIVE_BROKER_VALIDATION=ON"):
                config.validate_runtime()

    def test_public_ip_rejects_invalid_response(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ip":"not-an-ip"}'

        with patch("network_diagnostics.urllib.request.urlopen", return_value=Response()):
            with self.assertRaises(PublicIpError):
                public_ipv4()


if __name__ == "__main__":
    unittest.main()
