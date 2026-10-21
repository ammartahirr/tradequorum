"""
Interactive Brokers client (TWS / IB Gateway) built on ``ib_async``.

Defaults are paper-trading safe:
- connects to IB Gateway paper port 4002 (TWS paper = 7497)
- refuses to place orders on a non-paper account (account ids starting with
  ``DU``/``DF`` are paper) unless ``IBKR_ALLOW_LIVE_TRADING=true``

Environment variables (see ``IBKRConfig.from_env``):
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, IBKR_ACCOUNT,
    IBKR_MARKET_DATA_TYPE, IBKR_READONLY, IBKR_ALLOW_LIVE_TRADING,
    IBKR_CONNECT_TIMEOUT, IBKR_ORDER_FILL_TIMEOUT
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from src.agents.technical.config import SUPPORTED_TIMEFRAMES, TIMEFRAME_MINUTES
from src.models.signals import OHLCV

from .base import BrokerClient, BrokerError, BrokerNotConnectedError, BrokerOrderResult
from .symbols import IB_BAR_SIZES, AssetSpec, ib_duration, parse_symbol

logger = logging.getLogger(__name__)

LIVE_PORTS = {4001, 7496}

# IB error codes that mean "you have no market-data permission for this"
_MARKET_DATA_ERRORS = {162, 354, 10089, 10090, 10167, 10168, 10197}


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4002  # IB Gateway paper
    client_id: int = 17
    account: str = ""
    # 1=live, 2=frozen, 3=delayed, 4=delayed-frozen. Delayed works without subscriptions.
    market_data_type: int = 3
    readonly: bool = False
    allow_live_trading: bool = False
    connect_timeout: float = 15.0
    order_fill_timeout: float = 20.0
    use_rth: bool = False

    @classmethod
    def from_env(cls) -> "IBKRConfig":
        return cls(
            host=os.environ.get("IBKR_HOST", cls.host),
            port=int(os.environ.get("IBKR_PORT", cls.port)),
            client_id=int(os.environ.get("IBKR_CLIENT_ID", cls.client_id)),
            account=os.environ.get("IBKR_ACCOUNT", ""),
            market_data_type=int(os.environ.get("IBKR_MARKET_DATA_TYPE", cls.market_data_type)),
            readonly=_env_bool("IBKR_READONLY", False),
            allow_live_trading=_env_bool("IBKR_ALLOW_LIVE_TRADING", False),
            connect_timeout=float(os.environ.get("IBKR_CONNECT_TIMEOUT", cls.connect_timeout)),
            order_fill_timeout=float(
                os.environ.get("IBKR_ORDER_FILL_TIMEOUT", cls.order_fill_timeout)
            ),
            use_rth=_env_bool("IBKR_USE_RTH", False),
        )


def _what_to_show(asset: AssetSpec) -> str:
    return {
        "stock": "TRADES",
        "forex": "MIDPOINT",
        "crypto": "AGGTRADES",
        "metal": "MIDPOINT",
    }[asset.asset_class]


def _bar_start_utc(bar_date: Any) -> datetime:
    if isinstance(bar_date, datetime):
        return bar_date if bar_date.tzinfo else bar_date.replace(tzinfo=timezone.utc)
    if isinstance(bar_date, date):
        return datetime.combine(bar_date, time(0, 0), tzinfo=timezone.utc)
    raise BrokerError(f"Unexpected IB bar date: {bar_date!r}")


def bars_to_ohlcv(bars: list[Any], timeframe: str, now: Optional[datetime] = None) -> list[OHLCV]:
    """Convert ib_async BarData to OHLCV, dropping the still-forming bar."""
    now = now or datetime.now(timezone.utc)
    step = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    out: list[OHLCV] = []
    for b in bars:
        ts = _bar_start_utc(b.date)
        if ts + step > now:
            continue  # incomplete candle
        o, h, l, c = float(b.open), float(b.high), float(b.low), float(b.close)
        if min(o, h, l, c) <= 0 or any(math.isnan(x) for x in (o, h, l, c)):
            continue
        out.append(
            OHLCV(
                timestamp=ts,
                open=o,
                high=max(o, h, l, c),
                low=min(o, h, l, c),
                close=c,
                volume=max(0, int(b.volume or 0)),
            )
        )
    out.sort(key=lambda x: x.timestamp)
    return out


class IBKRClient(BrokerClient):
    """Interactive Brokers broker + market data client."""

    name = "ibkr"

    def __init__(self, config: Optional[IBKRConfig] = None, ib: Any = None):
        self.config = config or IBKRConfig.from_env()
        self._ib = ib  # injectable for tests
        self._lock = asyncio.Lock()
        self._contracts: dict[str, Any] = {}
        self._min_ticks: dict[str, float] = {}
        self._errors: deque = deque(maxlen=50)

    # ------------------------------------------------------------------ setup
    def _ensure_ib(self) -> Any:
        if self._ib is None:
            try:
                from ib_async import IB
            except ImportError as e:  # pragma: no cover
                raise BrokerError("ib_async is not installed: pip install ib_async") from e
            self._ib = IB()
            self._ib.errorEvent += self._on_error
        return self._ib

    def _on_error(self, req_id: int, code: int, message: str, contract: Any = None) -> None:
        # 2104/2106/2158 etc. are informational "data farm OK" messages
        if code in {2104, 2106, 2107, 2108, 2158, 2119}:
            return
        self._errors.append((req_id, code, message))
        logger.warning(f"IB error {code} (req {req_id}): {message}")

    @property
    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    @property
    def accounts(self) -> list[str]:
        if not self.is_connected:
            return []
        return list(self._ib.managedAccounts())

    @property
    def is_paper(self) -> bool:
        accts = self.accounts
        if accts:
            return all(a.upper().startswith(("DU", "DF")) for a in accts)
        return self.config.port not in LIVE_PORTS

    async def connect(self) -> bool:
        async with self._lock:
            if self.is_connected:
                return True
            ib = self._ensure_ib()
            try:
                await ib.connectAsync(
                    self.config.host,
                    self.config.port,
                    clientId=self.config.client_id,
                    timeout=self.config.connect_timeout,
                    readonly=self.config.readonly,
                    account=self.config.account,
                )
            except Exception as e:
                raise BrokerNotConnectedError(
                    f"Could not connect to IB Gateway/TWS at "
                    f"{self.config.host}:{self.config.port} (clientId {self.config.client_id}): {e}. "
                    "Is the gateway running, logged in, and is the API enabled?"
                ) from e
            ib.reqMarketDataType(self.config.market_data_type)
            logger.info(
                f"Connected to IBKR {self.config.host}:{self.config.port} "
                f"accounts={self.accounts} paper={self.is_paper}"
            )
            return True

    async def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    async def health(self) -> dict:
        return {
            "broker": self.name,
            "connected": self.is_connected,
            "paper": self.is_paper,
            "accounts": self.accounts,
            "host": self.config.host,
            "port": self.config.port,
            "client_id": self.config.client_id,
            "recent_errors": [
                {"code": c, "message": m} for _, c, m in list(self._errors)[-5:]
            ],
        }

    # -------------------------------------------------------------- contracts
    def _build_contract(self, asset: AssetSpec) -> Any:
        from ib_async import Contract, Crypto, Forex, Stock

        if asset.asset_class == "forex":
            return Forex(asset.symbol)
        if asset.asset_class == "crypto":
            return Crypto(asset.base, "PAXOS", asset.quote)
        if asset.asset_class == "metal":
            return Contract(
                secType="CMDTY", symbol=asset.symbol, exchange="SMART", currency=asset.quote
            )
        return Stock(asset.symbol, "SMART", "USD")

    async def _contract(self, symbol: str) -> tuple[Any, AssetSpec]:
        await self.ensure_connected()
        asset = parse_symbol(symbol)
        if asset.symbol not in self._contracts:
            contract = self._build_contract(asset)
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified or qualified[0] is None or not getattr(qualified[0], "conId", 0):
                raise BrokerError(f"IB could not resolve contract for {symbol}")
            self._contracts[asset.symbol] = qualified[0]
        return self._contracts[asset.symbol], asset

    async def _min_tick(self, symbol: str, contract: Any) -> float:
        if symbol not in self._min_ticks:
            try:
                details = await self._ib.reqContractDetailsAsync(contract)
                self._min_ticks[symbol] = float(details[0].minTick) if details else 0.01
            except Exception:
                self._min_ticks[symbol] = 0.01
        return self._min_ticks[symbol]

    @staticmethod
    def _round_to_tick(price: float, tick: float) -> float:
        if tick <= 0:
            return round(price, 8)
        return round(round(price / tick) * tick, 8)

    @staticmethod
    def _normalize_qty(quantity: float, asset: AssetSpec) -> float:
        if asset.asset_class in {"stock", "forex"}:
            return float(math.floor(quantity))
        return round(quantity, 4)

    # ------------------------------------------------------------ market data
    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int,
        end_time: Optional[datetime] = None,
    ) -> list[OHLCV]:
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe {timeframe}")
        contract, asset = await self._contract(symbol)
        n_err = len(self._errors)
        bars = await self._ib.reqHistoricalDataAsync(
            contract,
            endDateTime=end_time or "",
            durationStr=ib_duration(timeframe, count, asset),
            barSizeSetting=IB_BAR_SIZES[timeframe],
            whatToShow=_what_to_show(asset),
            useRTH=self.config.use_rth,
            formatDate=2,  # UTC
        )
        candles = bars_to_ohlcv(list(bars or []), timeframe)
        if not candles:
            new_errors = list(self._errors)[n_err:]
            detail = "; ".join(f"{c}: {m}" for _, c, m in new_errors) or "no bars returned"
            hint = ""
            if any(c in _MARKET_DATA_ERRORS for _, c, _m in new_errors):
                hint = (
                    " – your IBKR account lacks a market-data subscription for this "
                    "instrument. Enable sharing of live subscriptions with the paper "
                    "account, or use data_source='yahoo'."
                )
            raise BrokerError(f"IB historical data for {symbol} failed: {detail}{hint}")
        return candles[-count:]

    async def get_current_price(self, symbol: str) -> Optional[dict]:
        contract, _ = await self._contract(symbol)
        tickers = await self._ib.reqTickersAsync(contract)
        if not tickers:
            return None
        t = tickers[0]

        def clean(v: Any) -> Optional[float]:
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return None if math.isnan(f) or f <= 0 else f

        bid, ask, last = clean(t.bid), clean(t.ask), clean(t.last)
        mid = (bid + ask) / 2 if bid and ask else (last or clean(t.close))
        if mid is None:
            return None
        return {
            "bid": bid or mid,
            "ask": ask or mid,
            "last": last or mid,
            "mid": mid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ---------------------------------------------------------------- trading
    def _assert_can_trade(self) -> None:
        if self.config.readonly:
            raise BrokerError("IBKR client is in read-only mode (IBKR_READONLY=true)")
        if not self.is_paper and not self.config.allow_live_trading:
            raise BrokerError(
                f"Refusing to trade: connected account(s) {self.accounts} are LIVE. "
                "Set IBKR_ALLOW_LIVE_TRADING=true only when you are ready for real money."
            )

    async def place_bracket_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        reference: str = "",
    ) -> BrokerOrderResult:
        from ib_async import LimitOrder, MarketOrder, StopOrder

        side = side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        contract, asset = await self._contract(symbol)
        self._assert_can_trade()

        qty = self._normalize_qty(quantity, asset)
        if qty <= 0:
            raise BrokerError(f"Order quantity for {symbol} rounds to 0 (requested {quantity})")

        tick = await self._min_tick(asset.symbol, contract)
        sl = self._round_to_tick(stop_loss, tick)
        tp = self._round_to_tick(take_profit, tick)
        exit_side = "SELL" if side == "BUY" else "BUY"
        ref = (reference or "tradequorum")[:40]
        client = self._ib.client

        parent = MarketOrder(side, qty, orderId=client.getReqId(), transmit=False, orderRef=ref)
        tp_order = LimitOrder(
            exit_side, qty, tp, orderId=client.getReqId(), parentId=parent.orderId,
            transmit=False, tif="GTC", orderRef=ref,
        )
        sl_order = StopOrder(
            exit_side, qty, sl, orderId=client.getReqId(), parentId=parent.orderId,
            transmit=True, tif="GTC", orderRef=ref,
        )

        parent_trade = self._ib.placeOrder(contract, parent)
        self._ib.placeOrder(contract, tp_order)
        self._ib.placeOrder(contract, sl_order)

        deadline = asyncio.get_running_loop().time() + self.config.order_fill_timeout
        while not parent_trade.isDone() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.25)

        st = parent_trade.orderStatus
        filled = float(st.filled or 0)
        if st.status == "Filled":
            status = "filled"
        elif st.status in {"Cancelled", "ApiCancelled", "Inactive"}:
            status = "rejected"
        elif filled > 0:
            status = "partial"
        else:
            status = "pending"  # e.g. market closed – order queued at IB

        msgs = [e.message for e in parent_trade.log if getattr(e, "message", "")]
        return BrokerOrderResult(
            order_id=str(parent.orderId),
            symbol=asset.symbol,
            side=side,
            status=status,
            requested_quantity=qty,
            filled_quantity=filled,
            avg_fill_price=float(st.avgFillPrice or 0.0),
            stop_loss_order_id=str(sl_order.orderId),
            take_profit_order_id=str(tp_order.orderId),
            message=f"IB status={st.status}" + (f" ({msgs[-1]})" if msgs else ""),
        )

    async def modify_protective_orders(
        self,
        order_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> bool:
        await self.ensure_connected()
        self._assert_can_trade()
        parent_id = int(order_id)
        changed = False
        for trade in self._ib.openTrades():
            order = trade.order
            if order.parentId != parent_id:
                continue
            tick = await self._min_tick(trade.contract.symbol, trade.contract)
            if order.orderType == "STP" and stop_loss is not None:
                order.auxPrice = self._round_to_tick(stop_loss, tick)
            elif order.orderType == "LMT" and take_profit is not None:
                order.lmtPrice = self._round_to_tick(take_profit, tick)
            else:
                continue
            self._ib.placeOrder(trade.contract, order)
            changed = True
        return changed

    @staticmethod
    def _position_symbol(contract: Any) -> str:
        if contract.secType in {"CASH", "CRYPTO"}:
            return f"{contract.symbol}{contract.currency}"
        return contract.symbol

    async def close_position(self, symbol: str) -> BrokerOrderResult:
        from ib_async import MarketOrder

        await self.ensure_connected()
        self._assert_can_trade()
        asset = parse_symbol(symbol)
        pos = next(
            (p for p in self._ib.positions() if self._position_symbol(p.contract) == asset.symbol
             and p.position != 0),
            None,
        )
        if pos is None:
            raise BrokerError(f"No open IBKR position for {symbol}")

        # Cancel working bracket children for this contract first
        for trade in self._ib.openTrades():
            if trade.contract.conId == pos.contract.conId:
                self._ib.cancelOrder(trade.order)

        contract, _ = await self._contract(symbol)
        side = "SELL" if pos.position > 0 else "BUY"
        qty = abs(float(pos.position))
        trade = self._ib.placeOrder(contract, MarketOrder(side, qty, orderRef="tradequorum-close"))
        deadline = asyncio.get_running_loop().time() + self.config.order_fill_timeout
        while not trade.isDone() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.25)
        st = trade.orderStatus
        return BrokerOrderResult(
            order_id=str(trade.order.orderId),
            symbol=asset.symbol,
            side=side,
            status="filled" if st.status == "Filled" else "pending",
            requested_quantity=qty,
            filled_quantity=float(st.filled or 0),
            avg_fill_price=float(st.avgFillPrice or 0.0),
            message=f"IB status={st.status}",
        )

    async def get_open_positions(self) -> list[dict]:
        await self.ensure_connected()
        out = []
        for p in self._ib.positions():
            if p.position == 0:
                continue
            out.append(
                {
                    "symbol": self._position_symbol(p.contract),
                    "sec_type": p.contract.secType,
                    "quantity": abs(float(p.position)),
                    "side": "buy" if p.position > 0 else "sell",
                    "avg_cost": float(p.avgCost),
                    "account": p.account,
                    "con_id": p.contract.conId,
                }
            )
        return out

    async def get_account_info(self) -> dict:
        await self.ensure_connected()
        values = await self._ib.accountSummaryAsync(self.config.account)
        tags: dict[str, float] = {}
        currency = "USD"
        for v in values:
            try:
                tags[v.tag] = float(v.value)
            except (TypeError, ValueError):
                continue
            if v.tag == "NetLiquidation" and v.currency:
                currency = v.currency
        return {
            "balance": tags.get("TotalCashValue", 0.0),
            "equity": tags.get("NetLiquidation", 0.0),
            "margin": tags.get("InitMarginReq", 0.0),
            "free_margin": tags.get("AvailableFunds", 0.0),
            "buying_power": tags.get("BuyingPower", 0.0),
            "unrealized_pnl": tags.get("UnrealizedPnL", 0.0),
            "realized_pnl": tags.get("RealizedPnL", 0.0),
            "currency": currency,
            "accounts": self.accounts,
            "paper": self.is_paper,
            "mode": "ibkr",
        }
