import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from instruments.options import OptionContract, _expiry_date, round_to_tick, select_atm_option

IST = ZoneInfo("Asia/Kolkata")


class OptionResolutionTests(unittest.TestCase):
    def setUp(self):
        self.expiry = (datetime.now(IST).date() + timedelta(days=7)).isoformat()
        self.contract = OptionContract("NIFTY", "2026-09-10", 25000, "CE", "NIFTY", "NSE_FO|1", "NSE_FO", 65, 0.05)

    def test_contract_and_tick_rounding(self):
        contract = OptionContract("NIFTY", "08SEP2026", 23900, "CE", "NIFTY08SEP2623900CE", "42635", "NFO", 65, 0.05)
        self.assertEqual(contract["symbol"], contract.tradingsymbol)
        self.assertEqual(round_to_tick(131.63, contract.tick_size), 131.65)

    def test_expiry_date_supports_iso_format(self):
        self.assertEqual(_expiry_date("2026-10-27"), datetime(2026, 10, 27).date())

    def test_expiry_date_supports_ddmonyyyy_format(self):
        self.assertEqual(_expiry_date("27OCT2026"), datetime(2026, 10, 27).date())

    def test_expiry_date_supports_epoch_milliseconds(self):
        self.assertEqual(_expiry_date(1793125799000), datetime(2026, 10, 27).date())

    def test_expiry_date_rejects_malformed_value(self):
        with self.assertRaises(ValueError):
            _expiry_date("not-an-expiry")

    def test_occupied_atm_contract_uses_deterministic_next_eligible_contract(self):
        records = [
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
             "expiry": self.expiry, "strike_price": 25000, "lot_size": 65, "tick_size": 0.05,
             "trading_symbol": "NIFTY25000CE", "instrument_key": "OCCUPIED"},
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
             "expiry": self.expiry, "strike_price": 25050, "lot_size": 65, "tick_size": 0.05,
             "trading_symbol": "NIFTY25050CE", "instrument_key": "NEXT"},
        ]
        selected = select_atm_option("NIFTY", "NSE_INDEX", 25000, "CALL", records,
                                     underlying_key="NIFTY_KEY", occupied_tokens={"OCCUPIED"})
        self.assertEqual(selected.instrument_key, "NEXT")
        self.assertEqual(selected.strike, 25050)

    def test_liquidity_ranking_prefers_fresh_high_volume_candidate(self):
        records = [
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
             "expiry": self.expiry, "strike_price": 25000, "lot_size": 65, "tick_size": 0.05,
             "trading_symbol": "ATM", "instrument_key": "ATM"},
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
             "expiry": self.expiry, "strike_price": 24950, "lot_size": 65, "tick_size": 0.05,
             "trading_symbol": "LIQUID", "instrument_key": "LIQUID"},
        ]
        selected = select_atm_option(
            "NIFTY", "NSE_INDEX", 25000, "CALL", records, underlying_key="NIFTY_KEY",
            quote_data={"ATM": {"ltp": 100, "volume": 100}, "LIQUID": {"ltp": 90, "volume": 1000}},
        )
        self.assertEqual(selected.instrument_key, "LIQUID")

    def test_entry_selection_rejects_missing_live_quote(self):
        records = [{
            "segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
            "expiry": self.expiry, "strike_price": 25000, "lot_size": 65, "tick_size": 0.05,
            "trading_symbol": "ATM", "instrument_key": "ATM", "last_price": 100,
        }]
        with self.assertRaisesRegex(RuntimeError, "No CALL contract found"):
            select_atm_option("NIFTY", "NSE_INDEX", 25000, "CALL", records,
                              underlying_key="NIFTY_KEY", require_live_quote=True)

    def test_candidate_universe_is_bounded_to_five_strikes(self):
        from instruments.options import select_candidate_options

        records = [{
            "segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
            "expiry": self.expiry, "strike_price": strike, "lot_size": 65, "tick_size": 0.05,
            "trading_symbol": str(strike), "instrument_key": str(strike),
        } for strike in range(24900, 25200, 50)]
        selected = select_candidate_options("NIFTY", "NSE_INDEX", 25000, "CALL", records,
                                            underlying_key="NIFTY_KEY")
        self.assertLessEqual(len(selected), 5)
        self.assertTrue(all(abs(contract.strike - 25000) <= 100 for contract in selected))

    def test_index_expiry_uses_current_applicable_expiry(self):
        today = datetime.now(IST).date()
        weekly = (today + timedelta(days=3)).isoformat()
        next_weekly = (today + timedelta(days=10)).isoformat()
        monthly = (today + timedelta(days=24)).isoformat()
        records = [
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
             "expiry": next_weekly, "strike_price": 25000, "lot_size": 65, "tick_size": 0.05,
             "trading_symbol": "NIFTY25000CE", "instrument_key": "NIFTY_WEEKLY_LATE"},
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
             "expiry": weekly, "strike_price": 25000, "lot_size": 65, "tick_size": 0.05,
             "trading_symbol": "NIFTY25000CE", "instrument_key": "NIFTY_WEEKLY_CURRENT"},
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "BANKNIFTY_KEY",
             "expiry": monthly, "strike_price": 50000, "lot_size": 15, "tick_size": 0.05,
             "trading_symbol": "BANKNIFTY50000CE", "instrument_key": "BANKNIFTY_MONTHLY"},
            {"segment": "BSE_FO", "instrument_type": "CE", "underlying_key": "SENSEX_KEY",
             "expiry": next_weekly, "strike_price": 80000, "lot_size": 10, "tick_size": 0.05,
             "trading_symbol": "SENSEX80000CE", "instrument_key": "SENSEX_WEEKLY_LATE"},
            {"segment": "BSE_FO", "instrument_type": "CE", "underlying_key": "SENSEX_KEY",
             "expiry": weekly, "strike_price": 80000, "lot_size": 10, "tick_size": 0.05,
             "trading_symbol": "SENSEX80000CE", "instrument_key": "SENSEX_WEEKLY_CURRENT"},
            {"segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "MIDCPNIFTY_KEY",
             "expiry": monthly, "strike_price": 25000, "lot_size": 50, "tick_size": 0.05,
             "trading_symbol": "MIDCPNIFTY25000CE", "instrument_key": "MIDCPNIFTY_MONTHLY"},
        ]
        self.assertEqual(select_atm_option("NIFTY", "NSE_INDEX", 25000, "CALL", records, underlying_key="NIFTY_KEY").expiry, weekly)
        self.assertEqual(select_atm_option("SENSEX", "BSE_INDEX", 80000, "CALL", records, underlying_key="SENSEX_KEY").expiry, weekly)
        self.assertEqual(select_atm_option("BANKNIFTY", "NSE_INDEX", 50000, "CALL", records, underlying_key="BANKNIFTY_KEY").expiry, monthly)
        self.assertEqual(select_atm_option("MIDCPNIFTY", "NSE_INDEX", 25000, "CALL", records, underlying_key="MIDCPNIFTY_KEY").expiry, monthly)

    def test_expired_contracts_are_rejected(self):
        expired = (datetime.now(IST).date() - timedelta(days=1)).isoformat()
        records = [{
            "segment": "NSE_FO", "instrument_type": "CE", "underlying_key": "NIFTY_KEY",
            "expiry": expired, "strike_price": 25000, "lot_size": 65, "tick_size": 0.05,
            "trading_symbol": "EXPIRED", "instrument_key": "EXPIRED",
        }]
        with self.assertRaisesRegex(RuntimeError, "No current option expiry"):
            select_atm_option("NIFTY", "NSE_INDEX", 25000, "CALL", records,
                              underlying_key="NIFTY_KEY")


if __name__ == "__main__":
    unittest.main()
