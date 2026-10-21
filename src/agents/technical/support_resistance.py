"""
Support and resistance level identification for the Technical Agent.

Implements:
- Local minima (support) detection
- Local maxima (resistance) detection
- Level clustering to consolidate nearby levels
- Strength scoring based on number of touches
- Active level detection (within 2% of current price)

Requirements:
- 2.3: Identify support and resistance levels using up to 5 years of historical price data
- 2.6: Flag levels as active when current price is within 2%
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.models import OHLCV, SupportResistance

logger = logging.getLogger(__name__)


# --- Constants ---

# Default lookback window for local extrema detection
DEFAULT_LOOKBACK_WINDOW = 5

# Default clustering threshold (2% of price)
DEFAULT_CLUSTER_THRESHOLD_PCT = 0.02

# Active level threshold (Requirement 2.6: within 2%)
ACTIVE_LEVEL_THRESHOLD_PCT = 0.02

# Timeframe labels based on number of trading days
TIMEFRAME_LABELS = {
    "5y": 1260,   # ~5 years of trading days
    "1y": 252,    # ~1 year of trading days
    "6m": 126,    # ~6 months of trading days
    "1m": 21,     # ~1 month of trading days
}


# --- Data Classes ---

@dataclass
class PriceLevel:
    """Represents a detected price level (support or resistance)."""
    price: float
    timestamp: datetime
    level_type: str  # "support" or "resistance"


@dataclass
class SupportResistanceResult:
    """Result of support/resistance analysis."""
    support_levels: list[SupportResistance]
    resistance_levels: list[SupportResistance]
    active_support_levels: list[SupportResistance]
    active_resistance_levels: list[SupportResistance]
    current_price: float
    timeframe: str


# --- Local Extrema Detection ---

def find_local_minima(
    candles: list[OHLCV],
    window: int = DEFAULT_LOOKBACK_WINDOW,
) -> list[PriceLevel]:
    """
    Find local minima (potential support levels) in price data.
    
    A local minimum is a candle whose low is lower than the lows of
    all candles within the window on both sides.
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        window: Number of candles to check on each side
        
    Returns:
        List of PriceLevel objects representing local minima
    """
    if len(candles) < (2 * window + 1):
        return []
    
    minima = []
    
    for i in range(window, len(candles) - window):
        current_low = candles[i].low
        is_minimum = True
        
        # Check all candles in the window on both sides
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if candles[j].low <= current_low:
                is_minimum = False
                break
        
        if is_minimum:
            minima.append(PriceLevel(
                price=current_low,
                timestamp=candles[i].timestamp,
                level_type="support",
            ))
    
    logger.debug(f"Found {len(minima)} local minima")
    return minima


def find_local_maxima(
    candles: list[OHLCV],
    window: int = DEFAULT_LOOKBACK_WINDOW,
) -> list[PriceLevel]:
    """
    Find local maxima (potential resistance levels) in price data.
    
    A local maximum is a candle whose high is higher than the highs of
    all candles within the window on both sides.
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        window: Number of candles to check on each side
        
    Returns:
        List of PriceLevel objects representing local maxima
    """
    if len(candles) < (2 * window + 1):
        return []
    
    maxima = []
    
    for i in range(window, len(candles) - window):
        current_high = candles[i].high
        is_maximum = True
        
        # Check all candles in the window on both sides
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if candles[j].high >= current_high:
                is_maximum = False
                break
        
        if is_maximum:
            maxima.append(PriceLevel(
                price=current_high,
                timestamp=candles[i].timestamp,
                level_type="resistance",
            ))
    
    logger.debug(f"Found {len(maxima)} local maxima")
    return maxima


# --- Level Clustering ---

def cluster_levels(
    levels: list[PriceLevel],
    threshold_pct: float = DEFAULT_CLUSTER_THRESHOLD_PCT,
) -> list[tuple[float, list[PriceLevel]]]:
    """
    Cluster nearby price levels together.
    
    Levels within threshold_pct of each other are grouped together.
    The cluster price is the average of all levels in the cluster.
    
    Args:
        levels: List of PriceLevel objects to cluster
        threshold_pct: Percentage threshold for clustering (e.g., 0.02 = 2%)
        
    Returns:
        List of tuples (cluster_price, list_of_levels_in_cluster)
    """
    if not levels:
        return []
    
    # Sort levels by price
    sorted_levels = sorted(levels, key=lambda x: x.price)
    
    clusters: list[tuple[float, list[PriceLevel]]] = []
    current_cluster: list[PriceLevel] = [sorted_levels[0]]
    
    for i in range(1, len(sorted_levels)):
        current_level = sorted_levels[i]
        cluster_avg = sum(l.price for l in current_cluster) / len(current_cluster)
        
        # Check if current level is within threshold of cluster average
        if abs(current_level.price - cluster_avg) / cluster_avg <= threshold_pct:
            current_cluster.append(current_level)
        else:
            # Finalize current cluster and start new one
            cluster_price = sum(l.price for l in current_cluster) / len(current_cluster)
            clusters.append((cluster_price, current_cluster))
            current_cluster = [current_level]
    
    # Don't forget the last cluster
    if current_cluster:
        cluster_price = sum(l.price for l in current_cluster) / len(current_cluster)
        clusters.append((cluster_price, current_cluster))
    
    logger.debug(f"Clustered {len(levels)} levels into {len(clusters)} clusters")
    return clusters


# --- Strength Calculation ---

def calculate_strength(
    levels: list[PriceLevel],
    max_touches: int = 10,
) -> float:
    """
    Calculate the strength of a price level based on number of touches.
    
    Strength is calculated as: min(num_touches / max_touches, 1.0)
    
    Args:
        levels: List of PriceLevel objects in the cluster
        max_touches: Maximum number of touches for full strength
        
    Returns:
        Strength value in range [0.0, 1.0]
    """
    num_touches = len(levels)
    strength = min(num_touches / max_touches, 1.0)
    return strength


# --- Timeframe Determination ---

def determine_timeframe(candles: list[OHLCV]) -> str:
    """
    Determine the timeframe label based on number of candles.
    
    Args:
        candles: List of OHLCV candles
        
    Returns:
        Timeframe label: "5y", "1y", "6m", or "1m"
    """
    num_candles = len(candles)
    
    if num_candles >= TIMEFRAME_LABELS["5y"]:
        return "5y"
    elif num_candles >= TIMEFRAME_LABELS["1y"]:
        return "1y"
    elif num_candles >= TIMEFRAME_LABELS["6m"]:
        return "6m"
    else:
        return "1m"


# --- Support/Resistance Identification ---

def identify_support_levels(
    candles: list[OHLCV],
    window: int = DEFAULT_LOOKBACK_WINDOW,
    cluster_threshold_pct: float = DEFAULT_CLUSTER_THRESHOLD_PCT,
) -> list[SupportResistance]:
    """
    Identify support levels from historical price data.
    
    Requirements:
    - 2.3: Identify support levels using up to 5 years of historical price data
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        window: Lookback window for local minima detection
        cluster_threshold_pct: Threshold for clustering nearby levels
        
    Returns:
        List of SupportResistance objects representing support levels
    """
    # Find local minima
    minima = find_local_minima(candles, window)
    
    if not minima:
        return []
    
    # Cluster nearby levels
    clusters = cluster_levels(minima, cluster_threshold_pct)
    
    # Determine timeframe
    timeframe = determine_timeframe(candles)
    
    # Convert clusters to SupportResistance objects
    support_levels = []
    for cluster_price, levels in clusters:
        # Get the most recent timestamp from the cluster
        last_tested = max(l.timestamp for l in levels)
        
        # Calculate strength based on number of touches
        strength = calculate_strength(levels)
        
        support_levels.append(SupportResistance(
            level=cluster_price,
            strength=strength,
            timeframe=timeframe,
            last_tested=last_tested,
        ))
    
    # Sort by level (price) ascending
    support_levels.sort(key=lambda x: x.level)
    
    logger.info(f"Identified {len(support_levels)} support levels for {timeframe} timeframe")
    return support_levels


def identify_resistance_levels(
    candles: list[OHLCV],
    window: int = DEFAULT_LOOKBACK_WINDOW,
    cluster_threshold_pct: float = DEFAULT_CLUSTER_THRESHOLD_PCT,
) -> list[SupportResistance]:
    """
    Identify resistance levels from historical price data.
    
    Requirements:
    - 2.3: Identify resistance levels using up to 5 years of historical price data
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        window: Lookback window for local maxima detection
        cluster_threshold_pct: Threshold for clustering nearby levels
        
    Returns:
        List of SupportResistance objects representing resistance levels
    """
    # Find local maxima
    maxima = find_local_maxima(candles, window)
    
    if not maxima:
        return []
    
    # Cluster nearby levels
    clusters = cluster_levels(maxima, cluster_threshold_pct)
    
    # Determine timeframe
    timeframe = determine_timeframe(candles)
    
    # Convert clusters to SupportResistance objects
    resistance_levels = []
    for cluster_price, levels in clusters:
        # Get the most recent timestamp from the cluster
        last_tested = max(l.timestamp for l in levels)
        
        # Calculate strength based on number of touches
        strength = calculate_strength(levels)
        
        resistance_levels.append(SupportResistance(
            level=cluster_price,
            strength=strength,
            timeframe=timeframe,
            last_tested=last_tested,
        ))
    
    # Sort by level (price) ascending
    resistance_levels.sort(key=lambda x: x.level)
    
    logger.info(f"Identified {len(resistance_levels)} resistance levels for {timeframe} timeframe")
    return resistance_levels


# --- Active Level Detection ---

def is_level_active(
    level: SupportResistance,
    current_price: float,
    threshold_pct: float = ACTIVE_LEVEL_THRESHOLD_PCT,
) -> bool:
    """
    Check if a support/resistance level is active.
    
    A level is considered active when the current price is within
    the threshold percentage of the level.
    
    Requirements:
    - 2.6: Flag levels as active when current price is within 2%
    
    Args:
        level: SupportResistance level to check
        current_price: Current market price
        threshold_pct: Percentage threshold (default 0.02 = 2%)
        
    Returns:
        True if the level is active, False otherwise
    """
    if level.level <= 0 or current_price <= 0:
        return False
    
    # Calculate percentage distance from level
    distance_pct = abs(current_price - level.level) / level.level
    
    return distance_pct <= threshold_pct


def get_active_levels(
    levels: list[SupportResistance],
    current_price: float,
    threshold_pct: float = ACTIVE_LEVEL_THRESHOLD_PCT,
) -> list[SupportResistance]:
    """
    Get all active levels from a list.
    
    Requirements:
    - 2.6: Flag levels as active when current price is within 2%
    
    Args:
        levels: List of SupportResistance levels
        current_price: Current market price
        threshold_pct: Percentage threshold (default 0.02 = 2%)
        
    Returns:
        List of active SupportResistance levels
    """
    return [
        level for level in levels
        if is_level_active(level, current_price, threshold_pct)
    ]


# --- Nearest Level Functions ---

def get_nearest_support(
    levels: list[SupportResistance],
    current_price: float,
) -> Optional[SupportResistance]:
    """
    Get the nearest support level below the current price.
    
    Args:
        levels: List of SupportResistance levels
        current_price: Current market price
        
    Returns:
        Nearest support level below current price, or None if none exists
    """
    # Filter levels below current price
    below_price = [l for l in levels if l.level < current_price]
    
    if not below_price:
        return None
    
    # Return the highest level below current price (nearest support)
    return max(below_price, key=lambda x: x.level)


def get_nearest_resistance(
    levels: list[SupportResistance],
    current_price: float,
) -> Optional[SupportResistance]:
    """
    Get the nearest resistance level above the current price.
    
    Args:
        levels: List of SupportResistance levels
        current_price: Current market price
        
    Returns:
        Nearest resistance level above current price, or None if none exists
    """
    # Filter levels above current price
    above_price = [l for l in levels if l.level > current_price]
    
    if not above_price:
        return None
    
    # Return the lowest level above current price (nearest resistance)
    return min(above_price, key=lambda x: x.level)


# --- Complete Analysis ---

def analyze_support_resistance(
    candles: list[OHLCV],
    current_price: Optional[float] = None,
    window: int = DEFAULT_LOOKBACK_WINDOW,
    cluster_threshold_pct: float = DEFAULT_CLUSTER_THRESHOLD_PCT,
) -> SupportResistanceResult:
    """
    Perform complete support/resistance analysis on historical price data.
    
    Requirements:
    - 2.3: Identify support and resistance levels using up to 5 years of historical price data
    - 2.6: Flag levels as active when current price is within 2%
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        current_price: Current market price (uses last close if not provided)
        window: Lookback window for extrema detection
        cluster_threshold_pct: Threshold for clustering nearby levels
        
    Returns:
        SupportResistanceResult with all identified levels and active flags
        
    Raises:
        ValueError: If candles list is empty
    """
    if not candles:
        raise ValueError("Cannot analyze support/resistance with empty candle list")
    
    # Use last close price if current price not provided
    if current_price is None:
        current_price = candles[-1].close
    
    # Identify support and resistance levels
    support_levels = identify_support_levels(candles, window, cluster_threshold_pct)
    resistance_levels = identify_resistance_levels(candles, window, cluster_threshold_pct)
    
    # Get active levels
    active_support = get_active_levels(support_levels, current_price)
    active_resistance = get_active_levels(resistance_levels, current_price)
    
    # Determine timeframe
    timeframe = determine_timeframe(candles)
    
    logger.info(
        f"Support/Resistance analysis complete: "
        f"{len(support_levels)} support, {len(resistance_levels)} resistance, "
        f"{len(active_support)} active support, {len(active_resistance)} active resistance"
    )
    
    return SupportResistanceResult(
        support_levels=support_levels,
        resistance_levels=resistance_levels,
        active_support_levels=active_support,
        active_resistance_levels=active_resistance,
        current_price=current_price,
        timeframe=timeframe,
    )


# --- Convenience Functions for Design Interface ---

def find_support_levels(
    candles: list[OHLCV],
    lookback_years: int = 5,
) -> list[SupportResistance]:
    """
    Find support levels from historical price data.
    
    This is a convenience function matching the design document interface.
    
    Requirements:
    - 2.3: Identify support levels using up to 5 years of historical price data
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        lookback_years: Number of years of data to analyze (for documentation)
        
    Returns:
        List of SupportResistance objects representing support levels
    """
    return identify_support_levels(candles)


def find_resistance_levels(
    candles: list[OHLCV],
    lookback_years: int = 5,
) -> list[SupportResistance]:
    """
    Find resistance levels from historical price data.
    
    This is a convenience function matching the design document interface.
    
    Requirements:
    - 2.3: Identify resistance levels using up to 5 years of historical price data
    
    Args:
        candles: List of OHLCV candles sorted by timestamp ascending
        lookback_years: Number of years of data to analyze (for documentation)
        
    Returns:
        List of SupportResistance objects representing resistance levels
    """
    return identify_resistance_levels(candles)
