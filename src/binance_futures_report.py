#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import hmac
import html
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

import requests


DEFAULT_BASE_URL = "https://fapi.binance.com"


@dataclass
class PositionSnapshot:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    mark_price: float
    notional_value: float
    unrealized_pnl: float
    leverage: float
    liquidation_price: float
    margin_type: str

    @property
    def pnl_ratio(self) -> float:
        if self.notional_value == 0:
            return 0.0
        return self.unrealized_pnl / self.notional_value


@dataclass
class AccountSnapshot:
    wallet_balance: float
    unrealized_pnl: float
    margin_balance: float
    available_balance: float


@dataclass
class IncomeRecord:
    symbol: str
    income_type: str
    income: float
    asset: str
    info: str
    time: dt.datetime
    tran_id: str
    trade_id: str


INCOME_SYNC_OVERLAP = dt.timedelta(minutes=10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a daily Binance futures position-value report."
    )
    parser.add_argument("--env-file", default=".env", help="Path to the .env file.")
    parser.add_argument("--output-dir", default="output", help="Directory for report files.")
    parser.add_argument(
        "--history-file",
        default=None,
        help="CSV file for daily total position value history.",
    )
    parser.add_argument(
        "--chart-file",
        default=None,
        help="PNG file path for the generated curve chart.",
    )
    parser.add_argument(
        "--positions-file",
        default=None,
        help="CSV file path for the latest position snapshot.",
    )
    parser.add_argument(
        "--html-file",
        default=None,
        help="HTML file path for the dashboard report.",
    )
    parser.add_argument(
        "--income-file",
        default=None,
        help="CSV file path for the fetched realized/income ledger.",
    )
    parser.add_argument(
        "--position-history-file",
        default=None,
        help="CSV file path for timestamped per-position history snapshots.",
    )
    parser.add_argument(
        "--realized-since",
        default=None,
        help="Start date/time for realized PnL aggregation, e.g. 2026-04-12 or 2026-04-12T00:00:00.",
    )
    return parser.parse_args()


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def build_signed_params(params: dict[str, object], secret: str) -> str:
    query = urlencode(params, doseq=True)
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256)
    return f"{query}&signature={signature.hexdigest()}"


def signed_get(
    session: requests.Session,
    base_url: str,
    path: str,
    api_key: str,
    api_secret: str,
    params: dict[str, object] | None = None,
) -> object:
    query_params = dict(params or {})
    query_params["timestamp"] = int(time.time() * 1000)
    query_string = build_signed_params(query_params, api_secret)
    response = session.get(
        f"{base_url}{path}?{query_string}",
        headers={"X-MBX-APIKEY": api_key},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_positions(
    session: requests.Session,
    base_url: str,
    api_key: str,
    api_secret: str,
) -> list[PositionSnapshot]:
    raw_positions = signed_get(
        session,
        base_url,
        "/fapi/v2/positionRisk",
        api_key,
        api_secret,
    )

    positions: list[PositionSnapshot] = []
    for raw in raw_positions:
        quantity = float(raw["positionAmt"])
        if quantity == 0:
            continue

        mark_price = float(raw["markPrice"])
        notional_value = abs(quantity * mark_price)
        side = "LONG" if quantity > 0 else "SHORT"
        if raw.get("positionSide") not in {"BOTH", "", None}:
            side = str(raw["positionSide"]).upper()

        positions.append(
            PositionSnapshot(
                symbol=str(raw["symbol"]),
                side=side,
                quantity=quantity,
                entry_price=float(raw["entryPrice"]),
                mark_price=mark_price,
                notional_value=notional_value,
                unrealized_pnl=float(raw["unRealizedProfit"]),
                leverage=float(raw.get("leverage", 0) or 0),
                liquidation_price=float(raw.get("liquidationPrice", 0) or 0),
                margin_type=str(raw.get("marginType", "unknown")).upper(),
            )
        )

    positions.sort(key=lambda item: item.notional_value, reverse=True)
    return positions


def fetch_account_snapshot(
    session: requests.Session,
    base_url: str,
    api_key: str,
    api_secret: str,
) -> AccountSnapshot:
    raw_account = signed_get(
        session,
        base_url,
        "/fapi/v2/account",
        api_key,
        api_secret,
    )
    return AccountSnapshot(
        wallet_balance=float(raw_account["totalWalletBalance"]),
        unrealized_pnl=float(raw_account["totalUnrealizedProfit"]),
        margin_balance=float(raw_account["totalMarginBalance"]),
        available_balance=float(raw_account["availableBalance"]),
    )


def parse_since_datetime(raw_value: str | None) -> dt.datetime | None:
    if not raw_value:
        return None

    text = raw_value.strip()
    if not text:
        return None

    for parser in (dt.datetime.fromisoformat,):
        try:
            parsed = parser(text)
            if parsed.tzinfo is not None:
                return parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            continue

    try:
        parsed_date = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported --realized-since value: {raw_value!r}. Use YYYY-MM-DD or ISO datetime."
        ) from exc
    return dt.datetime.combine(parsed_date, dt.time.min)


