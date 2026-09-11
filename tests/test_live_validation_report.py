import json
import tempfile
import unittest
from pathlib import Path

from broker.validation_report import LiveBrokerValidationReport


class LiveValidationReportTests(unittest.TestCase):
    def test_report_preserves_classification_and_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "validation.jsonl"
            report = LiveBrokerValidationReport(path)
            values = {"event": "REAL_BROKER_RESPONSE", "broker_order_id": "O1"}
            report.record(values)
            self.assertEqual(values["event"], "REAL_BROKER_RESPONSE")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["data_classification"], "LOCAL SYSTEM DATA")
            self.assertEqual(saved["broker_order_id"], "O1")


if __name__ == "__main__":
    unittest.main()