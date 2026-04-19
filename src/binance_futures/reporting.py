from __future__ import annotations

import datetime as dt
import html
import os
import re
from pathlib import Path
from typing import Iterable

from .models import AccountSnapshot, IncomeRecord, PositionSnapshot
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


def format_usd(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


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
