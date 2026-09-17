import unittest

from instruments.options import OptionContract


def select_priority_contract(priority_book, underlying, direction, occupied_tokens=None):
    occupied = {str(token) for token in (occupied_tokens or set())}
    candidates = priority_book.get(underlying, {}).get(direction, [])

    for priority, contract in enumerate(candidates[:2], start=1):
        if contract.instrument_key not in occupied:
            return contract, priority

    return None, None


class OptionPrioritySelectionTests(unittest.TestCase):
    def setUp(self):
        self.p1 = OptionContract(
            "NIFTY", "2026-09-24", 25000, "CE",
            "NIFTY25000CE", "P1_TOKEN", "NSE_FO", 65, 0.05
        )
        self.p2 = OptionContract(
            "NIFTY", "2026-09-24", 25050, "CE",
            "NIFTY25050CE", "P2_TOKEN", "NSE_FO", 65, 0.05
        )
        self.put = OptionContract(
            "NIFTY", "2026-09-24", 25000, "PE",
            "NIFTY25000PE", "PUT_TOKEN", "NSE_FO", 65, 0.05
        )

        self.book = {
            "NIFTY": {
                "CALL": [self.p1, self.p2],
                "PUT": [self.put],
            }
        }

    def test_call_selects_priority_one(self):
        contract, priority = select_priority_contract(
            self.book, "NIFTY", "CALL"
        )
        self.assertEqual(contract.instrument_key, "P1_TOKEN")
        self.assertEqual(priority, 1)

    def test_call_uses_priority_two_when_priority_one_is_occupied(self):
        contract, priority = select_priority_contract(
            self.book, "NIFTY", "CALL", {"P1_TOKEN"}
        )
        self.assertEqual(contract.instrument_key, "P2_TOKEN")
        self.assertEqual(priority, 2)

    def test_call_rejects_when_both_priorities_are_occupied(self):
        contract, priority = select_priority_contract(
            self.book, "NIFTY", "CALL", {"P1_TOKEN", "P2_TOKEN"}
        )
        self.assertIsNone(contract)
        self.assertIsNone(priority)

    def test_call_never_selects_put_contract(self):
        contract, priority = select_priority_contract(
            self.book, "NIFTY", "CALL", {"P1_TOKEN"}
        )
        self.assertNotEqual(contract.instrument_key, "PUT_TOKEN")

    def test_put_uses_put_book_only(self):
        contract, priority = select_priority_contract(
            self.book, "NIFTY", "PUT"
        )
        self.assertEqual(contract.instrument_key, "PUT_TOKEN")
        self.assertEqual(priority, 1)

    def test_only_first_two_candidates_are_eligible(self):
        p3 = OptionContract(
            "NIFTY", "2026-09-24", 25100, "CE",
            "NIFTY25100CE", "P3_TOKEN", "NSE_FO", 65, 0.05
        )

        book = {
            "NIFTY": {
                "CALL": [self.p1, self.p2, p3],
                "PUT": [],
            }
        }

        contract, priority = select_priority_contract(
            book, "NIFTY", "CALL",
            {"P1_TOKEN", "P2_TOKEN"}
        )

        self.assertIsNone(contract)
        self.assertIsNone(priority)


if __name__ == "__main__":
    unittest.main()