def fetch_income_history(
    session: requests.Session,
    base_url: str,
    api_key: str,
    api_secret: str,
    start_time: dt.datetime | None,
) -> list[IncomeRecord]:
    if start_time is None:
        return []

    start_ms = int(start_time.timestamp() * 1000)
    income_types = ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")
    records: list[IncomeRecord] = []
    seen_keys: set[tuple[str, str]] = set()

    for income_type in income_types:
        cursor = start_ms
        while True:
            raw_rows = signed_get(
                session,
                base_url,
                "/fapi/v1/income",
                api_key,
                api_secret,
                params={
                    "incomeType": income_type,
                    "startTime": cursor,
                    "limit": 1000,
                },
            )
            if not isinstance(raw_rows, list):
                raise RuntimeError(f"Unexpected income payload for {income_type}: {raw_rows!r}")
            if not raw_rows:
                break

            for raw in raw_rows:
                tran_id = str(raw.get("tranId", ""))
                unique_key = (income_type, tran_id or f"{raw.get('time', '')}:{raw.get('tradeId', '')}")
                if unique_key in seen_keys:
                    continue
                seen_keys.add(unique_key)
                records.append(
                    IncomeRecord(
                        symbol=str(raw.get("symbol", "")),
                        income_type=str(raw.get("incomeType", income_type)),
                        income=float(raw.get("income", 0) or 0),
                        asset=str(raw.get("asset", "")),
                        info=str(raw.get("info", "")),
                        time=dt.datetime.fromtimestamp(float(raw["time"]) / 1000.0),
                        tran_id=tran_id,
                        trade_id=str(raw.get("tradeId", "")),
                    )
                )

            if len(raw_rows) < 1000:
                break
            cursor = int(raw_rows[-1]["time"]) + 1

    records.sort(key=lambda item: item.time, reverse=True)
    return records


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


