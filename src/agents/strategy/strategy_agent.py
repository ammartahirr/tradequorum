"""
Strategy Agent (The Brain) - Main implementation.

Synthesizes signals from the News Agent and Technical Agent to produce
trade decisions with precise entry, exit, stop-loss, and take-profit calculations.

Requirements:
- 3.1-3.9: Strategy decision making
- 4.1-4.8: Stop-loss and take-profit calculation
- 9.3: Persist decisions to DynamoDB
- 10.2: Halt new trade decisions when market data is stale
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from src.models.enums import Conviction, TradeAction, TradingHorizon
from src.models.signals import NewsSignal, TechnicalSignal
from src.models.trading import TradeDecision

from .config import StrategyConfig, DEFAULT_CONFIG
from .decision_matrix import DecisionMatrixEvaluator, DecisionMatrixResult
from .persistence import StrategyPersistence
from .signal_freshness import SignalFreshnessValidator, FreshnessValidationResult
from .stop_loss import StopLossCalculator
from .take_profit import TakeProfitCalculator, calculate_risk_reward_ratio

logger = logging.getLogger(__name__)


class StaleDataError(Exception):
    """Exception raised when market data is stale and trading should be halted."""
    pass


@dataclass
class EvaluationResult:
    """Result of strategy evaluation."""
    decision: Optional[TradeDecision]
    decision_id: Optional[str]
    matrix_result: Optional[DecisionMatrixResult]
    freshness_result: FreshnessValidationResult
    success: bool
    error_message: Optional[str] = None
    is_stale_data: bool = False


def _calculate_position_size(
    conviction: Conviction,
    config: StrategyConfig,
) -> float:
    """
    Calculate position size based on conviction level.
    
    Args:
        conviction: Trade conviction level
        config: Strategy configuration
        
    Returns:
        Position size as percentage of portfolio
    """
    sizes = {
        Conviction.HIGH: config.position_sizing.high_conviction_size_pct,
        Conviction.MEDIUM: config.position_sizing.medium_conviction_size_pct,
        Conviction.LOW: config.position_sizing.low_conviction_size_pct,
    }
    
    size = sizes.get(conviction, config.position_sizing.low_conviction_size_pct)
    return min(size, config.position_sizing.max_position_size_pct)


class StrategyAgent:
    """
    Strategy Agent (The Brain) - Synthesizes signals into trade decisions.
    
    This agent:
    - Validates signal freshness before processing
    - Combines news and technical signals using a weighted decision matrix
    - Calculates optimal entry, stop-loss, and take-profit levels
    - Generates TradeDecision objects with proper risk-reward ratios
    - Persists decisions to DynamoDB
    
    Requirements:
    - 3.1-3.9: Strategy decision making
    - 4.1-4.8: Stop-loss and take-profit calculation
    - 9.3: Persist decisions to DynamoDB
    - 10.2: Halt new trade decisions when market data is stale
    """
    
    def __init__(
        self,
        config: StrategyConfig = None,
        persistence: Optional[StrategyPersistence] = None,
        stale_data_detector: Optional[callable] = None,
    ):
        """
        Initialize the Strategy Agent.
        
        Args:
            config: Strategy configuration
            persistence: Optional persistence layer (created if not provided)
            stale_data_detector: Optional callable that returns True if data is stale
                                 for a given symbol (Requirement 10.2)
        """
        self.config = config or DEFAULT_CONFIG
        self._stale_data_detector = stale_data_detector
        self._trading_halted = False
        self._halt_reason: Optional[str] = None
        
        # Initialize components
        self.freshness_validator = SignalFreshnessValidator(
            self.config.signal_freshness
        )
        self.decision_matrix = DecisionMatrixEvaluator(
            self.config.decision_matrix
        )
        self.stop_loss_calculator = StopLossCalculator(
            self.config.stop_loss
        )
        self.take_profit_calculator = TakeProfitCalculator(
            self.config.take_profit
        )
        self.persistence = persistence or StrategyPersistence(
            table_name=self.config.decisions_table
        )
    
    def set_stale_data_detector(self, detector: callable) -> None:
        """
        Set the stale data detector function.
        
        Args:
            detector: Callable that takes a symbol and returns True if data is stale
        """
        self._stale_data_detector = detector
    
    def is_data_stale(self, symbol: str) -> bool:
        """
        Check if market data for a symbol is stale.
        
        Requirements:
        - 10.2: Mark signals as stale when data >5 min old during trading hours
        
        Args:
            symbol: Trading symbol to check
            
        Returns:
            True if data is stale, False otherwise
        """
        if self._stale_data_detector is None:
            return False
        
        try:
            return self._stale_data_detector(symbol)
        except Exception as e:
            logger.warning(f"Error checking stale data for {symbol}: {e}")
            return False
    
    def halt_trading(self, reason: str) -> None:
        """
        Halt all new trade decisions.
        
        Args:
            reason: Reason for halting trading
        """
        self._trading_halted = True
        self._halt_reason = reason
        logger.warning(f"Trading halted: {reason}")
    
    def resume_trading(self) -> None:
        """Resume trading after halt."""
        self._trading_halted = False
        self._halt_reason = None
        logger.info("Trading resumed")
    
    @property
    def is_trading_halted(self) -> bool:
        """Check if trading is currently halted."""
        return self._trading_halted
    
    @property
    def halt_reason(self) -> Optional[str]:
        """Get the reason for trading halt."""
        return self._halt_reason
    
    async def evaluate(
        self,
        news_signal: NewsSignal,
        technical_signal: TechnicalSignal,
        horizon: TradingHorizon = TradingHorizon.SHORT_TERM,
        news_signal_id: Optional[str] = None,
        technical_signal_id: Optional[str] = None,
        current_time: Optional[datetime] = None,
    ) -> EvaluationResult:
        """
        Evaluate news and technical signals to produce a trade decision.
        
        This method:
        1. Checks if trading is halted or data is stale
        2. Validates signal freshness
        3. Applies the decision matrix
        4. Calculates stop-loss and take-profit levels
        5. Generates a TradeDecision
        6. Persists the decision to DynamoDB
        
        Args:
            news_signal: News signal from News Agent
            technical_signal: Technical signal from Technical Agent
            horizon: Trading horizon (default SHORT_TERM)
            news_signal_id: Optional ID of the news signal for persistence
            technical_signal_id: Optional ID of the technical signal for persistence
            current_time: Current time for freshness validation
            
        Returns:
            EvaluationResult with decision and metadata
            
        Requirements:
        - 3.1-3.9: Strategy decision making
        - 4.1-4.8: Stop-loss and take-profit calculation
        - 9.3: Persist decisions to DynamoDB
        - 10.2: Halt new trade decisions when market data is stale
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Step 0: Check if trading is halted (Requirement 10.2)
        if self._trading_halted:
            logger.warning(
                f"Trade evaluation blocked for {news_signal.symbol}: "
                f"Trading halted - {self._halt_reason}"
            )
            return EvaluationResult(
                decision=None,
                decision_id=None,
                matrix_result=None,
                freshness_result=FreshnessValidationResult(
                    is_valid=False,
                    news_fresh=True,
                    technical_fresh=True,
                    rejection_reason=f"Trading halted: {self._halt_reason}",
                ),
                success=False,
                error_message=f"Trading halted: {self._halt_reason}",
                is_stale_data=True,
            )
        
        # Step 0.5: Check for stale market data (Requirement 10.2)
        if self.config.stale_data.halt_on_stale_data and self.is_data_stale(news_signal.symbol):
            stale_message = (
                f"Market data is stale for {news_signal.symbol}. "
                f"Halting new trade decisions until fresh data resumes."
            )
            logger.warning(stale_message)
            return EvaluationResult(
                decision=None,
                decision_id=None,
                matrix_result=None,
                freshness_result=FreshnessValidationResult(
                    is_valid=False,
                    news_fresh=True,
                    technical_fresh=False,
                    rejection_reason=stale_message,
                ),
                success=False,
                error_message=stale_message,
                is_stale_data=True,
            )
        
        # Step 1: Validate signal freshness (Requirements 3.8, 3.9)
        freshness_result = self.freshness_validator.validate(
            news_signal,
            technical_signal,
            current_time,
        )
        
        if not freshness_result.is_valid:
            logger.warning(
                f"Signal freshness validation failed for {news_signal.symbol}: "
                f"{freshness_result.rejection_reason}"
            )
            return EvaluationResult(
                decision=None,
                decision_id=None,
                matrix_result=None,
                freshness_result=freshness_result,
                success=False,
                error_message=freshness_result.rejection_reason,
            )
        
        # Step 2: Apply decision matrix (Requirements 3.1-3.6)
        matrix_result = self.decision_matrix.evaluate(news_signal, technical_signal)
        
        # Step 3: Check if action is tradeable
        if matrix_result.action in {TradeAction.NO_TRADE, TradeAction.HOLD, TradeAction.WAIT_PULLBACK}:
            # Create a non-actionable decision for logging purposes
            decision = self._create_non_actionable_decision(
                news_signal,
                technical_signal,
                matrix_result,
                horizon,
                current_time,
            )
            
            # Persist the decision
            decision_id = await self._persist_decision(
                decision,
                news_signal_id or "unknown",
                technical_signal_id or "unknown",
            )
            
            return EvaluationResult(
                decision=decision,
                decision_id=decision_id,
                matrix_result=matrix_result,
                freshness_result=freshness_result,
                success=True,
            )
        
        # Step 4: Calculate entry, stop-loss, take-profit (Requirements 4.1-4.8)
        try:
            decision = self._create_actionable_decision(
                news_signal,
                technical_signal,
                matrix_result,
                horizon,
                current_time,
            )
        except ValueError as e:
            logger.error(f"Failed to create trade decision: {e}")
            return EvaluationResult(
                decision=None,
                decision_id=None,
                matrix_result=matrix_result,
                freshness_result=freshness_result,
                success=False,
                error_message=str(e),
            )
        
        # Step 5: Persist the decision (Requirement 9.3)
        decision_id = await self._persist_decision(
            decision,
            news_signal_id or "unknown",
            technical_signal_id or "unknown",
        )
        
        logger.info(
            f"Strategy evaluation complete for {news_signal.symbol}: "
            f"action={decision.action.value}, conviction={decision.conviction.value}, "
            f"entry={decision.entry_price:.2f}, sl={decision.stop_loss:.2f}, "
            f"tp={decision.take_profit:.2f}, rr={decision.risk_reward_ratio:.2f}"
        )
        
        return EvaluationResult(
            decision=decision,
            decision_id=decision_id,
            matrix_result=matrix_result,
            freshness_result=freshness_result,
            success=True,
        )
    
    def _create_actionable_decision(
        self,
        news_signal: NewsSignal,
        technical_signal: TechnicalSignal,
        matrix_result: DecisionMatrixResult,
        horizon: TradingHorizon,
        current_time: datetime,
    ) -> TradeDecision:
        """
        Create an actionable trade decision with calculated levels.
        
        Args:
            news_signal: News signal
            technical_signal: Technical signal
            matrix_result: Decision matrix result
            horizon: Trading horizon
            current_time: Current timestamp
            
        Returns:
            TradeDecision with all calculated fields
        """
        entry_price = technical_signal.current_price
        
        # Calculate stop-loss (Requirements 4.1-4.3, 4.7)
        stop_loss = self.stop_loss_calculator.calculate(
            action=matrix_result.action,
            entry_price=entry_price,
            support_levels=technical_signal.support_levels,
            resistance_levels=technical_signal.resistance_levels,
            horizon=horizon,
        )
        
        # Calculate take-profit (Requirements 4.4-4.6, 4.8)
        take_profit = self.take_profit_calculator.calculate(
            action=matrix_result.action,
            entry_price=entry_price,
            stop_loss=stop_loss,
            support_levels=technical_signal.support_levels,
            resistance_levels=technical_signal.resistance_levels,
            horizon=horizon,
        )
        
        # Calculate risk-reward ratio
        risk_reward_ratio = calculate_risk_reward_ratio(
            matrix_result.action,
            entry_price,
            stop_loss,
            take_profit,
        )
        
        # Calculate position size based on conviction
        position_size_pct = _calculate_position_size(
            matrix_result.conviction,
            self.config,
        )
        
        # Calculate expiry time
        expires_at = current_time + timedelta(hours=self.config.decision_expiry_hours)
        
        return TradeDecision(
            symbol=news_signal.symbol,
            action=matrix_result.action,
            conviction=matrix_result.conviction,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size_pct,
            risk_reward_ratio=risk_reward_ratio,
            reasoning=matrix_result.reasoning,
            news_signal=news_signal,
            technical_signal=technical_signal,
            timestamp=current_time,
            expires_at=expires_at,
        )
    
    def _create_non_actionable_decision(
        self,
        news_signal: NewsSignal,
        technical_signal: TechnicalSignal,
        matrix_result: DecisionMatrixResult,
        horizon: TradingHorizon,
        current_time: datetime,
    ) -> TradeDecision:
        """
        Create a non-actionable decision (NO_TRADE, HOLD, WAIT_PULLBACK).
        
        For non-actionable decisions, we still need valid stop-loss and
        take-profit values for the model, but they won't be used for trading.
        
        Args:
            news_signal: News signal
            technical_signal: Technical signal
            matrix_result: Decision matrix result
            horizon: Trading horizon
            current_time: Current timestamp
            
        Returns:
            TradeDecision for logging purposes
        """
        entry_price = technical_signal.current_price
        
        # For non-actionable trades, use placeholder values that satisfy model validation
        # These won't be used for actual trading
        stop_loss = entry_price * 0.95  # 5% below entry
        take_profit = entry_price * 1.10  # 10% above entry
        risk_reward_ratio = 2.0  # Placeholder
        
        # Calculate expiry time
        expires_at = current_time + timedelta(hours=self.config.decision_expiry_hours)
        
        # Use minimal positive value for position_size_pct to satisfy model validation
        # This is a placeholder since non-actionable decisions won't be traded
        minimal_position_size = 0.001  # 0.1% - minimal valid value
        
        return TradeDecision(
            symbol=news_signal.symbol,
            action=matrix_result.action,
            conviction=matrix_result.conviction,
            horizon=horizon,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=minimal_position_size,
            risk_reward_ratio=risk_reward_ratio,
            reasoning=matrix_result.reasoning,
            news_signal=news_signal,
            technical_signal=technical_signal,
            timestamp=current_time,
            expires_at=expires_at,
        )
    
    async def _persist_decision(
        self,
        decision: TradeDecision,
        news_signal_id: str,
        technical_signal_id: str,
    ) -> Optional[str]:
        """
        Persist a trade decision to DynamoDB.
        
        Args:
            decision: TradeDecision to persist
            news_signal_id: ID of the originating news signal
            technical_signal_id: ID of the originating technical signal
            
        Returns:
            Decision ID if successful, None otherwise
        """
        return await self.persistence.persist_decision(
            decision,
            news_signal_id,
            technical_signal_id,
        )
    
    async def get_recent_decisions(
        self,
        symbol: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get recent decisions for a symbol.
        
        Args:
            symbol: Stock symbol to query
            limit: Maximum number of results
            
        Returns:
            List of decision data dictionaries
        """
        return await self.persistence.get_recent_decisions(symbol, limit)
