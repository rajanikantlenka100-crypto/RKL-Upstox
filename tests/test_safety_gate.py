import unittest

from trading.safety import SafetyGate, SystemState


class SafetyGateTests(unittest.TestCase):
    """UNIT: deterministic fail-closed BUY interlock checks."""

    def test_buy_is_allowed_only_when_every_check_passes(self):
        gate = SafetyGate(state=SystemState.RUNNING)
        allowed, reason = gate.allow_buy(
            feed_healthy=True, broker_authenticated=True, history_ready=True,
            contract_valid=True, signal_valid=True, database_ready=True,
        )
        self.assertTrue(allowed)
        self.assertEqual(reason, "READY")

    def test_any_critical_failure_blocks_buy(self):
        gate = SafetyGate(state=SystemState.RUNNING)
        allowed, reason = gate.allow_buy(
            feed_healthy=False, broker_authenticated=True, history_ready=True,
            contract_valid=True, signal_valid=True, database_ready=True,
        )
        self.assertFalse(allowed)
        self.assertIn("feed stale", reason)

    def test_halt_is_not_ready(self):
        gate = SafetyGate(state=SystemState.RUNNING)
        gate.halt("unknown order")
        self.assertFalse(gate.ready())
        self.assertEqual(gate.state, SystemState.TRADING_HALTED)

    def test_non_running_system_state_blocks_buy(self):
        gate = SafetyGate(state=SystemState.DEGRADED)
        allowed, reason = gate.allow_buy(
            feed_healthy=True, broker_authenticated=True, history_ready=True,
            contract_valid=True, signal_valid=True, database_ready=True,
        )
        self.assertFalse(allowed)
        self.assertIn("system is not RUNNING", reason)

    def test_running_clears_degradation_reasons(self):
        gate = SafetyGate(state=SystemState.DEGRADED)
        gate.degrade("stale feed")
        gate.running()
        self.assertEqual(gate.state, SystemState.RUNNING)
        self.assertTrue(gate.ready())

    def test_emergency_and_shutdown_states_block_buy(self):
        for transition in ("emergency", "shutdown"):
            gate = SafetyGate(state=SystemState.RUNNING)
            if transition == "emergency":
                gate.emergency(transition)
            else:
                gate.shutdown()
            allowed, _ = gate.allow_buy(
                feed_healthy=True, broker_authenticated=True, history_ready=True,
                contract_valid=True, signal_valid=True, database_ready=True,
            )
            self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
