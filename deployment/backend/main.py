"""
FastAPI Backend for AI Trading System.
Replaces AWS Lambda handlers with a unified API server.

Run with a SINGLE worker: the scheduler, the WebSocket connection registry
and the IB Gateway socket are all in-process state.
"""
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from api.routes import (  # noqa: E402
    auth_router,
    broker_router,
    health_router,
    news_router,
    orders_router,
    positions_router,
    quant_router,
    risk_router,
    sandbox_router,
    signals_router,
    strategy_router,
    technical_router,
)
from api.websocket import manager as ws_manager  # noqa: E402  (shared with broadcast helpers)
from core.database import close_db, init_db, seed_admin_user  # noqa: E402
from core.scheduler import start_scheduler, stop_scheduler  # noqa: E402
from services.broker_service import connect_broker, disconnect_broker  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    try:
        await init_db()
        await seed_admin_user()
    except Exception as e:
        logger.error(f"Database initialisation failed: {e}")
    await connect_broker()
    if settings.ENABLE_SCHEDULER:
        await start_scheduler()
    yield
    if settings.ENABLE_SCHEDULER:
        await stop_scheduler()
    await disconnect_broker()
    await close_db()


app = FastAPI(
    title="AI Trading System API",
    description="Multi-agent trading platform with News, Technical, and Strategy agents",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/health", tags=["Health"])
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(news_router, prefix="/api/news", tags=["News Agent"])
app.include_router(technical_router, prefix="/api/technical", tags=["Technical Agent"])
app.include_router(strategy_router, prefix="/api/strategy", tags=["Strategy Agent"])
app.include_router(risk_router, prefix="/api/risk", tags=["Risk Manager"])
app.include_router(orders_router, prefix="/api/orders", tags=["Order Executor"])
app.include_router(positions_router, prefix="/api/positions", tags=["Position Manager"])
app.include_router(signals_router, prefix="/api/signals", tags=["Signals"])
app.include_router(broker_router, prefix="/api/broker", tags=["Broker"])
app.include_router(sandbox_router, prefix="/api/sandbox", tags=["Training Sandbox"])
app.include_router(quant_router, prefix="/api/quant", tags=["Quant Engine"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates (JSON messages)."""
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                msg = {"type": raw}
            mtype = msg.get("type") if isinstance(msg, dict) else None
            if mtype == "ping":
                await websocket.send_text(json.dumps({
                    "type": "pong", "payload": {}, "timestamp": datetime.utcnow().isoformat(),
                }))
            elif mtype == "subscribe" and msg.get("symbol"):
                ws_manager.subscribe(websocket, str(msg["symbol"]).upper())
            elif mtype == "unsubscribe" and msg.get("symbol"):
                ws_manager.unsubscribe(websocket, str(msg["symbol"]).upper())
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "AI Trading System",
        "version": "1.1.0",
        "status": "running",
        "broker": settings.BROKER,
        "timestamp": datetime.utcnow().isoformat(),
    }
