"""
Application configuration using Pydantic Settings.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    
    # CORS – comma-separated list or JSON list
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    
    # AWS Bedrock (for Claude Opus 4.5)
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "anthropic.claude-opus-4-5-20250514"
    
    # AWS SageMaker (for pattern recognition)
    SAGEMAKER_ENDPOINT: str = "ai-trading-pattern-recognition"
    
    # Broker selection: "ibkr" (Interactive Brokers), "paper" (in-memory simulator), "mt5" (legacy)
    BROKER: str = "paper"

    # Interactive Brokers (IB Gateway / TWS). Paper gateway port = 4002 (TWS paper = 7497).
    # In docker-compose the gateway container exposes paper on ib-gateway:4004.
    IBKR_HOST: str = "127.0.0.1"
    IBKR_PORT: int = 4002
    IBKR_CLIENT_ID: int = 17
    IBKR_ACCOUNT: str = ""
    IBKR_MARKET_DATA_TYPE: int = 3  # 1=live (needs subscription), 3=delayed (free)
    IBKR_READONLY: bool = False
    IBKR_ALLOW_LIVE_TRADING: bool = False  # safety: orders only on paper (DU…) accounts

    # Market data source for the sandbox/technical agent: "ibkr" | "yahoo" | "synthetic"
    DEFAULT_DATA_SOURCE: str = "yahoo"
    SANDBOX_MAX_BARS: int = 5000
    SANDBOX_MAX_CONCURRENT: int = 2

    # Background jobs (news scraping, technical analysis, position monitoring)
    ENABLE_SCHEDULER: bool = True

    # MT5/Exness Trading (legacy, Windows only)
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
    
    # Trading Symbols (broker-neutral: stocks like AAPL, forex like EURUSD, BTCUSD, XAUUSD)
    TRADING_SYMBOLS: str = "AAPL,MSFT,SPY,EURUSD,BTCUSD"
    
    # Scheduler
    NEWS_SCRAPE_INTERVAL_MINUTES: int = 5
    TECHNICAL_ANALYSIS_INTERVAL_MINUTES: int = 1
    
    # Encryption
    ENCRYPTION_KEY: Optional[str] = None
    
    # Admin User
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = "change_this_secure_password"
    
    @property
    def cors_origins_list(self) -> List[str]:
        v = self.CORS_ORIGINS.strip()
        if v.startswith("["):
            import json
            return [str(o) for o in json.loads(v)]
        return [o.strip() for o in v.split(",") if o.strip()]

    @property
    def trading_symbols_list(self) -> List[str]:
        """Get trading symbols as a list."""
        return [s.strip().upper() for s in self.TRADING_SYMBOLS.split(",") if s.strip()]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
