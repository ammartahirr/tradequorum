"""
Decision Matrix Evaluation for the Strategy Agent.

Implements the weighted decision matrix that combines news and technical signals
to produce trade actions.

Requirements:
- 3.1: Combine news (40% weight) and technical (60% weight) signals
- 3.2: VERY_BULLISH + OVERSOLD → STRONG_BUY with HIGH conviction
- 3.3: VERY_BEARISH + OVERBOUGHT → STRONG_SELL with HIGH conviction
- 3.4: BULLISH + OVERBOUGHT → WAIT_PULLBACK with MEDIUM conviction
- 3.5: Bearish news + oversold technical → NO_TRADE (conflicting signals)
- 3.6: STRONG_BUY/STRONG_SELL require HIGH conviction only
"""

import logging
from dataclasses import dataclass
from typing import Tuple

from src.models.enums import (
    Conviction,
    MarketCondition,
    Sentiment,
    TradeAction,
)
from src.models.signals import NewsSignal, TechnicalSignal

from .config import DecisionMatrixConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def map_sentiment_score(sentiment: Sentiment, impact_score: float) -> float:
    """
    Map news sentiment to a numeric score for the decision matrix.
    
    Args:
        sentiment: News sentiment enum
        impact_score: Impact score from news signal (0.0 to 1.0)
        
    Returns:
        Numeric score in range [-1.0, 1.0]
        - Positive values indicate bullish sentiment
        - Negative values indicate bearish sentiment
        - Magnitude is scaled by impact_score
    """
    base_scores = {
        Sentiment.VERY_BULLISH: 1.0,
        Sentiment.BULLISH: 0.5,
        Sentiment.NEUTRAL: 0.0,
        Sentiment.BEARISH: -0.5,
        Sentiment.VERY_BEARISH: -1.0,
    }
    
    base = base_scores.get(sentiment, 0.0)
    # Scale by impact score to give more weight to high-impact news
    return base * (0.5 + 0.5 * impact_score)


def map_technical_score(condition: MarketCondition, confluence_score: float) -> float:
    """
    Map technical market condition to a numeric score for the decision matrix.
    
    The score represents the opportunity for a trade:
    - OVERSOLD: Positive score (buying opportunity)
    - OVERBOUGHT: Negative score (selling opportunity)
    - NEUTRAL: Zero score
    
    Args:
        condition: Market condition enum
        confluence_score: Confluence score from technical signal (0.0 to 1.0)
        
    Returns:
        Numeric score in range [-1.0, 1.0]
        - Positive values indicate buying opportunity (oversold)
        - Negative values indicate selling opportunity (overbought)
        - Magnitude is scaled by confluence_score
    """
    base_scores = {
        MarketCondition.OVERSOLD: 1.0,    # Buying opportunity
        MarketCondition.NEUTRAL: 0.0,
        MarketCondition.OVERBOUGHT: -1.0,  # Selling opportunity
    }
    
    base = base_scores.get(condition, 0.0)
    # Scale by confluence score to give more weight to high-confluence signals
    return base * (0.5 + 0.5 * confluence_score)


@dataclass
class DecisionMatrixResult:
    """Result of decision matrix evaluation."""
    action: TradeAction
    conviction: Conviction
    combined_score: float
    news_score: float
    technical_score: float
    reasoning: str


