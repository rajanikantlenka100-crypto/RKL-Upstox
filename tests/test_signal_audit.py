import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data.models import Candle
from signals.audit import SignalAudit


class SignalAuditTests(unittest.TestCase):
    """UNIT: secret-free signal audit persistence and report formatting."""

    def test_report_contains_breakout_and_lifecycle(self):
        path = Path(tempfile.mktemp(suffix=".jsonl"))
        audit = SignalAudit(path)
        audit.write({
            "signal_id": "S1", "instrument": "NIFTY", "direction": "CALL",
            "priority": "PRIMARY", "running_ohlc": [1, 2, 1, 2],
            "previous_ohlc": [1, 1.5, 1, 1.2], "breakout_condition": "running_high > previous_high",
            "breakout_result": "TRUE", "status": "WAITING", "approval": "PENDING",
        })
        report = audit.report()
        self.assertIn("Signal ID: S1", report)
        self.assertIn("running_high > previous_high", report)
        self.assertIn("Lifecycle: WAITING", report)
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
