"""System endpoints: health, config."""

from fastapi import APIRouter

from web.api.dependencies import get_config_manager
from web.api.schemas import HealthResponse

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version="0.1.0")


@router.get("/config")
def get_config() -> dict[str, object]:
    cm = get_config_manager()
    raw: dict[str, object] = dict(cm.raw_config)
    # Strip sensitive fields
    sanitized = {k: v for k, v in raw.items() if k not in ("api_key", "credentials")}
    return sanitized
