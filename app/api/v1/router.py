from fastapi import APIRouter

from app.api.v1 import admin, health, meta, news, persons, publications, search

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(meta.router, prefix="/meta", tags=["meta"])
router.include_router(persons.router, tags=["persons"])
router.include_router(publications.router, tags=["publications"])
router.include_router(search.router, tags=["search"])
router.include_router(news.router, tags=["news"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
