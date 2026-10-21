"""
Signal Freshness Validation for the Strategy Agent.

Implements validation to ensure signals are fresh before using them
in trade decisions.

Requirements:
- 3.8: Discard NewsSignals where expires_at <= current time
- 3.9: Discard TechnicalSignals where timestamp is > 1 hour old
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.models.signals import NewsSignal, TechnicalSignal

from .config import SignalFreshnessConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def is_news_signal_fresh(
    signal: NewsSignal,
    current_time: Optional[datetime] = None,
) -> bool:
    """
    Check if a news signal is still fresh (not expired).
    
    A news signal is considered fresh if its expires_at time is
    greater than the current time.
    
    Args:
        signal: NewsSignal to check
        current_time: Current time (defaults to now if not provided)
        
    Returns:
        True if signal is fresh, False if expired
        
    Requirements:
    - 3.8: Discard NewsSignals where expires_at <= current time
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # Ensure current_time is timezone-aware
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    # Ensure signal expires_at is timezone-aware
    expires_at = signal.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    
    is_fresh = expires_at > current_time
    
    if not is_fresh:
        logger.debug(
            f"NewsSignal for {signal.symbol} is expired: "
            f"expires_at={expires_at.isoformat()}, current={current_time.isoformat()}"
        )
    
    return is_fresh


def is_technical_signal_fresh(
    signal: TechnicalSignal,
    current_time: Optional[datetime] = None,
    max_age: Optional[float] = None,
) -> bool:
    """
    Check if a technical signal is still fresh (not too old).
    
    A technical signal is considered fresh if its timestamp is
    within the maximum age threshold (default 1 hour).
    
    Args:
        signal: TechnicalSignal to check
        current_time: Current time (defaults to now if not provided)
        max_age: Maximum age in seconds (defaults to 1 hour)
        
    Returns:
        True if signal is fresh, False if too old
        
    Requirements:
    - 3.9: Discard TechnicalSignals where timestamp is > 1 hour old
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    if max_age is None:
        max_age = DEFAULT_CONFIG.signal_freshness.technical_signal_max_age.total_seconds()
    
    # Ensure current_time is timezone-aware
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    # Ensure signal timestamp is timezone-aware
    signal_time = signal.timestamp
    if signal_time.tzinfo is None:
        signal_time = signal_time.replace(tzinfo=timezone.utc)
    
    age_seconds = (current_time - signal_time).total_seconds()
    is_fresh = age_seconds <= max_age
    
    if not is_fresh:
        logger.debug(
            f"TechnicalSignal for {signal.symbol} is stale: "
            f"age={age_seconds:.0f}s, max_age={max_age:.0f}s"
        )
    
    return is_fresh


@dataclass
class FreshnessValidationResult:
    """Result of signal freshness validation."""
    is_valid: bool
    news_fresh: bool
    technical_fresh: bool
    rejection_reason: Optional[str] = None


class SignalFreshnessValidator:
    """
    Validates that signals are fresh before using them in trade decisions.
    
    Requirements:
    - 3.8: Discard NewsSignals where expires_at <= current time
    - 3.9: Discard TechnicalSignals where timestamp is > 1 hour old
    """
    
    def __init__(self, config: SignalFreshnessConfig = None):
        """
        Initialize the signal freshness validator.
        
        Args:
            config: Signal freshness configuration
        """
        self.config = config or DEFAULT_CONFIG.signal_freshness
    
    def validate(
        self,
        news_signal: NewsSignal,
        technical_signal: TechnicalSignal,
        current_time: Optional[datetime] = None,
    ) -> FreshnessValidationResult:
        """
        Validate that both signals are fresh.
        
        Args:
            news_signal: NewsSignal to validate
            technical_signal: TechnicalSignal to validate
            current_time: Current time (defaults to now if not provided)
            
        Returns:
            FreshnessValidationResult indicating if signals are valid
            
        Requirements:
        - 3.8: Discard NewsSignals where expires_at <= current time
        - 3.9: Discard TechnicalSignals where timestamp is > 1 hour old
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Check news signal freshness
        news_fresh = is_news_signal_fresh(news_signal, current_time)
        
        # Check technical signal freshness
        max_age = self.config.technical_signal_max_age.total_seconds()
        technical_fresh = is_technical_signal_fresh(
            technical_signal,
            current_time,
            max_age,
        )
        
        # Determine overall validity
        is_valid = news_fresh and technical_fresh
        
        # Build rejection reason if not valid
        rejection_reason = None
        if not is_valid:
            reasons = []
            if not news_fresh:
                reasons.append(
                    f"NewsSignal expired at {news_signal.expires_at.isoformat()}"
                )
            if not technical_fresh:
                age = (current_time - technical_signal.timestamp).total_seconds()
                reasons.append(
                    f"TechnicalSignal is {age:.0f}s old (max: {max_age:.0f}s)"
                )
            rejection_reason = "; ".join(reasons)
            
            logger.warning(
                f"Signal freshness validation failed for {news_signal.symbol}: "
                f"{rejection_reason}"
            )
        
        return FreshnessValidationResult(
            is_valid=is_valid,
            news_fresh=news_fresh,
            technical_fresh=technical_fresh,
            rejection_reason=rejection_reason,
        )
    
    def validate_news_signal(
        self,
        signal: NewsSignal,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Validate a single news signal for freshness.
        
        Args:
            signal: NewsSignal to validate
            current_time: Current time (defaults to now if not provided)
            
        Returns:
            True if signal is fresh, False if expired
        """
        return is_news_signal_fresh(signal, current_time)
    
    def validate_technical_signal(
        self,
        signal: TechnicalSignal,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Validate a single technical signal for freshness.
        
        Args:
            signal: TechnicalSignal to validate
            current_time: Current time (defaults to now if not provided)
            
        Returns:
            True if signal is fresh, False if too old
        """
        max_age = self.config.technical_signal_max_age.total_seconds()
        return is_technical_signal_fresh(signal, current_time, max_age)
