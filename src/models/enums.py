"""Enums for the AI Trading System."""

from enum import Enum


class Sentiment(Enum):
    """News sentiment classification."""
    VERY_BULLISH = "very_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    VERY_BEARISH = "very_bearish"


class ImpactType(Enum):
    """Type of news impact on stocks."""
    CASH_FLOW = "cash_flow"       # Direct financial impact
    HYPE = "hype"                 # Market sentiment only
    REGULATORY = "regulatory"     # Regulatory/legal impact
    MACRO = "macro"               # Macroeconomic impact


class TrendDirection(Enum):
    """Technical trend direction classification."""
    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    SIDEWAYS = "sideways"
    DOWNTREND = "downtrend"
    STRONG_DOWNTREND = "strong_downtrend"


class MarketCondition(Enum):
    """Market condition based on technical indicators."""
    OVERSOLD = "oversold"
    NEUTRAL = "neutral"
    OVERBOUGHT = "overbought"


class TradeAction(Enum):
    """Trade action recommendation."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    WAIT_PULLBACK = "wait_pullback"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"
    NO_TRADE = "no_trade"


class TradingHorizon(Enum):
    """Trading time horizon."""
    SHORT_TERM = "short_term"    # ~5 days
    MEDIUM_TERM = "medium_term"  # ~1-3 months
    LONG_TERM = "long_term"      # ~6 months


class Conviction(Enum):
    """Trade conviction level."""
    HIGH = "high"                # 80%+ confidence
    MEDIUM = "medium"            # 60-80% confidence
    LOW = "low"                  # Below 60%
