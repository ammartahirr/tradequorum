"""
FastAPI Backend for AI Trading System.
Replaces AWS Lambda handlers with a unified API server.
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    auth_router,
    news_router,
    technical_router,
    strategy_router,
    risk_router,
    orders_router,
    positions_router,
    signals_router,
    health_router,
)
from api.websocket import ConnectionManager
from core.config import settings
from core.database import init_db, close_db
from core.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    await init_db()
    await start_scheduler()
    yield
    # Shutdown
    await stop_scheduler()
    await close_db()


app = FastAPI(
    title="AI Trading System API",
    description="Multi-agent trading platform with News, Technical, and Strategy agents",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, prefix="/api/health", tags=["Health"])
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(news_router, prefix="/api/news", tags=["News Agent"])
app.include_router(technical_router, prefix="/api/technical", tags=["Technical Agent"])
app.include_router(strategy_router, prefix="/api/strategy", tags=["Strategy Agent"])
app.include_router(risk_router, prefix="/api/risk", tags=["Risk Manager"])
app.include_router(orders_router, prefix="/api/orders", tags=["Order Executor"])
app.include_router(positions_router, prefix="/api/positions", tags=["Position Manager"])
app.include_router(signals_router, prefix="/api/signals", tags=["Signals"])

# WebSocket manager
ws_manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages (ping/pong, subscriptions)
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "AI Trading System",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
    }
