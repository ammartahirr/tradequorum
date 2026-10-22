"""Broker connection status / control."""
from fastapi import APIRouter, Depends, HTTPException

from api.routes.auth import get_current_user
from core.config import settings
from models.user import User
from services.broker_service import get_broker, get_ibkr_client

router = APIRouter()


@router.get("/status")
async def broker_status():
    """Public: which broker is active and whether it is connected (no account data)."""
    broker = get_broker()
    info = {
        "broker": broker.name,
        "connected": broker.is_connected,
        "paper": broker.is_paper,
        "default_data_source": settings.DEFAULT_DATA_SOURCE,
    }
    if settings.BROKER.lower() == "ibkr" or settings.DEFAULT_DATA_SOURCE == "ibkr":
        ib = get_ibkr_client()
        info["ibkr"] = {
            "connected": ib.is_connected,
            "host": ib.config.host,
            "port": ib.config.port,
        }
    return info


@router.post("/connect")
async def broker_connect(current_user: User = Depends(get_current_user)):
    """Connect (or reconnect) to the configured broker."""
    broker = get_broker()
    try:
        await broker.connect()
    except Exception as e:
        raise HTTPException(502, str(e))
    return await broker.health()


@router.get("/positions")
async def broker_positions(current_user: User = Depends(get_current_user)):
    """Positions as reported by the broker itself."""
    broker = get_broker()
    try:
        return await broker.get_open_positions()
    except Exception as e:
        raise HTTPException(502, str(e))
