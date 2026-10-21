"""Technical Agent service - integrates with AWS SageMaker for pattern recognition."""
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4

import boto3
from botocore.config import Config

from core.config import settings
from core.database import get_db_context
from models.signal import TechnicalSignal
from api.websocket import broadcast_signal

logger = logging.getLogger(__name__)


class TechnicalService:
    """Service for technical analysis using existing indicators and AWS SageMaker."""
    
    def __init__(self):
        # Configure boto3 for cross-cloud access to AWS SageMaker
        self.sagemaker_client = boto3.client(
            "sagemaker-runtime",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                connect_timeout=5,
                read_timeout=10,  # 10s timeout for SageMaker
            ),
        )
        
        # Tracked symbols (could be loaded from config/database)
        self.tracked_symbols = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"]
    
    async def analyze_all_symbols(self):
        """Analyze all tracked symbols."""
        for symbol in self.tracked_symbols:
            try:
                await self.analyze_symbol(symbol)
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
    
    async def analyze_symbol(self, symbol: str, timeframe: str = "1d") -> TechnicalSignal:
        """Perform technical analysis on a symbol."""
        # Import existing technical analysis modules
        from src.agents.technical.indicators import calculate_rsi, calculate_macd, calculate_bollinger
        from src.agents.technical.confluence import detect_confluence
        from src.agents.technical.support_resistance import find_support_resistance
        from src.agents.technical.market_data import fetch_ohlcv
        
        # Fetch market data
        candles = await fetch_ohlcv(symbol, timeframe, limit=500)
        
        if not candles:
            raise ValueError(f"No market data available for {symbol}")
        
        current_price = candles[-1].close
        
        # Calculate indicators
        rsi = calculate_rsi(candles)
        macd_data = calculate_macd(candles)
        bollinger = calculate_bollinger(candles)
        
        # Find support/resistance
        support_levels, resistance_levels = find_support_resistance(candles)
        
        # Detect confluence
        confluence = detect_confluence(
            candles=candles,
            rsi=rsi,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
        )
        
        # Determine trend and condition
        trend = self._determine_trend(candles, macd_data)
        condition = self._determine_condition(rsi)
        
        # Volume trend
        volume_trend = self._determine_volume_trend(candles)
        
        # Optional: SageMaker pattern prediction
        ml_prediction = await self._get_ml_prediction(symbol, candles)
        
        # Create signal
        signal = TechnicalSignal(
            signal_id=uuid4(),
            symbol=symbol,
            trend=trend,
            condition=condition,
            rsi=rsi,
            current_price=current_price,
            support_levels=[
                {"level": s.level, "strength": s.strength, "timeframe": s.timeframe, "last_tested": s.last_tested.isoformat()}
                for s in support_levels[:5]
            ],
            resistance_levels=[
                {"level": r.level, "strength": r.strength, "timeframe": r.timeframe, "last_tested": r.last_tested.isoformat()}
                for r in resistance_levels[:5]
            ],
            confluence_score=confluence.score,
            confluence_factors=confluence.factors,
            confluence_description=confluence.description,
            volume_trend=volume_trend,
            interest_rate_impact=0.0,  # Could integrate with economic data
            timestamp=datetime.utcnow(),
        )
        
        # Persist to database
        async with get_db_context() as db:
            db.add(signal)
        
        # Broadcast to WebSocket clients
        await broadcast_signal("technical", {
            "signal_id": str(signal.signal_id),
            "symbol": symbol,
            "trend": trend,
            "condition": condition,
            "rsi": rsi,
            "confluence_score": confluence.score,
        })
        
        return signal
    
    def _determine_trend(self, candles, macd_data) -> str:
        """Determine trend direction from price action and MACD."""
        # Simple trend determination using moving averages
        closes = [c.close for c in candles]
        
        if len(closes) < 200:
            return "sideways"
        
        ma_50 = sum(closes[-50:]) / 50
        ma_200 = sum(closes[-200:]) / 200
        current = closes[-1]
        
        if current > ma_50 > ma_200:
            if macd_data.get("histogram", 0) > 0:
                return "strong_uptrend"
            return "uptrend"
        elif current < ma_50 < ma_200:
            if macd_data.get("histogram", 0) < 0:
                return "strong_downtrend"
            return "downtrend"
        return "sideways"
    
    def _determine_condition(self, rsi: float) -> str:
        """Determine market condition from RSI."""
        if rsi <= 30:
            return "oversold"
        elif rsi >= 70:
            return "overbought"
        return "neutral"
    
    def _determine_volume_trend(self, candles) -> str:
        """Determine volume trend."""
        if len(candles) < 20:
            return "stable"
        
        recent_avg = sum(c.volume for c in candles[-5:]) / 5
        historical_avg = sum(c.volume for c in candles[-20:]) / 20
        
        if recent_avg > historical_avg * 1.5:
            return "increasing"
        elif recent_avg < historical_avg * 0.7:
            return "decreasing"
        return "stable"
    
    async def _get_ml_prediction(self, symbol: str, candles) -> Optional[dict]:
        """Get ML pattern prediction from SageMaker (with timeout fallback)."""
        import json
        
        try:
            # Prepare features for SageMaker
            features = self._prepare_features(candles)
            
            response = self.sagemaker_client.invoke_endpoint(
                EndpointName=settings.SAGEMAKER_ENDPOINT,
                ContentType="application/json",
                Body=json.dumps({"symbol": symbol, "features": features}),
            )
            
            result = json.loads(response["Body"].read())
            return result
            
        except Exception as e:
            logger.warning(f"SageMaker prediction failed, skipping: {e}")
            return None
    
    def _prepare_features(self, candles) -> List[float]:
        """Prepare feature vector for ML model."""
        # Simple feature extraction - returns, volatility, etc.
        closes = [c.close for c in candles[-50:]]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        
        return returns
    
    async def get_indicators(self, symbol: str, timeframe: str = "1d") -> dict:
        """Get current technical indicators for a symbol."""
        from src.agents.technical.indicators import calculate_rsi, calculate_macd, calculate_bollinger
        from src.agents.technical.market_data import fetch_ohlcv
        
        candles = await fetch_ohlcv(symbol, timeframe, limit=200)
        
        rsi = calculate_rsi(candles)
        macd = calculate_macd(candles)
        bollinger = calculate_bollinger(candles)
        
        closes = [c.close for c in candles]
        ma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        ma_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
        
        return {
            "symbol": symbol,
            "rsi": rsi,
            "macd": macd,
            "bollinger": bollinger,
            "ma_50": ma_50,
            "ma_200": ma_200,
            "current_price": candles[-1].close,
            "timestamp": datetime.utcnow(),
        }
    
    async def get_confluence(self, symbol: str) -> dict:
        """Get confluence analysis for a symbol."""
        signal = await self.analyze_symbol(symbol)
        return {
            "score": signal.confluence_score,
            "factors": signal.confluence_factors,
            "description": signal.confluence_description,
        }
    
    async def get_support_resistance(self, symbol: str, lookback_years: int = 5) -> dict:
        """Get support and resistance levels for a symbol."""
        from src.agents.technical.support_resistance import find_support_resistance
        from src.agents.technical.market_data import fetch_ohlcv
        
        # Fetch historical data
        candles = await fetch_ohlcv(symbol, "1d", limit=lookback_years * 252)
        
        support_levels, resistance_levels = find_support_resistance(candles)
        
        return {
            "symbol": symbol,
            "support_levels": [
                {"level": s.level, "strength": s.strength, "timeframe": s.timeframe}
                for s in support_levels
            ],
            "resistance_levels": [
                {"level": r.level, "strength": r.strength, "timeframe": r.timeframe}
                for r in resistance_levels
            ],
        }
