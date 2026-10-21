"""Trading data models for the AI Trading System."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from .enums import Conviction, TradeAction, TradingHorizon
from .signals import NewsSignal, TechnicalSignal


class TradeDecision(BaseModel):
    """Trade decision from the Strategy Agent."""
    symbol: str
    action: TradeAction
    conviction: Conviction
    horizon: TradingHorizon
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    position_size_pct: float = Field(gt=0, le=1.0)  # % of portfolio
    risk_reward_ratio: float = Field(ge=0)
    reasoning: str
    news_signal: NewsSignal
    technical_signal: TechnicalSignal
    timestamp: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_stop_loss_and_take_profit(self) -> "TradeDecision":
        """
        Validate stop-loss and take-profit positions based on trade action.
        
        Requirements 4.1, 4.2, 4.3, 13.1, 13.2:
        - For BUY: stop_loss < entry_price, take_profit > entry_price
        - For SELL: stop_loss > entry_price, take_profit < entry_price
        """
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        sell_actions = {TradeAction.STRONG_SELL, TradeAction.SELL}
        
        if self.action in buy_actions:
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"For BUY trades, stop_loss ({self.stop_loss}) must be below "
                    f"entry_price ({self.entry_price})"
                )
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"For BUY trades, take_profit ({self.take_profit}) must be above "
                    f"entry_price ({self.entry_price})"
                )
        elif self.action in sell_actions:
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"For SELL trades, stop_loss ({self.stop_loss}) must be above "
                    f"entry_price ({self.entry_price})"
                )
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"For SELL trades, take_profit ({self.take_profit}) must be below "
                    f"entry_price ({self.entry_price})"
                )
        
        return self

    @model_validator(mode="after")
    def validate_risk_reward_ratio(self) -> "TradeDecision":
        """
        Validate risk-reward ratio is at least 1.5 for actionable trades.
        
        Requirements 4.6, 13.4:
        - risk_reward_ratio must be >= 1.5 for actionable trades
        """
        actionable = {
            TradeAction.STRONG_BUY, TradeAction.BUY,
            TradeAction.STRONG_SELL, TradeAction.SELL
        }
        
        if self.action in actionable and self.risk_reward_ratio < 1.5:
            raise ValueError(
                f"Risk-reward ratio ({self.risk_reward_ratio}) must be >= 1.5 "
                f"for actionable trades"
            )
        
        return self

    @model_validator(mode="after")
    def validate_conviction_for_strong_actions(self) -> "TradeDecision":
        """
        Validate conviction level for STRONG_BUY/STRONG_SELL actions.
        
        Requirement 3.6:
        - STRONG_BUY and STRONG_SELL must have HIGH conviction
        """
        strong_actions = {TradeAction.STRONG_BUY, TradeAction.STRONG_SELL}
        
        if self.action in strong_actions and self.conviction != Conviction.HIGH:
            raise ValueError(
                f"STRONG_BUY and STRONG_SELL actions require HIGH conviction, "
                f"got {self.conviction}"
            )
        
        return self


class RiskLimits(BaseModel):
    """Risk management limits configuration."""
    max_position_pct: float = Field(default=0.05, gt=0, le=1.0)       # Max 5% per position
    max_portfolio_risk_pct: float = Field(default=0.02, gt=0, le=1.0)  # Max 2% portfolio risk per trade
    max_correlated_exposure: float = Field(default=0.20, gt=0, le=1.0)  # Max 20% in correlated assets
    max_daily_loss_pct: float = Field(default=0.05, gt=0, le=1.0)      # Max 5% daily loss
    max_open_positions: int = Field(default=10, gt=0)


class RiskAssessment(BaseModel):
    """Risk assessment result from the Risk Manager."""
    approved: bool
    adjusted_size: Optional[float] = Field(default=None, gt=0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)  # 0.0 to 1.0
    warnings: list[str] = Field(default_factory=list)
    rejection_reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> "RiskAssessment":
        """
        Validate rejection reason is provided when trade is rejected.
        
        Requirement 5.7:
        - Non-empty rejection reason when trade rejected
        """
        if not self.approved and not self.rejection_reason:
            raise ValueError(
                "rejection_reason must be provided when trade is not approved"
            )
        return self


class OrderResult(BaseModel):
    """Result of order execution."""
    order_id: str
    symbol: str
    status: str                  # "filled", "partial", "rejected"
    filled_price: float = Field(ge=0)
    filled_quantity: float = Field(ge=0)
    timestamp: datetime


class TradeRecord(BaseModel):
    """Complete trade record for persistence."""
    trade_id: str
    symbol: str
    action: TradeAction
    horizon: TradingHorizon
    entry_price: float = Field(gt=0)
    exit_price: Optional[float] = Field(default=None, gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    position_size: float = Field(gt=0)
    status: str                  # "open", "closed_profit", "closed_loss", "closed_sl", "closed_tp"
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    conviction: Conviction
    news_signal_id: str
    technical_signal_id: str
    decision_reasoning: str
    opened_at: datetime
    closed_at: Optional[datetime] = None
    exness_order_id: str

    @model_validator(mode="after")
    def validate_stop_loss_position(self) -> "TradeRecord":
        """
        Validate stop-loss position based on trade action.
        
        Requirements 13.1, 13.2:
        - For BUY: stop_loss < entry_price
        - For SELL: stop_loss > entry_price
        """
        buy_actions = {TradeAction.STRONG_BUY, TradeAction.BUY}
        sell_actions = {TradeAction.STRONG_SELL, TradeAction.SELL}
        
        if self.action in buy_actions:
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"For BUY trades, stop_loss ({self.stop_loss}) must be below "
                    f"entry_price ({self.entry_price})"
                )
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"For BUY trades, take_profit ({self.take_profit}) must be above "
                    f"entry_price ({self.entry_price})"
                )
        elif self.action in sell_actions:
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"For SELL trades, stop_loss ({self.stop_loss}) must be above "
                    f"entry_price ({self.entry_price})"
                )
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"For SELL trades, take_profit ({self.take_profit}) must be below "
                    f"entry_price ({self.entry_price})"
                )
        
        return self

    @model_validator(mode="after")
    def validate_closed_status(self) -> "TradeRecord":
        """
        Validate closed trade has required fields.
        
        Requirement 13.5:
        - Closed trades must have valid status
        """
        closed_statuses = {"closed_profit", "closed_loss", "closed_sl", "closed_tp"}
        
        if self.status in closed_statuses:
            if self.exit_price is None:
                raise ValueError(
                    f"Closed trades must have an exit_price"
                )
            if self.closed_at is None:
                raise ValueError(
                    f"Closed trades must have a closed_at timestamp"
                )
        
        return self


class SignalLog(BaseModel):
    """
    Signal log entry for DynamoDB persistence.
    
    Used to track all signals generated by agents for auditing and analysis.
    
    Requirements:
    - 9.1: Persist NewsSignal with signal ID, agent type, symbol, payload, timestamp
    - 9.2: Persist TechnicalSignal with signal ID, agent type, symbol, payload, timestamp
    - 9.4: Record whether signal was consumed and resulted in trade
    """
    signal_id: str
    agent_type: str              # "news", "technical", "strategy"
    symbol: str
    signal_data: dict            # Full signal payload
    created_at: datetime
    consumed_by: Optional[str] = None   # Which agent consumed this signal
    resulted_in_trade: bool = False
    trade_id: Optional[str] = None
