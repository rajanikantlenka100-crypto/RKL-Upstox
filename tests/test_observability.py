import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from observability import Observability
from signals.candidate_trace import CandidateTrace
from storage.sqlite_store import CandleStore


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mktemp(suffix=".sqlite3"))
        self.store = CandleStore(self.path)
        self.telemetry = Observability(self.store)

    def tearDown(self):
        self.store.close()
        self.path.unlink(missing_ok=True)

    def test_events_and_report_are_persistent(self):
        self.telemetry.event("AUTH_START", component="AUTH")
        self.telemetry.event("AUTH_END", component="AUTH", payload={"success": True})
        self.telemetry.event("ORDER_REQUEST_SENT", component="ORDERS")
        self.telemetry.event("ORDER_REJECTED", component="ORDERS", severity="ERROR", message="ZERO_BALANCE")

        report_date = datetime.now().astimezone().date().isoformat()
        report = self.telemetry.daily_report(report_date)

        self.assertEqual(report["sections"]["AUTH"]["status"], "PASS")
        self.assertEqual(report["order_verification"]["ORDER REQUEST REACHED BROKER"], "PASS")
        self.assertEqual(report["order_verification"]["BROKER ACCEPTED/FILLED"], "FAILED")
        self.assertEqual(report["order_verification"]["SL/FILL LIFECYCLE"], "NOT TESTED")
        self.assertEqual(len(self.store.telemetry_events(report_date)), 4)

    def test_candidate_trace_forwards_every_record(self):
        records = []
        path = Path(tempfile.mktemp(suffix=".jsonl"))
        trace = CandidateTrace(path, on_record=records.append)
        trace.write({"reason_code": "CALL_CANDIDATE", "signal_type": "TYPE_1"})
        trace.write({"reason_code": "RSI_REJECT", "signal_type": "TYPE_1"})
        self.assertEqual([item["reason_code"] for item in records], ["CALL_CANDIDATE", "RSI_REJECT"])
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
