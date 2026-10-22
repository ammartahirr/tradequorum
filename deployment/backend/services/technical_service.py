"""Technical Agent service – runs the real src Technical Agent on broker/Yahoo candles."""
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from core.config import settings
from core.database import get_db_context
from models.signal import TechnicalSignal
from api.websocket import broadcast_signal
from services.broker_service import get_data_provider

logger = logging.getLogger(__name__)

# Dashboard/API timeframe aliases -> internal timeframe codes
TIMEFRAME_ALIASES = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D1", "1w": "W1", "1mo": "MN1",
}


def normalize_timeframe(tf: str) -> str:
    return TIMEFRAME_ALIASES.get(tf.lower(), tf.upper())


def _level_dict(lvl) -> dict:
    return {
        "level": lvl.level,
        "strength": lvl.strength,
        "timeframe": lvl.timeframe,
        "last_tested": lvl.last_tested.isoformat(),
    }


class TechnicalService:
    """Technical analysis using the shared src/ indicators, S/R and confluence logic."""

    def __init__(self, data_source: Optional[str] = None):
        from src.agents.technical.signal_generator import TechnicalSignalGenerator

        self.provider = get_data_provider(data_source)
        # SageMaker enhancement only when explicitly configured with AWS creds
        use_sagemaker = bool(settings.AWS_ACCESS_KEY_ID and settings.SAGEMAKER_ENDPOINT)
        self.generator = TechnicalSignalGenerator(use_sagemaker=use_sagemaker)
        self.tracked_symbols = settings.trading_symbols_list

    async def _candles(self, symbol: str, timeframe: str, count: int):
        candles = await self.provider.get_candles(symbol.upper(), normalize_timeframe(timeframe), count)
        if not candles:
            raise ValueError(f"No market data available for {symbol}")
        return candles

    async def analyze_all_symbols(self):
        for symbol in self.tracked_symbols:
            try:
                await self.analyze_symbol(symbol)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")

    async def analyze_symbol(self, symbol: str, timeframe: str = "1d") -> TechnicalSignal:
        """Generate a TechnicalSignal with the real Technical Agent and persist it."""
        candles = await self._candles(symbol, timeframe, 500)
        sig = await self.generator.generate_signal(symbol.upper(), candles)

        row = TechnicalSignal(
            signal_id=uuid4(),
            symbol=sig.symbol,
            trend=sig.trend.value,
            condition=sig.condition.value,
            rsi=sig.rsi,
            current_price=sig.current_price,
            support_levels=[_level_dict(s) for s in sig.support_levels[:5]],
            resistance_levels=[_level_dict(r) for r in sig.resistance_levels[:5]],
            confluence_score=sig.confluence.score,
            confluence_factors=sig.confluence.factors,
            confluence_description=sig.confluence.description,
            volume_trend=sig.volume_trend,
            interest_rate_impact=sig.interest_rate_impact,
            timestamp=sig.timestamp,
        )
        async with get_db_context() as db:
            db.add(row)

        await broadcast_signal("technical", {
            "signal_id": str(row.signal_id),
            "symbol": row.symbol,
            "trend": row.trend,
            "condition": row.condition,
            "rsi": row.rsi,
            "current_price": row.current_price,
            "confluence_score": row.confluence_score,
        })
        return row

    async def get_indicators(self, symbol: str, timeframe: str = "1d") -> dict:
        from src.agents.technical.indicators import (
            calculate_bollinger_bands, calculate_macd, calculate_rsi,
        )

        candles = await self._candles(symbol, timeframe, 300)
        closes = [c.close for c in candles]
        return {
            "symbol": symbol.upper(),
            "rsi": calculate_rsi(candles),
            "macd": asdict(calculate_macd(candles)),
            "bollinger": asdict(calculate_bollinger_bands(candles)),
            "ma_50": sum(closes[-50:]) / 50 if len(closes) >= 50 else None,
            "ma_200": sum(closes[-200:]) / 200 if len(closes) >= 200 else None,
            "current_price": closes[-1],
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_confluence(self, symbol: str) -> dict:
        signal = await self.analyze_symbol(symbol)
        return {
            "score": signal.confluence_score,
            "factors": signal.confluence_factors,
            "description": signal.confluence_description,
        }

    async def get_support_resistance(self, symbol: str, lookback_years: int = 5) -> dict:
        from src.agents.technical.support_resistance import (
            identify_resistance_levels, identify_support_levels,
        )

        candles = await self._candles(symbol, "D1", max(260, lookback_years * 252))
        return {
            "symbol": symbol.upper(),
            "support_levels": [_level_dict(s) for s in identify_support_levels(candles)],
            "resistance_levels": [_level_dict(r) for r in identify_resistance_levels(candles)],
        }
