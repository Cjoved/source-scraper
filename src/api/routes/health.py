"""Health route; intentionally lightweight and unauthenticated."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_qdrant_store
from src.api.errors import ApiError, ErrorCode
from src.api.schemas import HealthResponse
from src.storage.qdrant_store import QdrantStoreProtocol

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness + Qdrant connectivity probe",
    description=(
        "Lightweight check used by orchestrators (Docker, Kubernetes, CI smoke tests) "
        "and humans to confirm the service is up and that Qdrant is reachable.\n\n"
        "**Behavior**\n\n"
        "- Returns `200 OK` with the list of detected Qdrant collections when reachable.\n"
        "- Returns `503 SERVICE_UNAVAILABLE` with `Retry-After: 30` when the Qdrant "
        "ping fails, using the standard error envelope.\n\n"
        "**When to use**\n\n"
        "- Docker `HEALTHCHECK` directive.\n"
        "- Kubernetes liveness/readiness probes.\n"
        "- Manual sanity check after deploy: `curl http://host:8000/v1/health`.\n\n"
        "**Authentication**: not required."
    ),
    responses={
        200: {
            "description": "Service is up and Qdrant is reachable.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "qdrant": "reachable",
                        "collections": [
                            "prism_yield_records",
                            "prism_yield_knowledge",
                        ],
                    }
                }
            },
        },
        503: {
            "description": "Qdrant is unreachable; client should retry after 30s.",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "QDRANT_UNAVAILABLE",
                            "message": "Qdrant is unreachable",
                            "details": {},
                        }
                    }
                }
            },
        },
    },
)
def health(store: QdrantStoreProtocol = Depends(get_qdrant_store)) -> HealthResponse:
    """Ping Qdrant and report reachable collections."""
    if not store.ping():
        raise ApiError(
            ErrorCode.QDRANT_UNAVAILABLE,
            "Qdrant is unreachable",
            status_code=503,
            headers={"Retry-After": "30"},
        )
    return HealthResponse(
        status="ok",
        qdrant="reachable",
        collections=store.list_collection_names(),
    )
