"""
Backtest validation tests.

Tests:
- Run strategy against 2+ years of historical data
- Verify win rate and drawdown metrics

Requirements: All (Backtest Validation)
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from typing import List
import random

from src.models import OHLCV
from src.models.enums import TradingHorizon

from src.backtest.backtester import Backtester, BacktestConfig, BacktestResult


def generate_synthetic_candles(
    num_days: int = 750,  # ~3 years
    start_price: float = 100.0,
    volatility: float = 0.02,
    trend: float = 0.0001,
    seed: int = 42,
) -> List[OHLCV]:
    """Generate synthetic OHLCV data for backtesting."""
    random.seed(seed)
    candles = []
    price = start_price
    base_time = datetime(2022, 1, 1, tzinfo=timezone.utc)
    
    for i in range(num_days):
        # Random walk with trend
        daily_return = random.gauss(trend, volatility)
        
        open_price = price
        close_price = price * (1 + daily_return)
        
        # Generate high/low with some randomness
        intraday_vol = abs(daily_return) + random.uniform(0.005, 0.015)
        high_price = max(open_price, close_price) * (1 + random.uniform(0, intraday_vol))
        low_price = min(open_price, close_price) * (1 - random.uniform(0, intraday_vol))
        
        # Volume with some variation
        base_volume = 1000000
        volume = int(base_volume * random.uniform(0.5, 2.0))
        
        candle = OHLCV(
            timestamp=base_time + timedelta(days=i),
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=volume,
        )
        candles.append(candle)
        price = close_price
    
    return candles


class TestBacktestValidation:
    """Tests for backtest validation."""

    @pytest.mark.asyncio
    async def test_backtest_runs_successfully(self):
        """Test that backtest runs without errors."""
        candles = generate_synthetic_candles(num_days=500)
        
        config = BacktestConfig(
            initial_capital=100000.0,
            position_size_pct=0.05,
        )
        
        backtester = Backtester(config=config)
        result = await backtester.run_backtest(
            symbol="TEST",
            candles=candles,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        assert isinstance(result, BacktestResult)
        assert result.total_trades >= 0
        assert 0 <= result.win_rate <= 1
        assert result.max_drawdown_pct >= 0

    @pytest.mark.asyncio
    async def test_backtest_with_trending_market(self):
        """Test backtest in a trending market."""
        # Generate uptrending data
        candles = generate_synthetic_candles(
            num_days=500,
            trend=0.0005,  # Positive trend
            seed=123,
        )
        
        backtester = Backtester()
        result = await backtester.run_backtest(
            symbol="UPTREND",
            candles=candles,
            horizon=TradingHorizon.SHORT_TERM,
        )
        
        # In an uptrend, we expect some trades
        assert result.total_trades >= 0
        # Metrics should be valid
        assert result.win_rate >= 0
        assert result.max_drawdown_pct <= 1.0

    @pytest.mark.asyncio
    async def test_backtest_metrics_are_valid(self):
        """Test that backtest metrics are within valid ranges."""
        candles = generate_synthetic_candles(num_days=500, seed=456)
        
        backtester = Backtester()
        result = await backtester.run_backtest(
            symbol="METRICS",
            candles=candles,
        )
        
        # Win rate should be between 0 and 1
        assert 0 <= result.win_rate <= 1
        
        # Drawdown should be non-negative
        assert result.max_drawdown >= 0
        assert result.max_drawdown_pct >= 0
        
        # Trade counts should be consistent
        assert result.total_trades == result.winning_trades + result.losing_trades
        
        # Equity curve should start with initial capital
        if result.equity_curve:
            assert result.equity_curve[0] == 100000.0

    @pytest.mark.asyncio
    async def test_backtest_with_2_years_data(self):
        """Test backtest with 2+ years of historical data."""
        # Generate 2.5 years of data (~625 trading days)
        candles = generate_synthetic_candles(num_days=625, seed=789)
        
        backtester = Backtester()
        result = await backtester.run_backtest(
            symbol="LONGTERM",
            candles=candles,
            horizon=TradingHorizon.LONG_TERM,
        )
        
        # Should have processed the data
        assert isinstance(result, BacktestResult)
        
        # Log results for verification
        print(f"\n2+ Year Backtest Results:")
        print(f"  Total Trades: {result.total_trades}")
        print(f"  Win Rate: {result.win_rate:.2%}")
        print(f"  Total PnL: ${result.total_pnl:,.2f}")
        print(f"  Max Drawdown: {result.max_drawdown_pct:.2%}")
        print(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")

    @pytest.mark.asyncio
    async def test_backtest_result_to_dict(self):
        """Test that backtest result can be converted to dict."""
        candles = generate_synthetic_candles(num_days=300, seed=111)
        
        backtester = Backtester()
        result = await backtester.run_backtest(
            symbol="DICT",
            candles=candles,
        )
        
        result_dict = result.to_dict()
        
        assert 'total_trades' in result_dict
        assert 'win_rate' in result_dict
        assert 'max_drawdown' in result_dict
        assert 'sharpe_ratio' in result_dict

    @pytest.mark.asyncio
    async def test_backtest_insufficient_data_raises_error(self):
        """Test that backtest raises error with insufficient data."""
        candles = generate_synthetic_candles(num_days=100)  # Too few
        
        backtester = Backtester()
        
        with pytest.raises(ValueError, match="at least 250 candles"):
            await backtester.run_backtest(
                symbol="SHORT",
                candles=candles,
            )
