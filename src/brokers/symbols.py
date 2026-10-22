"""
Symbol / timeframe normalisation shared by all data providers.

The bot uses broker-neutral symbols such as ``AAPL``, ``EURUSD``, ``BTCUSD``
and ``XAUUSD``. Each provider maps them to its own contract format.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.agents.technical.config import TIMEFRAME_MINUTES

FIAT = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK", "HKD", "SGD"}
CRYPTO = {"BTC", "ETH", "LTC", "BCH"}
METALS = {"XAU", "XAG"}


@dataclass(frozen=True)
class AssetSpec:
    """Broker-neutral description of a tradable symbol."""

    symbol: str
    asset_class: str  # "stock" | "forex" | "crypto" | "metal"
    base: str
    quote: str = "USD"

    @property
    def trades_24h(self) -> bool:
        return self.asset_class in {"forex", "crypto", "metal"}


def parse_symbol(symbol: str) -> AssetSpec:
    """Classify a symbol such as ``EURUSD``, ``BTCUSD``, ``XAUUSD`` or ``AAPL``."""
    s = symbol.upper().replace("/", "").replace("-", "").strip()
    if len(s) == 6:
        base, quote = s[:3], s[3:]
        if base in CRYPTO and quote in FIAT:
            return AssetSpec(s, "crypto", base, quote)
        if base in METALS and quote in FIAT:
            return AssetSpec(s, "metal", base, quote)
        if base in FIAT and quote in FIAT:
            return AssetSpec(s, "forex", base, quote)
    return AssetSpec(s, "stock", s, "USD")


# Interactive Brokers bar-size strings
IB_BAR_SIZES = {
    "M1": "1 min",
    "M5": "5 mins",
    "M15": "15 mins",
    "M30": "30 mins",
    "H1": "1 hour",
    "H4": "4 hours",
    "D1": "1 day",
    "W1": "1 week",
    "MN1": "1 month",
}


def ib_duration(timeframe: str, count: int, asset: AssetSpec) -> str:
    """
    Build an IB ``durationStr`` large enough to return ``count`` bars.

    Non-24h markets (stocks) only trade ~6.5h/day, 5 days/week, so we
    over-request and trim afterwards.
    """
    minutes = TIMEFRAME_MINUTES[timeframe] * count
    if timeframe in {"D1", "W1", "MN1"}:
        # calendar days ≈ trading days * 7/5, plus holidays
        days = minutes / 1440 * 1.5
    elif asset.trades_24h:
        days = minutes / 1440 * 1.5
    else:
        days = minutes / 390 * 1.5  # 390 RTH minutes per session
    days = max(1, math.ceil(days))
    if days > 365:
        return f"{math.ceil(days / 365)} Y"
    return f"{days} D"


# Yahoo Finance (free, no key) mapping – used as a fallback data source
YF_INTERVALS = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "1h",  # resampled to 4h
    "D1": "1d",
    "W1": "1wk",
    "MN1": "1mo",
}

# Yahoo caps intraday history
YF_MAX_PERIOD = {
    "M1": "7d",
    "M5": "60d",
    "M15": "60d",
    "M30": "60d",
    "H1": "730d",
    "H4": "730d",
    "D1": "max",
    "W1": "max",
    "MN1": "max",
}

_YF_METALS = {"XAU": "GC=F", "XAG": "SI=F"}


def yahoo_ticker(symbol: str) -> str:
    asset = parse_symbol(symbol)
    if asset.asset_class == "forex":
        return f"{asset.base}{asset.quote}=X"
    if asset.asset_class == "crypto":
        return f"{asset.base}-{asset.quote}"
    if asset.asset_class == "metal":
        return _YF_METALS[asset.base]
    return asset.symbol
