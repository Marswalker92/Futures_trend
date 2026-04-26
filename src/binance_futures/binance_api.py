from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import time
from typing import Iterable
from urllib.parse import urlencode

import requests

from .models import AccountSnapshot, IncomeRecord, PositionSnapshot

DEFAULT_BASE_URL = "https://fapi.binance.com"


def expect_dict(payload: object, endpoint: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected {endpoint} payload: {payload!r}")
    return payload


def expect_list(payload: object, endpoint: str) -> list[object]:
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected {endpoint} payload: {payload!r}")
    return payload


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
    raw_positions = expect_list(
        signed_get(
            session,
            base_url,
            "/fapi/v2/positionRisk",
            api_key,
            api_secret,
        ),
        "/fapi/v2/positionRisk",
    )

    positions: list[PositionSnapshot] = []
    for raw in raw_positions:
        if not isinstance(raw, dict):
            raise RuntimeError(f"Unexpected position row: {raw!r}")
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
    raw_account = expect_dict(
        signed_get(
            session,
            base_url,
            "/fapi/v2/account",
            api_key,
            api_secret,
        ),
        "/fapi/v2/account",
    )
    return AccountSnapshot(
        wallet_balance=float(raw_account["totalWalletBalance"]),
        unrealized_pnl=float(raw_account["totalUnrealizedProfit"]),
        margin_balance=float(raw_account["totalMarginBalance"]),
        available_balance=float(raw_account["availableBalance"]),
    )


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
            raw_rows = expect_list(
                signed_get(
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
                ),
                f"/fapi/v1/income:{income_type}",
            )
            if not raw_rows:
                break

            for raw in raw_rows:
                if not isinstance(raw, dict):
                    raise RuntimeError(f"Unexpected income row for {income_type}: {raw!r}")
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
