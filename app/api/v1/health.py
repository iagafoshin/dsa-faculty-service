from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.schemas.common import HealthResponse, ReadyChecks, ReadyResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/ready", response_model=ReadyResponse)
async def get_ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return ReadyResponse(status="ok", checks=ReadyChecks(db="ok"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content=ReadyResponse(status="degraded", checks=ReadyChecks(db="down")).model_dump(),
        )
