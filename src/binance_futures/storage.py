from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

from .models import IncomeRecord, PositionSnapshot

HISTORY_FIELDNAMES = [
    "timestamp",
    "total_value",
    "total_pnl",
    "long_value",
    "short_value",
    "position_count",
    "equity",
    "wallet_balance",
    "available_balance",
    "realized_pnl",
    "commission",
    "funding_fee",
    "net_realized_pnl",
    "total_trading_pnl",
    "income_row_count",
]

POSITION_FIELDNAMES = [
    "timestamp",
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "mark_price",
    "notional_value",
    "unrealized_pnl",
    "pnl_ratio",
    "leverage",
    "liquidation_price",
    "margin_type",
]


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_history(history_file: Path) -> list[dict[str, str]]:
    if not history_file.exists():
        return []

    with history_file.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    normalized: list[dict[str, str]] = []
    for row in rows:
        timestamp = row.get("timestamp")
        if not timestamp and row.get("date"):
            timestamp = f"{row['date']}T00:00:00"

        normalized.append(
            {
                "timestamp": timestamp or "",
                "total_value": row.get("total_value", "0"),
                "total_pnl": row.get("total_pnl", "0"),
                "long_value": row.get("long_value", "0"),
                "short_value": row.get("short_value", "0"),
                "position_count": row.get("position_count", "0"),
                "equity": row.get("equity", row.get("total_value", "0")),
                "wallet_balance": row.get("wallet_balance", "0"),
                "available_balance": row.get("available_balance", "0"),
                "realized_pnl": row.get("realized_pnl", "0"),
                "commission": row.get("commission", "0"),
                "funding_fee": row.get("funding_fee", "0"),
                "net_realized_pnl": row.get("net_realized_pnl", "0"),
                "total_trading_pnl": row.get("total_trading_pnl", row.get("total_pnl", "0")),
                "income_row_count": row.get("income_row_count", "0"),
            }
        )
    return normalized


def write_history(history_file: Path, rows: list[dict[str, str]]) -> None:
    ensure_parent(history_file)
    with history_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def upsert_history_row(
    history_rows: list[dict[str, str]],
    current_time: dt.datetime,
    summary: dict[str, float],
) -> list[dict[str, str]]:
    target = current_time.replace(microsecond=0).isoformat()
    serialized = {
        "timestamp": target,
        "total_value": f"{summary['total_value']:.8f}",
        "total_pnl": f"{summary['total_pnl']:.8f}",
        "long_value": f"{summary['long_value']:.8f}",
        "short_value": f"{summary['short_value']:.8f}",
        "position_count": str(int(summary["position_count"])),
        "equity": f"{summary['equity']:.8f}",
        "wallet_balance": f"{summary['wallet_balance']:.8f}",
        "available_balance": f"{summary['available_balance']:.8f}",
        "realized_pnl": f"{summary['realized_pnl']:.8f}",
        "commission": f"{summary['commission']:.8f}",
        "funding_fee": f"{summary['funding_fee']:.8f}",
        "net_realized_pnl": f"{summary['net_realized_pnl']:.8f}",
        "total_trading_pnl": f"{summary['total_trading_pnl']:.8f}",
        "income_row_count": str(int(summary["income_row_count"])),
    }

    merged = [row for row in history_rows if row.get("timestamp") != target]
    merged.append(serialized)
    merged.sort(key=lambda item: item.get("timestamp", ""))
    return merged


def serialize_position(item: PositionSnapshot, timestamp: str | None = None) -> dict[str, str]:
    row = {
        "symbol": item.symbol,
        "side": item.side,
        "quantity": f"{item.quantity:.8f}",
        "entry_price": f"{item.entry_price:.8f}",
        "mark_price": f"{item.mark_price:.8f}",
        "notional_value": f"{item.notional_value:.8f}",
        "unrealized_pnl": f"{item.unrealized_pnl:.8f}",
        "pnl_ratio": f"{item.pnl_ratio:.8f}",
        "leverage": f"{item.leverage:.2f}",
        "liquidation_price": f"{item.liquidation_price:.8f}",
        "margin_type": item.margin_type,
    }
    if timestamp is not None:
        row = {"timestamp": timestamp, **row}
    return row


def write_positions_csv(positions_file: Path, positions: list[PositionSnapshot]) -> None:
    ensure_parent(positions_file)
    with positions_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSITION_FIELDNAMES[1:])
        writer.writeheader()
        for item in positions:
            writer.writerow(serialize_position(item))


def load_position_history(position_history_file: Path) -> list[dict[str, str]]:
    if not position_history_file.exists():
        return []

    with position_history_file.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def upsert_position_history_rows(
    existing_rows: list[dict[str, str]],
    current_time: dt.datetime,
    positions: list[PositionSnapshot],
) -> list[dict[str, str]]:
    target = current_time.replace(microsecond=0).isoformat()
    merged = [row for row in existing_rows if row.get("timestamp") != target]

    for item in positions:
        merged.append(serialize_position(item, target))

    merged.sort(key=lambda item: (item.get("timestamp", ""), item.get("symbol", "")))
    return merged


def write_position_history_csv(position_history_file: Path, rows: list[dict[str, str]]) -> None:
    ensure_parent(position_history_file)
    with position_history_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSITION_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_income_csv(income_file: Path, records: list[IncomeRecord]) -> None:
    ensure_parent(income_file)
    fieldnames = [
        "time",
        "symbol",
        "income_type",
        "income",
        "asset",
        "info",
        "tran_id",
        "trade_id",
    ]
    with income_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in records:
            writer.writerow(
                {
                    "time": item.time.replace(microsecond=0).isoformat(sep=" "),
                    "symbol": item.symbol,
                    "income_type": item.income_type,
                    "income": f"{item.income:.8f}",
                    "asset": item.asset,
                    "info": item.info,
                    "tran_id": item.tran_id,
                    "trade_id": item.trade_id,
                }
            )
