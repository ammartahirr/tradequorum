"""
Process-wide broker + market-data provider registry.

BROKER=ibkr   -> Interactive Brokers via IB Gateway/TWS (paper by default)
BROKER=paper  -> in-memory simulator priced from DEFAULT_DATA_SOURCE
"""
import logging
from typing import Optional

from core.config import settings
from src.brokers import (
    BrokerClient,
    IBKRClient,
    IBKRConfig,
    MarketDataProvider,
    PaperBroker,
    SyntheticDataProvider,
    YahooDataProvider,
)

logger = logging.getLogger(__name__)

_broker: Optional[BrokerClient] = None
_ibkr: Optional[IBKRClient] = None
_providers: dict[str, MarketDataProvider] = {}


def get_ibkr_client() -> IBKRClient:
    global _ibkr
    if _ibkr is None:
        _ibkr = IBKRClient(
            IBKRConfig(
                host=settings.IBKR_HOST,
                port=settings.IBKR_PORT,
                client_id=settings.IBKR_CLIENT_ID,
                account=settings.IBKR_ACCOUNT,
                market_data_type=settings.IBKR_MARKET_DATA_TYPE,
                readonly=settings.IBKR_READONLY,
                allow_live_trading=settings.IBKR_ALLOW_LIVE_TRADING,
            )
        )
    return _ibkr


def get_data_provider(name: Optional[str] = None) -> MarketDataProvider:
    name = (name or settings.DEFAULT_DATA_SOURCE).lower()
    if name == "ibkr":
        return get_ibkr_client()
    if name not in _providers:
        if name == "yahoo":
            _providers[name] = YahooDataProvider()
        elif name == "synthetic":
            _providers[name] = SyntheticDataProvider()
        else:
            raise ValueError(f"Unknown data source '{name}' (use ibkr, yahoo or synthetic)")
    return _providers[name]


def get_broker() -> BrokerClient:
    global _broker
    if _broker is None:
        kind = settings.BROKER.lower()
        if kind == "ibkr":
            _broker = get_ibkr_client()
        elif kind == "paper":
            _broker = PaperBroker(data_provider=get_data_provider())
        else:
            raise ValueError(
                f"BROKER={settings.BROKER!r} is not supported by the API server "
                "(use 'ibkr' or 'paper'; MT5 only runs on Windows)"
            )
        logger.info(f"Broker selected: {_broker.name}")
    return _broker


async def connect_broker() -> None:
    """Best-effort connect at startup – the API stays up if the gateway is down."""
    try:
        broker = get_broker()
        await broker.connect()
    except Exception as e:
        logger.warning(f"Broker not connected at startup (will retry on demand): {e}")


async def disconnect_broker() -> None:
    if _broker is not None:
        try:
            await _broker.disconnect()
        except Exception:
            pass
