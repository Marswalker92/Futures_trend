from __future__ import annotations

import datetime as dt
import os
from pathlib import Path


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
