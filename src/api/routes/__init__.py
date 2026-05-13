"""API route modules; mounted under /v1 by `src.api.app`."""

from __future__ import annotations

from fastapi import APIRouter

from src.api.routes import admin, health, knowledge, yield_data


def build_v1_router() -> APIRouter:
    router = APIRouter(prefix="/v1")
    router.include_router(health.router)
    router.include_router(yield_data.router)
    router.include_router(knowledge.router)
    router.include_router(admin.router)
    return router
