from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Iterable

from .html_report import render_html_report
from .models import AccountSnapshot, PositionSnapshot
from .storage import ensure_parent


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


def extract_asset(symbol: str) -> str:
    for suffix in ("USDT", "USDC", "BUSD", "FDUSD"):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)] or symbol
    return re.sub(r"[^A-Z0-9一-鿿]+$", "", symbol) or symbol


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
