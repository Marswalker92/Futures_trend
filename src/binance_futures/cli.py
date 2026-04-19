from __future__ import annotations

import argparse
from pathlib import Path


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
