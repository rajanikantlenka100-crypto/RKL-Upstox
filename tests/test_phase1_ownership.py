import unittest
from pathlib import Path

from trading.safety import SystemState


class PhaseOneOwnershipTests(unittest.TestCase):
    def test_required_system_states_are_explicit(self):
        self.assertEqual(
            {state.value for state in SystemState},
            {"RUNNING", "DEGRADED", "TRADING_HALTED", "EMERGENCY", "SHUTTING_DOWN"},
        )

    def test_main_has_one_approval_owner_and_no_signal_queue_wiring(self):
        source = Path(__file__).parents[1].joinpath("main.py").read_text(encoding="utf-8")
        self.assertNotIn("SignalQueue", source)
        self.assertEqual(source.count("ApprovalController("), 1)
        self.assertEqual(source.count("place_approved_buy("), 1)

    def test_terminal_has_one_keyboard_reader(self):
        source = Path(__file__).parents[1].joinpath("signals", "coordinator.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("msvcrt.kbhit()"), 1)
        self.assertEqual(source.count("sys.stdin.isatty()"), 1)


if __name__ == "__main__":
    unittest.main()