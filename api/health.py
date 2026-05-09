"""헬스 체크."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import engine, get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        ok = True
    except Exception:
        pass
    return {
        "status":     "ok" if ok else "degraded",
        "service":    settings.service_name,
        "db_connected": ok,
    }


@router.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
