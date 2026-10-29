"""HTTP liveness and database readiness; scientific coverage is still unavailable."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel
from sqlalchemy import Engine

from mycoradar.database import database_is_ready, get_engine

app = FastAPI(
    title="MycoRadar API",
    version="0.1.0",
    description="Service bootstrap. No source data or predictions are published yet.",
)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["mycoradar-api"]


@app.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    """Confirm HTTP liveness, without claiming database or source-data readiness."""
    return HealthResponse(status="ok", service="mycoradar-api")


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ready", "unavailable"]


@app.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "Database or migrations unavailable"}},
    tags=["operations"],
)
def ready(response: Response, engine: Annotated[Engine, Depends(get_engine)]) -> ReadyResponse:
    """Check PostGIS and schema head; this does not certify source-data availability."""
    if database_is_ready(engine):
        return ReadyResponse(status="ok", database="ready")
    response.status_code = 503
    return ReadyResponse(status="unavailable", database="unavailable")