class DecisionMatrixEvaluator:
    """
    Evaluates news and technical signals using a weighted decision matrix.
    
    The decision matrix combines:
    - News sentiment (40% weight)
    - Technical condition (60% weight)
    
    And applies specific rules for signal combinations to produce
    trade actions with appropriate conviction levels.
    
    Requirements:
    - 3.1: Combine news (40% weight) and technical (60% weight) signals
    - 3.2: VERY_BULLISH + OVERSOLD → STRONG_BUY with HIGH conviction
    - 3.3: VERY_BEARISH + OVERBOUGHT → STRONG_SELL with HIGH conviction
    - 3.4: BULLISH + OVERBOUGHT → WAIT_PULLBACK with MEDIUM conviction
    - 3.5: Bearish news + oversold technical → NO_TRADE (conflicting signals)
    - 3.6: STRONG_BUY/STRONG_SELL require HIGH conviction only
    """
    
    def __init__(self, config: DecisionMatrixConfig = None):
        """
        Initialize the decision matrix evaluator.
        
        Args:
            config: Decision matrix configuration
        """
        self.config = config or DEFAULT_CONFIG.decision_matrix
    
    def evaluate(
        self,
        news_signal: NewsSignal,
        technical_signal: TechnicalSignal,
    ) -> DecisionMatrixResult:
        """
        Evaluate news and technical signals to produce a trade action.
        
        This method applies the decision matrix rules in order of priority:
        1. Check for specific high-conviction combinations
        2. Check for conflicting signals
        3. Fall back to combined score evaluation
        
        Args:
            news_signal: News signal from News Agent
            technical_signal: Technical signal from Technical Agent
            
        Returns:
            DecisionMatrixResult with action, conviction, and reasoning
            
        Requirements:
        - 3.1: Combine news (40% weight) and technical (60% weight) signals
        - 3.2-3.6: Apply decision matrix rules
        """
        # Calculate individual scores
        news_score = map_sentiment_score(
            news_signal.sentiment,
            news_signal.impact_score,
        )
        technical_score = map_technical_score(
            technical_signal.condition,
            technical_signal.confluence.score,
        )
        
        # Calculate combined score
        combined_score = (
            news_score * self.config.news_weight +
            technical_score * self.config.technical_weight
        )
        
        # Apply decision matrix rules
        action, conviction, reasoning = self._apply_decision_rules(
            news_signal.sentiment,
            technical_signal.condition,
            combined_score,
            technical_signal.confluence.score,
        )
        
        logger.info(
            f"Decision matrix evaluation: "
            f"news={news_signal.sentiment.value} ({news_score:.2f}), "
            f"tech={technical_signal.condition.value} ({technical_score:.2f}), "
            f"combined={combined_score:.2f} → {action.value} ({conviction.value})"
        )
        
        return DecisionMatrixResult(
            action=action,
            conviction=conviction,
            combined_score=combined_score,
            news_score=news_score,
            technical_score=technical_score,
            reasoning=reasoning,
        )
    
    def _apply_decision_rules(
        self,
        sentiment: Sentiment,
        condition: MarketCondition,
        combined_score: float,
        confluence_score: float,
    ) -> Tuple[TradeAction, Conviction, str]:
        """
        Apply decision matrix rules to determine trade action and conviction.
        
        Rules are applied in priority order:
        1. VERY_BULLISH + OVERSOLD → STRONG_BUY (HIGH)
        2. VERY_BEARISH + OVERBOUGHT → STRONG_SELL (HIGH)
        3. BULLISH + OVERBOUGHT → WAIT_PULLBACK (MEDIUM)
        4. BEARISH/VERY_BEARISH + OVERSOLD → NO_TRADE (conflicting)
        5. Fall back to combined score evaluation
        
        Args:
            sentiment: News sentiment
            condition: Market condition
            combined_score: Weighted combined score
            confluence_score: Technical confluence score
            
        Returns:
            Tuple of (TradeAction, Conviction, reasoning string)
        """
        # Rule 1: VERY_BULLISH + OVERSOLD → STRONG_BUY (Requirement 3.2)
        if sentiment == Sentiment.VERY_BULLISH and condition == MarketCondition.OVERSOLD:
            return (
                TradeAction.STRONG_BUY,
                Conviction.HIGH,
                f"Strong buy signal: Very bullish news with oversold technical condition. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        # Rule 2: VERY_BEARISH + OVERBOUGHT → STRONG_SELL (Requirement 3.3)
        if sentiment == Sentiment.VERY_BEARISH and condition == MarketCondition.OVERBOUGHT:
            return (
                TradeAction.STRONG_SELL,
                Conviction.HIGH,
                f"Strong sell signal: Very bearish news with overbought technical condition. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        # Rule 3: BULLISH + OVERBOUGHT → WAIT_PULLBACK (Requirement 3.4)
        if sentiment == Sentiment.BULLISH and condition == MarketCondition.OVERBOUGHT:
            return (
                TradeAction.WAIT_PULLBACK,
                Conviction.MEDIUM,
                f"Wait for pullback: Bullish news but overbought condition. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        # Rule 4: Bearish news + OVERSOLD → NO_TRADE (Requirement 3.5)
        # Conflicting signals - bearish news suggests selling but oversold suggests buying
        if sentiment in (Sentiment.BEARISH, Sentiment.VERY_BEARISH) and condition == MarketCondition.OVERSOLD:
            return (
                TradeAction.NO_TRADE,
                Conviction.LOW,
                f"No trade: Conflicting signals - bearish news ({sentiment.value}) "
                f"with oversold technical condition. Confluence: {confluence_score:.2f}",
            )
        
        # Rule 5: Bullish news + OVERSOLD → BUY (not STRONG_BUY since not VERY_BULLISH)
        if sentiment == Sentiment.BULLISH and condition == MarketCondition.OVERSOLD:
            return (
                TradeAction.BUY,
                Conviction.MEDIUM,
                f"Buy signal: Bullish news with oversold technical condition. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        # Rule 6: Bearish news + OVERBOUGHT → SELL (not STRONG_SELL since not VERY_BEARISH)
        if sentiment == Sentiment.BEARISH and condition == MarketCondition.OVERBOUGHT:
            return (
                TradeAction.SELL,
                Conviction.MEDIUM,
                f"Sell signal: Bearish news with overbought technical condition. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        # Fall back to combined score evaluation
        return self._evaluate_combined_score(combined_score, confluence_score)
    
    def _evaluate_combined_score(
        self,
        combined_score: float,
        confluence_score: float,
    ) -> Tuple[TradeAction, Conviction, str]:
        """
        Evaluate trade action based on combined score when no specific rule applies.
        
        Args:
            combined_score: Weighted combined score
            confluence_score: Technical confluence score
            
        Returns:
            Tuple of (TradeAction, Conviction, reasoning string)
        """
        if combined_score > self.config.buy_threshold:
            # Positive combined score above threshold → BUY
            conviction = Conviction.MEDIUM if confluence_score >= 0.5 else Conviction.LOW
            return (
                TradeAction.BUY,
                conviction,
                f"Buy signal based on combined score: {combined_score:.2f}. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        if combined_score < self.config.sell_threshold:
            # Negative combined score below threshold → SELL
            conviction = Conviction.MEDIUM if confluence_score >= 0.5 else Conviction.LOW
            return (
                TradeAction.SELL,
                conviction,
                f"Sell signal based on combined score: {combined_score:.2f}. "
                f"Confluence: {confluence_score:.2f}",
            )
        
        # Combined score in neutral range → HOLD or NO_TRADE
        if abs(combined_score) < 0.2:
            return (
                TradeAction.NO_TRADE,
                Conviction.LOW,
                f"No trade: Combined score too neutral ({combined_score:.2f}). "
                f"Confluence: {confluence_score:.2f}",
            )
        
        return (
            TradeAction.HOLD,
            Conviction.LOW,
            f"Hold: Combined score in uncertain range ({combined_score:.2f}). "
            f"Confluence: {confluence_score:.2f}",
        )
