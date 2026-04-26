from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from binance_futures.income import load_income_records
from binance_futures.models import PositionSnapshot
from binance_futures.reporting import parse_chart_row
from binance_futures.storage import serialize_position


class CoreBehaviourTests(unittest.TestCase):
    def test_serialize_position_keeps_latest_and_history_shapes_consistent(self) -> None:
        position = PositionSnapshot(
            symbol="BTCUSDT",
            side="LONG",
            quantity=0.25,
            entry_price=60000,
            mark_price=62000,
            notional_value=15500,
            unrealized_pnl=500,
            leverage=5,
            liquidation_price=45000,
            margin_type="CROSSED",
        )

        latest_row = serialize_position(position)
        history_row = serialize_position(position, "2026-04-26T12:00:00")

        self.assertNotIn("timestamp", latest_row)
        self.assertEqual(history_row["timestamp"], "2026-04-26T12:00:00")
        self.assertEqual(latest_row["symbol"], history_row["symbol"])
        self.assertEqual(latest_row["pnl_ratio"], "0.03225806")

    def test_parse_chart_row_skips_malformed_history_rows(self) -> None:
        self.assertIsNone(parse_chart_row({"timestamp": "bad", "total_value": "1"}))

        parsed = parse_chart_row(
            {
                "timestamp": "2026-04-26T12:00:00",
                "total_value": "100.5",
                "total_pnl": "-2.25",
                "equity": "98.25",
            }
        )

        self.assertEqual(
            parsed,
            (dt.datetime(2026, 4, 26, 12, 0), 100.5, -2.25, 98.25),
        )

    def test_load_income_records_skips_bad_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            income_file = Path(tmp_dir) / "income.csv"
            income_file.write_text(
                "\n".join(
                    [
                        "time,symbol,income_type,income,asset,info,tran_id,trade_id",
                        "not-a-date,BTCUSDT,REALIZED_PNL,10,USDT,,1,2",
                        "2026-04-26 12:00:00,BTCUSDT,COMMISSION,-0.5,USDT,,3,4",
                    ]
                ),
                encoding="utf-8",
            )

            records = load_income_records(income_file)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].income_type, "COMMISSION")
        self.assertEqual(records[0].income, -0.5)


if __name__ == "__main__":
    unittest.main()
