from __future__ import annotations

import datetime as dt
import html
import os
from pathlib import Path

from .html_sections import build_asset_group_rows, build_income_rows, build_position_rows
from .html_template import build_report_html
from .models import IncomeRecord, PositionSnapshot
from .storage import ensure_parent


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
    realized_window = (
        realized_since.strftime("%Y-%m-%d %H:%M:%S") if realized_since is not None else "未设置"
    )
    html_body = build_report_html(
        chart_name=chart_name,
        rows=build_position_rows(positions),
        group_rows=build_asset_group_rows(asset_groups),
        income_rows=build_income_rows(income_records),
        summary=summary,
        report_time=report_time,
        realized_window=realized_window,
    )
    html_file.write_text(html_body, encoding="utf-8")
