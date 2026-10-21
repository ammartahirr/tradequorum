"""Health check endpoints."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

router = APIRouter()


@router.get("")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """Detailed health check including database connectivity."""
    checks = {
        "api": "healthy",
        "database": "unknown",
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"
    
    overall = "healthy" if all(
        v == "healthy" for k, v in checks.items() if k != "timestamp"
    ) else "unhealthy"
    
    return {"status": overall, "checks": checks}
