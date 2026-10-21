"""API route modules."""
from api.routes.auth import router as auth_router
from api.routes.news import router as news_router
from api.routes.technical import router as technical_router
from api.routes.strategy import router as strategy_router
from api.routes.risk import router as risk_router
from api.routes.orders import router as orders_router
from api.routes.positions import router as positions_router
from api.routes.signals import router as signals_router
from api.routes.health import router as health_router
from api.routes.broker import router as broker_router
from api.routes.sandbox import router as sandbox_router

__all__ = [
    "auth_router",
    "news_router",
    "technical_router",
    "strategy_router",
    "risk_router",
    "orders_router",
    "positions_router",
    "signals_router",
    "health_router",
    "broker_router",
    "sandbox_router",
]
