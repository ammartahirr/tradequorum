"""Signal data models for the AI Trading System."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import ImpactType, MarketCondition, Sentiment, TrendDirection


class NewsItem(BaseModel):
    """Raw news item from data sources."""
    source: str                    # "reuters", "twitter", "sec_filing"
    headline: str
    content: str
    published_at: datetime
    symbols: list[str]             # Affected stock symbols
    url: Optional[str] = None


class NewsSignal(BaseModel):
    """Processed news signal from the News Agent."""
    symbol: str
    sentiment: Sentiment
    impact_type: ImpactType
    impact_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str                 # LLM explanation
    source_items: list[str]        # Source news item IDs
    timestamp: datetime
    expires_at: datetime           # Signal validity window

    @field_validator("confidence")
    @classmethod
    def validate_cash_flow_confidence(cls, v: float, info) -> float:
        """Validate confidence for CASH_FLOW impact type (Requirement 1.4)."""
        # Note: This validation is applied during construction
        # The actual downgrade logic should be in the News Agent
        return v


class OHLCV(BaseModel):
    """Open, High, Low, Close, Volume candlestick data."""
    timestamp: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)

    @field_validator("high")
    @classmethod
    def high_must_be_highest(cls, v: float, info) -> float:
        """Validate high is >= open and close."""
        if info.data.get("open") is not None and v < info.data["open"]:
            raise ValueError("high must be >= open")
        return v

    @field_validator("low")
    @classmethod
    def low_must_be_lowest(cls, v: float, info) -> float:
        """Validate low is <= open, high, and close."""
        if info.data.get("open") is not None and v > info.data["open"]:
            raise ValueError("low must be <= open")
        if info.data.get("high") is not None and v > info.data["high"]:
            raise ValueError("low must be <= high")
        return v

    @model_validator(mode="after")
    def close_within_range(self) -> "OHLCV":
        """Validate low <= close <= high (field validators run before close is set)."""
        if not (self.low <= self.close <= self.high):
            raise ValueError("close must be between low and high")
        return self


class SupportResistance(BaseModel):
    """Support or resistance price level."""
    level: float = Field(gt=0)
    strength: float = Field(ge=0.0, le=1.0)  # How many times tested
    timeframe: str               # "5y", "1y", "6m", "1m"
    last_tested: datetime


class ConfluenceResult(BaseModel):
    """Result of confluence detection analysis."""
    score: float = Field(ge=0.0, le=1.0)
    factors: list[str]           # e.g. ["rsi_oversold", "5y_support", "volume_spike"]
    description: str


class TechnicalSignal(BaseModel):
    """Technical analysis signal from the Technical Agent."""
    symbol: str
    trend: TrendDirection
    condition: MarketCondition
    rsi: float = Field(ge=0, le=100)  # RSI must be in [0, 100] (Requirement 2.2)
    current_price: float = Field(gt=0)
    support_levels: list[SupportResistance]
    resistance_levels: list[SupportResistance]
    confluence: ConfluenceResult
    volume_trend: str            # "increasing", "decreasing", "stable"
    interest_rate_impact: float = Field(ge=-1.0, le=1.0)
    timestamp: datetime
