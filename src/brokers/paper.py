"""
In-memory paper broker.

Fills market orders instantly at the latest price from a ``MarketDataProvider``
(Yahoo, IBKR, synthetic …) and simulates bracket SL/TP via ``mark_to_market``.
Used for local development / CI and when IB Gateway is not running.
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.models.signals import OHLCV

from .base import BrokerClient, BrokerError, BrokerOrderResult, MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass
class _PaperPosition:
    order_id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PaperBroker(BrokerClient):
    name = "paper"

    def __init__(
        self,
        data_provider: Optional[MarketDataProvider] = None,
        starting_cash: float = 100_000.0,
        commission_pct: float = 0.0005,
    ):
        self._data = data_provider
        self._cash = starting_cash
        self._commission_pct = commission_pct
        self._positions: dict[str, _PaperPosition] = {}
        self._prices: dict[str, float] = {}
        self._ids = itertools.count(1)
        self._connected = False
        self.closed_trades: list[dict] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol.upper()] = price

    async def get_candles(self, symbol, timeframe, count, end_time=None) -> list[OHLCV]:
        if self._data is None:
            raise BrokerError("PaperBroker has no data provider configured")
        return await self._data.get_candles(symbol, timeframe, count, end_time)

    async def get_current_price(self, symbol: str) -> Optional[dict]:
        sym = symbol.upper()
        price = self._prices.get(sym)
        if price is None and self._data is not None:
            candles = await self._data.get_candles(sym, "M5", 3)
            price = candles[-1].close if candles else None
        if price is None:
            return None
        return {
            "bid": price, "ask": price, "last": price, "mid": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def place_bracket_order(
        self, symbol, side, quantity, stop_loss, take_profit, reference=""
    ) -> BrokerOrderResult:
        sym, side = symbol.upper(), side.upper()
        if sym in self._positions:
            raise BrokerError(f"Paper broker already has an open position in {sym}")
        quote = await self.get_current_price(sym)
        if quote is None:
            raise BrokerError(f"No price for {sym}")
        price = quote["ask"] if side == "BUY" else quote["bid"]
        oid = str(next(self._ids))
        self._positions[sym] = _PaperPosition(oid, sym, side, quantity, price, stop_loss, take_profit)
        self._cash -= price * quantity * self._commission_pct
        return BrokerOrderResult(
            order_id=oid, symbol=sym, side=side, status="filled",
            requested_quantity=quantity, filled_quantity=quantity, avg_fill_price=price,
            stop_loss_order_id=f"{oid}-sl", take_profit_order_id=f"{oid}-tp",
            message="paper fill",
        )

    async def modify_protective_orders(self, order_id, stop_loss=None, take_profit=None) -> bool:
        for p in self._positions.values():
            if p.order_id == order_id:
                if stop_loss is not None:
                    p.stop_loss = stop_loss
                if take_profit is not None:
                    p.take_profit = take_profit
                return True
        return False

    def _realize(self, p: _PaperPosition, price: float, reason: str) -> float:
        sign = 1 if p.side == "BUY" else -1
        pnl = (price - p.entry_price) * p.quantity * sign
        pnl -= price * p.quantity * self._commission_pct
        self._cash += pnl
        self.closed_trades.append(
            {"symbol": p.symbol, "side": p.side, "entry": p.entry_price, "exit": price,
             "quantity": p.quantity, "pnl": pnl, "reason": reason}
        )
        return pnl

    async def close_position(self, symbol: str) -> BrokerOrderResult:
        sym = symbol.upper()
        p = self._positions.pop(sym, None)
        if p is None:
            raise BrokerError(f"No open paper position for {sym}")
        quote = await self.get_current_price(sym)
        price = quote["mid"] if quote else p.entry_price
        self._realize(p, price, "manual")
        return BrokerOrderResult(
            order_id=str(next(self._ids)), symbol=sym,
            side="SELL" if p.side == "BUY" else "BUY", status="filled",
            requested_quantity=p.quantity, filled_quantity=p.quantity, avg_fill_price=price,
        )

    def mark_to_market(self, symbol: str, high: float, low: float) -> Optional[str]:
        """Apply a bar's range to an open bracket; returns 'sl'/'tp' if it closed."""
        p = self._positions.get(symbol.upper())
        if p is None:
            return None
        if p.side == "BUY":
            hit = ("sl", p.stop_loss) if low <= p.stop_loss else (
                ("tp", p.take_profit) if high >= p.take_profit else None)
        else:
            hit = ("sl", p.stop_loss) if high >= p.stop_loss else (
                ("tp", p.take_profit) if low <= p.take_profit else None)
        if hit:
            self._positions.pop(p.symbol)
            self._realize(p, hit[1], hit[0])
            return hit[0]
        return None

    async def get_open_positions(self) -> list[dict]:
        return [
            {"symbol": p.symbol, "quantity": p.quantity, "side": p.side.lower(),
             "avg_cost": p.entry_price, "stop_loss": p.stop_loss,
             "take_profit": p.take_profit, "order_id": p.order_id}
            for p in self._positions.values()
        ]

    async def get_account_info(self) -> dict:
        unreal = 0.0
        for p in self._positions.values():
            px = self._prices.get(p.symbol, p.entry_price)
            unreal += (px - p.entry_price) * p.quantity * (1 if p.side == "BUY" else -1)
        return {
            "balance": self._cash, "equity": self._cash + unreal, "margin": 0.0,
            "free_margin": self._cash, "unrealized_pnl": unreal, "currency": "USD",
            "paper": True, "mode": "paper",
        }
