#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

import requests

from binance_futures.binance_api import (
    DEFAULT_BASE_URL,
    fetch_account_snapshot,
    fetch_income_history,
    fetch_positions,
)
from binance_futures.cli import parse_args, resolve_paths
from binance_futures.config import load_env_file, parse_since_datetime
from binance_futures.income import (
    determine_income_sync_start,
    load_income_records,
    merge_income_records,
    summarize_income,
)
from binance_futures.reporting import (
    build_asset_groups,
    generate_chart,
    render_html_report,
    summarize_positions,
)
from binance_futures.storage import (
    load_history,
    load_position_history,
    upsert_history_row,
    upsert_position_history_rows,
    write_history,
    write_income_csv,
    write_position_history_csv,
    write_positions_csv,
)


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
