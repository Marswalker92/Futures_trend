from __future__ import annotations

import html

from .formatting import format_usd
from .models import IncomeRecord, PositionSnapshot


def build_position_rows(positions: list[PositionSnapshot]) -> list[str]:
    rows: list[str] = []
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

    if rows:
        return rows

    return [
        """
        <tr>
          <td colspan="10">No open futures positions.</td>
        </tr>
        """.strip()
    ]


def build_asset_group_rows(asset_groups: list[dict[str, float | str | int]]) -> list[str]:
    rows: list[str] = []
    for row in asset_groups:
        pnl_value = float(row["unrealized_pnl"])
        pnl_class = "pnl-pos" if pnl_value >= 0 else "pnl-neg"
        rows.append(
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

    if rows:
        return rows

    return [
        """
        <tr>
          <td colspan="6">No grouped asset stats available.</td>
        </tr>
        """.strip()
    ]


def build_income_rows(income_records: list[IncomeRecord]) -> list[str]:
    rows: list[str] = []
    income_labels = {
        "REALIZED_PNL": "已实现盈亏",
        "COMMISSION": "手续费",
        "FUNDING_FEE": "资金费",
    }
    for item in income_records[:120]:
        income_class = "pnl-pos" if item.income >= 0 else "pnl-neg"
        rows.append(
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

    if rows:
        return rows

    return [
        """
        <tr>
          <td colspan="6">No realized income rows in the selected window.</td>
        </tr>
        """.strip()
    ]
