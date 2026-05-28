import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.admin import router as admin_router
from app.config import settings
from app.experts import router as experts_router
from app.routes import router as v1_router
from app.scheduler import shutdown_scheduler, start_scheduler_if_enabled
from app.ui import router as ui_router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "unprocessable_entity",
    500: "server_error",
    503: "service_unavailable",
}

app = FastAPI(
    title="DSA Faculty Service API",
    version=settings.app_version,
    description=(
        "DSA Faculty Service — faculty-data microservice of the Digital Student Assistant "
        "platform. Source of truth: openapi.yaml in repo root."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    body = exc.detail
    if isinstance(body, dict) and "code" in body and "message" in body:
        return JSONResponse(status_code=exc.status_code, content=body)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": _STATUS_CODES.get(exc.status_code, "error"), "message": str(exc.detail)},
    )


# experts_router зарегистрирован ПЕРЕД v1_router, чтобы конкретные пути
# вроде /publications/semantic-search не перехватывались более общим
# /publications/{pub_id} из v1_router.
app.include_router(experts_router, prefix="/api/v1")
app.include_router(v1_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1/admin")

# HTML UI на корневых путях (/, /persons, /publications, /persons/{id}).
# JSON API остаётся под /api/v1/.
app.include_router(ui_router)


# === Scheduler (опциональный, активируется через ENV SCHEDULE_DAYS > 0) ===

@app.on_event("startup")
async def _startup_scheduler() -> None:
    start_scheduler_if_enabled()


@app.on_event("shutdown")
async def _shutdown_scheduler() -> None:
    shutdown_scheduler()
