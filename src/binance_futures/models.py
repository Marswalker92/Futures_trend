from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


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
