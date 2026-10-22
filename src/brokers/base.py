"""
Broker abstraction.

Every broker (Interactive Brokers, MT5, in-memory paper) implements
``BrokerClient`` so the execution layer and the market-data layer do not
depend on any vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.models.signals import OHLCV


class BrokerError(Exception):
    """Raised when a broker operation fails."""


class BrokerNotConnectedError(BrokerError):
    """Raised when an operation needs a live broker connection."""


@dataclass
class BrokerOrderResult:
    """Normalized result of an order submitted to a broker."""

    order_id: str
    symbol: str
    side: str  # "BUY" | "SELL"
    status: str  # "filled" | "partial" | "rejected" | "pending"
    requested_quantity: float
    filled_quantity: float
    avg_fill_price: float
    stop_loss_order_id: Optional[str] = None
    take_profit_order_id: Optional[str] = None
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "status": self.status,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "stop_loss_order_id": self.stop_loss_order_id,
            "take_profit_order_id": self.take_profit_order_id,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class MarketDataProvider(ABC):
    """Anything that can return historical candles."""

    name: str = "base"

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
        end_time: Optional[datetime] = None,
    ) -> list[OHLCV]:
        """Return up to ``count`` *completed* candles, ascending by time."""


class BrokerClient(MarketDataProvider):
    """Full broker interface: market data + order management."""

    name: str = "broker"

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @property
    def is_paper(self) -> bool:
        return True

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    async def ensure_connected(self) -> None:
        if not self.is_connected:
            await self.connect()

    @abstractmethod
    async def get_current_price(self, symbol: str) -> Optional[dict]:
        """Return ``{bid, ask, last, mid, timestamp}`` or None."""

    @abstractmethod
    async def place_bracket_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        reference: str = "",
    ) -> BrokerOrderResult:
        """Market entry with attached stop-loss and take-profit (OCO) orders."""

    @abstractmethod
    async def modify_protective_orders(
        self,
        order_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        """Modify SL/TP of a bracket identified by its parent order id."""

    @abstractmethod
    async def close_position(self, symbol: str) -> BrokerOrderResult:
        """Flatten the position in ``symbol`` and cancel its working child orders."""

    @abstractmethod
    async def get_open_positions(self) -> list[dict]:
        """Return ``[{symbol, quantity, side, avg_cost, ...}]``."""

    @abstractmethod
    async def get_account_info(self) -> dict:
        """Return ``{balance, equity, free_margin, currency, ...}``."""

    async def health(self) -> dict:
        return {"broker": self.name, "connected": self.is_connected, "paper": self.is_paper}
