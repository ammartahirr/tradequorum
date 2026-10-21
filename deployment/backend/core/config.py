"""
Application configuration using Pydantic Settings.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "AI Trading System"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://trading:trading@postgres:5432/trading"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis (for caching and pub/sub)
    REDIS_URL: str = "redis://redis:6379/0"
    
    # JWT Authentication
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # AWS Bedrock (for Claude Opus 4.5)
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "anthropic.claude-opus-4-5-20250514"
    
    # AWS SageMaker (for pattern recognition)
    SAGEMAKER_ENDPOINT: str = "ai-trading-pattern-recognition"
    
    # MT5/Exness Trading
    MT5_LOGIN: str = ""
    MT5_PASSWORD: str = ""
    MT5_SERVER: str = "Exness-MT5Real"
    
    # News API Keys
    REUTERS_API_KEY: Optional[str] = None
    BLOOMBERG_API_KEY: Optional[str] = None
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_BEARER_TOKEN: Optional[str] = None
    SEC_EDGAR_USER_AGENT: str = "AI-Trading-System contact@example.com"
    
    # Alternative News APIs
    NEWSAPI_KEY: Optional[str] = None
    ALPHA_VANTAGE_API_KEY: Optional[str] = None
    FINNHUB_API_KEY: Optional[str] = None
    POLYGON_API_KEY: Optional[str] = None
    TWELVE_DATA_API_KEY: Optional[str] = None
    
    # Risk Limits
    MAX_POSITION_PCT: float = 0.05
    MAX_PORTFOLIO_RISK_PCT: float = 0.02
    MAX_CORRELATED_EXPOSURE: float = 0.20
    MAX_DAILY_LOSS_PCT: float = 0.05
    MAX_OPEN_POSITIONS: int = 10
    
    # Trading Symbols
    TRADING_SYMBOLS: str = "BTCUSD,ETHUSD,XAUUSD,EURUSD,GBPUSD"
    
    # Scheduler
    NEWS_SCRAPE_INTERVAL_MINUTES: int = 5
    TECHNICAL_ANALYSIS_INTERVAL_MINUTES: int = 1
    
    # Encryption
    ENCRYPTION_KEY: Optional[str] = None
    
    # Admin User
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "change_this_secure_password"
    
    @property
    def trading_symbols_list(self) -> List[str]:
        """Get trading symbols as a list."""
        return [s.strip() for s in self.TRADING_SYMBOLS.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
