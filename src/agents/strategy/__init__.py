"""
Strategy Agent (The Brain) - Synthesizes signals from News and Technical Agents.

This module implements the Strategy Agent which:
- Combines news (40% weight) and technical (60% weight) signals
- Applies decision matrix rules for trade actions
- Calculates stop-loss and take-profit levels
- Generates TradeDecision objects with proper risk-reward ratios
- Persists decisions to DynamoDB

Requirements:
- 3.1-3.9: Strategy decision making
- 4.1-4.8: Stop-loss and take-profit calculation
- 9.3: Persist decisions to DynamoDB
"""

from .decision_matrix import (
    DecisionMatrixEvaluator,
    map_sentiment_score,
    map_technical_score,
)
from .signal_freshness import (
    SignalFreshnessValidator,
    is_news_signal_fresh,
    is_technical_signal_fresh,
)
from .stop_loss import (
    StopLossCalculator,
    calculate_stop_loss,
)
from .take_profit import (
    TakeProfitCalculator,
    calculate_take_profit,
)
from .strategy_agent import (
    StrategyAgent,
)
from .persistence import (
    StrategyPersistence,
)

__all__ = [
    # Decision Matrix
    "DecisionMatrixEvaluator",
    "map_sentiment_score",
    "map_technical_score",
    # Signal Freshness
    "SignalFreshnessValidator",
    "is_news_signal_fresh",
    "is_technical_signal_fresh",
    # Stop Loss
    "StopLossCalculator",
    "calculate_stop_loss",
    # Take Profit
    "TakeProfitCalculator",
    "calculate_take_profit",
    # Strategy Agent
    "StrategyAgent",
    # Persistence
    "StrategyPersistence",
]
