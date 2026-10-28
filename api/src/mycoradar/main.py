"""HTTP liveness only; data readiness and scientific results arrive in later tasks."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

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
