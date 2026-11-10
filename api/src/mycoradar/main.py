"""HTTP liveness and database readiness; scientific coverage is still unavailable."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy import Engine

from mycoradar.catalog import DEFAULT_CATALOG, Catalog
from mycoradar.catalog_api import CatalogError, catalog_error_handler, query_error_handler, router
from mycoradar.database import database_is_ready, get_engine
from mycoradar.exploration import ExplorerBundle
from mycoradar.exploration import router as exploration_router
from mycoradar.settings import get_settings


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    path = settings.catalog_path or DEFAULT_CATALOG
    checksum = settings.catalog_sha256
    if settings.catalog_path is None:
        try:
            checksum = DEFAULT_CATALOG.with_suffix(".sha256").read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            checksum = None
    application.state.catalog = Catalog(path, checksum or "")
    application.state.explorer = ExplorerBundle(application.state.catalog)
    yield
    application.state.catalog = None
    application.state.explorer = None


app = FastAPI(
    title="MycoRadar API",
    version="0.1.0",
    description="Public geographic catalogue. Scientific predictions remain unavailable.",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(exploration_router)
app.add_exception_handler(CatalogError, catalog_error_handler)
app.add_exception_handler(RequestValidationError, query_error_handler)


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
