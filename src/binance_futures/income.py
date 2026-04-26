from __future__ import annotations

import datetime as dt
import csv
from pathlib import Path
from typing import Iterable

from .models import IncomeRecord

INCOME_SYNC_OVERLAP = dt.timedelta(minutes=10)


def income_record_key(item: IncomeRecord) -> tuple[str, str]:
    if item.tran_id:
        return (item.income_type, item.tran_id)
    fallback = (
        f"{item.time.isoformat()}:{item.trade_id}:{item.symbol}:{item.asset}:{item.income:.8f}"
    )
    return (item.income_type, fallback)


def load_income_records(income_file: Path) -> list[IncomeRecord]:
    if not income_file.exists():
        return []

    with income_file.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    items: list[IncomeRecord] = []
    for row in rows:
        raw_time = (row.get("time") or "").strip()
        if not raw_time:
            continue
        try:
            items.append(
                IncomeRecord(
                    symbol=str(row.get("symbol", "")),
                    income_type=str(row.get("income_type", "")),
                    income=float(row.get("income", 0) or 0),
                    asset=str(row.get("asset", "")),
                    info=str(row.get("info", "")),
                    time=dt.datetime.fromisoformat(raw_time),
                    tran_id=str(row.get("tran_id", "")),
                    trade_id=str(row.get("trade_id", "")),
                )
            )
        except (TypeError, ValueError):
            continue

    items.sort(key=lambda item: item.time, reverse=True)
    return items


def determine_income_sync_start(
    existing_records: list[IncomeRecord], realized_since: dt.datetime | None
) -> dt.datetime | None:
    if realized_since is None:
        return None
    if not existing_records:
        return realized_since

    latest_local_time = max(item.time for item in existing_records)
    return max(realized_since, latest_local_time - INCOME_SYNC_OVERLAP)


def merge_income_records(
    existing_records: Iterable[IncomeRecord],
    new_records: Iterable[IncomeRecord],
    realized_since: dt.datetime | None,
) -> list[IncomeRecord]:
    merged: dict[tuple[str, str], IncomeRecord] = {}
    for item in list(existing_records) + list(new_records):
        if realized_since is not None and item.time < realized_since:
            continue
        merged[income_record_key(item)] = item

    records = list(merged.values())
    records.sort(key=lambda item: item.time, reverse=True)
    return records


def summarize_income(records: Iterable[IncomeRecord]) -> dict[str, float]:
    items = list(records)
    realized_pnl = sum(item.income for item in items if item.income_type == "REALIZED_PNL")
    commission = sum(item.income for item in items if item.income_type == "COMMISSION")
    funding_fee = sum(item.income for item in items if item.income_type == "FUNDING_FEE")
    net_realized_pnl = realized_pnl + commission + funding_fee
    return {
        "realized_pnl": realized_pnl,
        "commission": commission,
        "funding_fee": funding_fee,
        "net_realized_pnl": net_realized_pnl,
        "income_row_count": float(len(items)),
    }
