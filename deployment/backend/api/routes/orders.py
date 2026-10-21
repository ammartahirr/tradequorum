"""Order Executor API endpoints."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from api.routes.auth import get_current_user
from models.user import User

router = APIRouter()


class OrderResultResponse(BaseModel):
    id: UUID
    order_id: str
    trade_id: Optional[UUID]
    symbol: str
    status: str
    filled_price: float
    filled_quantity: float
    timestamp: datetime

    class Config:
        from_attributes = True


class PlaceOrderRequest(BaseModel):
    decision_id: UUID


class ModifyOrderRequest(BaseModel):
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@router.get("/", response_model=List[OrderResultResponse])
async def get_orders(
    symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get order results, optionally filtered."""
    from models.order import OrderResult
    
    query = select(OrderResult)
    
    if symbol:
        query = query.where(OrderResult.symbol == symbol)
    if status:
        query = query.where(OrderResult.status == status)
    
    query = query.order_by(OrderResult.timestamp.desc()).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{order_id}", response_model=OrderResultResponse)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific order by ID."""
    from models.order import OrderResult
    
    result = await db.execute(
        select(OrderResult).where(OrderResult.order_id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/place", response_model=OrderResultResponse)
async def place_order(
    request: PlaceOrderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Place an order based on a trade decision."""
    from services.order_service import OrderService
    
    service = OrderService()
    result = await service.place_order(request.decision_id)
    return result


@router.put("/{order_id}/modify")
async def modify_order(
    order_id: str,
    request: ModifyOrderRequest,
    current_user: User = Depends(get_current_user),
):
    """Modify an existing order's stop-loss or take-profit."""
    from services.order_service import OrderService
    
    service = OrderService()
    success = await service.modify_order(
        order_id=order_id,
        stop_loss=request.stop_loss,
        take_profit=request.take_profit,
    )
    if not success:
        raise HTTPException(status_code=400, detail="Failed to modify order")
    return {"message": "Order modified successfully"}


@router.delete("/{order_id}")
async def close_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
):
    """Close/cancel an order."""
    from services.order_service import OrderService
    
    service = OrderService()
    result = await service.close_position(order_id)
    return result


@router.get("/account/info")
async def get_account_info(
    current_user: User = Depends(get_current_user),
):
    """Get MT5 account information."""
    from services.order_service import OrderService
    
    service = OrderService()
    info = await service.get_account_info()
    return info