def summarize_positions(
    positions: Iterable[PositionSnapshot],
    account: AccountSnapshot,
    income_summary: dict[str, float] | None = None,
) -> dict[str, float]:
    items = list(positions)
    long_value = sum(item.notional_value for item in items if item.quantity > 0)
    short_value = sum(item.notional_value for item in items if item.quantity < 0)
    total_value = long_value + short_value
    total_pnl = sum(item.unrealized_pnl for item in items)
    incomes = income_summary or {}
    net_realized_pnl = float(incomes.get("net_realized_pnl", 0) or 0)
    return {
        "position_count": float(len(items)),
        "long_value": long_value,
        "short_value": short_value,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "realized_pnl": float(incomes.get("realized_pnl", 0) or 0),
        "commission": float(incomes.get("commission", 0) or 0),
        "funding_fee": float(incomes.get("funding_fee", 0) or 0),
        "net_realized_pnl": net_realized_pnl,
        "total_trading_pnl": total_pnl + net_realized_pnl,
        "income_row_count": float(incomes.get("income_row_count", 0) or 0),
        "equity": account.margin_balance,
        "wallet_balance": account.wallet_balance,
        "available_balance": account.available_balance,
    }


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
    fieldnames = [
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
    with history_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
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
    merged.sort(key=lambda item: item["timestamp"])
    return merged


def write_positions_csv(positions_file: Path, positions: list[PositionSnapshot]) -> None:
    ensure_parent(positions_file)
    fieldnames = [
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
    with positions_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in positions:
            writer.writerow(
                {
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
            )


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
        merged.append(
            {
                "timestamp": target,
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
        )

    merged.sort(key=lambda item: (item.get("timestamp", ""), item.get("symbol", "")))
    return merged


def write_position_history_csv(position_history_file: Path, rows: list[dict[str, str]]) -> None:
    ensure_parent(position_history_file)
    fieldnames = [
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
    with position_history_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
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


def format_usd(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def extract_asset(symbol: str) -> str:
    for suffix in ("USDT", "USDC", "BUSD", "FDUSD"):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)] or symbol
    return re.sub(r"[^A-Z0-9\u4e00-\u9fff]+$", "", symbol) or symbol


def build_asset_groups(positions: list[PositionSnapshot]) -> list[dict[str, float | str | int]]:
    grouped: dict[str, dict[str, float | str | int]] = {}
    for item in positions:
        asset = extract_asset(item.symbol)
        bucket = grouped.setdefault(
            asset,
            {
                "asset": asset,
                "position_count": 0,
                "gross_value": 0.0,
                "long_value": 0.0,
                "short_value": 0.0,
                "unrealized_pnl": 0.0,
            },
        )
        bucket["position_count"] = int(bucket["position_count"]) + 1
        bucket["gross_value"] = float(bucket["gross_value"]) + item.notional_value
        bucket["unrealized_pnl"] = float(bucket["unrealized_pnl"]) + item.unrealized_pnl
        if item.quantity > 0:
            bucket["long_value"] = float(bucket["long_value"]) + item.notional_value
        else:
            bucket["short_value"] = float(bucket["short_value"]) + item.notional_value

    rows = list(grouped.values())
    rows.sort(key=lambda row: float(row["gross_value"]), reverse=True)
    return rows


def generate_chart(history_rows: list[dict[str, str]], chart_file: Path) -> None:
    if not history_rows:
        return

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
        from matplotlib import rcParams
    except ImportError as exc:
        raise RuntimeError(
            "matplotlib is required to render charts. Please run: pip install -r requirements.txt"
        ) from exc

    rcParams["axes.unicode_minus"] = False

    dates = [dt.datetime.fromisoformat(row["timestamp"]) for row in history_rows]
    total_values = [float(row["total_value"]) for row in history_rows]
    total_pnls = [float(row["total_pnl"]) for row in history_rows]
    equities = [float(row.get("equity", 0) or 0) for row in history_rows]

    ensure_parent(chart_file)
    fig, ax1 = plt.subplots(figsize=(12, 6.5), constrained_layout=True)
    ax1.plot(dates, total_values, color="#135D66", linewidth=2.5, marker="o")
    ax1.plot(dates, equities, color="#2A7F62", linewidth=2.2, marker="s")
    ax1.fill_between(dates, total_values, color="#8DD8C8", alpha=0.18)
    ax1.set_title("Futures Exposure and Equity Trend", fontsize=16, pad=14)
    ax1.set_ylabel("Exposure / Equity (USD)")
    ax1.grid(alpha=0.25, linestyle="--")
    ax1.yaxis.set_major_formatter(mticker.StrMethodFormatter("${x:,.0f}"))
    ax1.legend(["Gross Position Value", "Account Equity"], loc="upper left")

    ax2 = ax1.twinx()
    ax2.plot(dates, total_pnls, color="#E76F51", linewidth=2, linestyle="--")
    ax2.set_ylabel("Unrealized PnL (USD)")
    ax2.yaxis.set_major_formatter(mticker.StrMethodFormatter("${x:,.0f}"))

    fig.autofmt_xdate(rotation=25)
    fig.savefig(chart_file, dpi=180)
    plt.close(fig)


def render_html_report(
    html_file: Path,
    chart_file: Path,
    positions: list[PositionSnapshot],
    asset_groups: list[dict[str, float | str | int]],
    income_records: list[IncomeRecord],
    summary: dict[str, float],
    report_time: dt.datetime,
    realized_since: dt.datetime | None,
) -> None:
    ensure_parent(html_file)
    chart_name = html.escape(os.path.relpath(chart_file, start=html_file.parent))
    total_pnl_class = "pnl-pos" if summary["total_pnl"] >= 0 else "pnl-neg"
    net_realized_class = "pnl-pos" if summary["net_realized_pnl"] >= 0 else "pnl-neg"
    total_trading_class = "pnl-pos" if summary["total_trading_pnl"] >= 0 else "pnl-neg"

    rows = []
    for item in positions:
        pnl_class = "pnl-pos" if item.unrealized_pnl >= 0 else "pnl-neg"
        rows.append(
            f"""
            <tr>
              <td>{html.escape(item.symbol)}</td>
              <td>{html.escape(item.side)}</td>
              <td>{abs(item.quantity):.6f}</td>
              <td>{item.entry_price:,.4f}</td>
              <td>{item.mark_price:,.4f}</td>
              <td>{format_usd(item.notional_value)}</td>
              <td class="{pnl_class}">{format_usd(item.unrealized_pnl)}</td>
              <td class="{pnl_class}">{item.pnl_ratio * 100:,.2f}%</td>
              <td>{item.leverage:.0f}x</td>
              <td>{item.margin_type}</td>
            </tr>
            """.strip()
        )

    if not rows:
        rows.append(
            """
            <tr>
              <td colspan="10">No open futures positions.</td>
            </tr>
            """.strip()
        )

    group_rows = []
    for row in asset_groups:
        pnl_value = float(row["unrealized_pnl"])
        pnl_class = "pnl-pos" if pnl_value >= 0 else "pnl-neg"
        group_rows.append(
            f"""
            <tr>
              <td>{html.escape(str(row["asset"]))}</td>
              <td>{int(row["position_count"])}</td>
              <td>{format_usd(float(row["gross_value"]))}</td>
              <td>{format_usd(float(row["long_value"]))}</td>
              <td>{format_usd(float(row["short_value"]))}</td>
              <td class="{pnl_class}">{format_usd(pnl_value)}</td>
            </tr>
            """.strip()
        )

    if not group_rows:
        group_rows.append(
            """
            <tr>
              <td colspan="6">No grouped asset stats available.</td>
            </tr>
            """.strip()
        )

    income_rows = []
    income_labels = {
        "REALIZED_PNL": "已实现盈亏",
        "COMMISSION": "手续费",
        "FUNDING_FEE": "资金费",
    }
    for item in income_records[:120]:
        income_class = "pnl-pos" if item.income >= 0 else "pnl-neg"
        income_rows.append(
            f"""
            <tr>
              <td>{html.escape(item.time.strftime("%Y-%m-%d %H:%M:%S"))}</td>
              <td>{html.escape(item.symbol or "-")}</td>
              <td>{html.escape(income_labels.get(item.income_type, item.income_type))}</td>
              <td class="{income_class}">{format_usd(item.income)}</td>
              <td>{html.escape(item.asset or "-")}</td>
              <td>{html.escape(item.trade_id or "-")}</td>
            </tr>
            """.strip()
        )

    if not income_rows:
        income_rows.append(
            """
            <tr>
              <td colspan="6">No realized income rows in the selected window.</td>
            </tr>
            """.strip()
        )

    realized_window = (
        realized_since.strftime("%Y-%m-%d %H:%M:%S") if realized_since is not None else "未设置"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Binance 合约账户报表</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #1f2933;
      --muted: #66737f;
      --line: #ded6c8;
      --accent: #135d66;
      --accent-soft: #dcefeb;
      --green: #1f8a70;
      --red: #d1495b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "PingFang SC", "Noto Sans SC", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(19, 93, 102, 0.14), transparent 28%),
        linear-gradient(180deg, #f8f5ef 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    .page {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .hero {{
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 4vw, 42px);
      letter-spacing: -0.03em;
    }}
    .sub {{
      color: var(--muted);
      margin: 0;
      font-size: 15px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 24px 0 26px;
    }}
    .card {{
      background: rgba(255, 253, 248, 0.88);
      border: 1px solid rgba(222, 214, 200, 0.9);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(31, 41, 51, 0.05);
      backdrop-filter: blur(4px);
    }}
    .label {{
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .value {{
      font-size: 28px;
      font-weight: 700;
      letter-spacing: -0.03em;
    }}
    .chart-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 20px;
      margin-bottom: 22px;
      overflow: hidden;
    }}
    .chart-panel img {{
      width: 100%;
      display: block;
      border-radius: 16px;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      overflow: hidden;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
      font-size: 14px;
    }}
    th {{
      background: var(--accent-soft);
      color: var(--ink);
      font-weight: 700;
    }}
    th:first-child, td:first-child {{
      text-align: left;
    }}
    .pnl-pos {{
      color: var(--green);
      font-weight: 700;
    }}
    .pnl-neg {{
      color: var(--red);
      font-weight: 700;
    }}
    .footer {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 14px;
    }}
    @media (max-width: 900px) {{
      .table-wrap {{
        overflow-x: auto;
      }}
      th, td {{
        font-size: 13px;
        padding: 10px 12px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h1>Binance 合约账户报表</h1>
      <p class="sub">快照时间：{report_time.strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>

    <div class="summary">
      <div class="card">
        <div class="label">总仓位价值</div>
        <div class="value">{format_usd(summary["total_value"])}</div>
      </div>
      <div class="card">
        <div class="label">总未实现盈亏</div>
        <div class="value {total_pnl_class}">{format_usd(summary["total_pnl"])}</div>
      </div>
      <div class="card">
        <div class="label">账户权益</div>
        <div class="value">{format_usd(summary["equity"])}</div>
      </div>
      <div class="card">
        <div class="label">已实现净盈亏（自 {html.escape(realized_window)}）</div>
        <div class="value {net_realized_class}">{format_usd(summary["net_realized_pnl"])}</div>
      </div>
      <div class="card">
        <div class="label">总交易盈亏（已实现 + 未实现）</div>
        <div class="value {total_trading_class}">{format_usd(summary["total_trading_pnl"])}</div>
      </div>
      <div class="card">
        <div class="label">钱包余额</div>
        <div class="value">{format_usd(summary["wallet_balance"])}</div>
      </div>
      <div class="card">
        <div class="label">多头敞口</div>
        <div class="value">{format_usd(summary["long_value"])}</div>
      </div>
      <div class="card">
        <div class="label">空头敞口</div>
        <div class="value">{format_usd(summary["short_value"])}</div>
      </div>
      <div class="card">
        <div class="label">可用余额</div>
        <div class="value">{format_usd(summary["available_balance"])}</div>
      </div>
    </div>

    <div class="chart-panel">
      <img src="{chart_name}" alt="合约账户走势曲线图">
    </div>

    <div class="table-wrap" style="margin-bottom: 22px;">
      <table>
        <thead>
          <tr>
            <th>币种</th>
            <th>仓位数</th>
            <th>总仓位价值</th>
            <th>多头价值</th>
            <th>空头价值</th>
            <th>汇总盈亏</th>
          </tr>
        </thead>
        <tbody>
          {''.join(group_rows)}
        </tbody>
      </table>
    </div>

    <div class="table-wrap" style="margin-bottom: 22px;">
      <table>
        <thead>
          <tr>
            <th>时间</th>
            <th>交易对</th>
            <th>类型</th>
            <th>金额</th>
            <th>资产</th>
            <th>Trade ID</th>
          </tr>
        </thead>
        <tbody>
          {''.join(income_rows)}
        </tbody>
      </table>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>交易对</th>
            <th>方向</th>
            <th>数量</th>
            <th>开仓价</th>
            <th>标记价</th>
            <th>仓位价值</th>
            <th>未实现盈亏</th>
            <th>盈亏率</th>
            <th>杠杆</th>
            <th>保证金模式</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </div>

    <p class="footer">当前持仓数：{int(summary["position_count"])}。总仓位价值按每个非零持仓的 abs(数量 × 标记价格) 汇总计算。总交易盈亏 = 当前未实现盈亏 + 已实现盈亏 + 手续费 + 资金费；不包含充值划转等非交易流水。</p>
  </div>
</body>
</html>
"""
    html_file.write_text(html_body, encoding="utf-8")


def resolve_paths(args: argparse.Namespace) -> dict[str, Path]:
    output_dir = Path(args.output_dir)
    history_file = Path(args.history_file) if args.history_file else output_dir / "position_value_history.csv"
    chart_file = Path(args.chart_file) if args.chart_file else output_dir / "position_value_curve.png"
    positions_file = Path(args.positions_file) if args.positions_file else output_dir / "latest_positions.csv"
    position_history_file = (
        Path(args.position_history_file)
        if args.position_history_file
        else output_dir / "position_snapshots_history.csv"
    )
    html_file = Path(args.html_file) if args.html_file else output_dir / "daily_report.html"
    income_file = Path(args.income_file) if args.income_file else output_dir / "income_history.csv"
    return {
        "history": history_file,
        "chart": chart_file,
        "positions": positions_file,
        "position_history": position_history_file,
        "html": html_file,
        "income": income_file,
    }


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))

    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    base_url = os.getenv("BINANCE_FAPI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    realized_since_raw = args.realized_since or os.getenv("BINANCE_REALIZED_SINCE")

    if not api_key or not api_secret:
        print(
            "Missing BINANCE_API_KEY or BINANCE_API_SECRET. Set them in the environment or in the .env file.",
            file=sys.stderr,
        )
        return 1

    paths = resolve_paths(args)
    session = requests.Session()
    try:
        realized_since = parse_since_datetime(realized_since_raw)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        positions = fetch_positions(session, base_url, api_key, api_secret)
        account = fetch_account_snapshot(session, base_url, api_key, api_secret)
        existing_income_records = load_income_records(paths["income"])
        income_sync_start = determine_income_sync_start(existing_income_records, realized_since)
        fetched_income_records = fetch_income_history(
            session, base_url, api_key, api_secret, income_sync_start
        )
    except requests.HTTPError as exc:
        response_text = exc.response.text if exc.response is not None else str(exc)
        print(f"Binance API request failed: {response_text}", file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        print(f"Network error while calling Binance API: {exc}", file=sys.stderr)
        return 2

    now = dt.datetime.now()
    income_records = merge_income_records(
        existing_income_records, fetched_income_records, realized_since
    )
    income_summary = summarize_income(income_records)
    summary = summarize_positions(positions, account, income_summary)
    asset_groups = build_asset_groups(positions)
    history_rows = upsert_history_row(load_history(paths["history"]), now, summary)
    position_history_rows = upsert_position_history_rows(
        load_position_history(paths["position_history"]), now, positions
    )

    write_history(paths["history"], history_rows)
    write_positions_csv(paths["positions"], positions)
    write_position_history_csv(paths["position_history"], position_history_rows)
    write_income_csv(paths["income"], income_records)
    generate_chart(history_rows, paths["chart"])
    render_html_report(
        paths["html"],
        paths["chart"],
        positions,
        asset_groups,
        income_records,
        summary,
        now,
        realized_since,
    )

    print(f"History CSV: {paths['history']}")
    print(f"Chart PNG:   {paths['chart']}")
    print(f"Positions:   {paths['positions']}")
    print(f"Pos hist:    {paths['position_history']}")
    print(f"Income CSV:  {paths['income']}")
    print(f"HTML report: {paths['html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
