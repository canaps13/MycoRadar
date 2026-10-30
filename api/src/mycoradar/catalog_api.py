"""Versioned geographic catalogue, bounded envelope filters and typed errors."""

from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from mycoradar.catalog import Catalog
from mycoradar.catalog_models import (
    Bounds,
    Cell,
    Country,
    ErrorDetail,
    ErrorResponse,
    Identifier,
    Page,
    Pagination,
    Region,
    Snapshot,
    Source,
    Species,
)


class CatalogError(Exception):
    def __init__(
        self,
        status_code: int,
        code: Literal[
            "invalid_query", "region_not_found", "catalog_version_conflict", "catalog_unavailable"
        ],
        message: str,
    ) -> None:
        self.status_code = status_code
        self.body = ErrorResponse(error=ErrorDetail(code=code, message=message))


async def catalog_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CatalogError)
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.body.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


async def query_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return await catalog_error_handler(
        _request,
        CatalogError(
            422, "invalid_query", "Query parameters do not satisfy the documented contract."
        ),
    )


def get_catalog(request: Request) -> Catalog:
    allowed = {"limit", "offset", "bbox", "country", "region_id", "catalog_version"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise CatalogError(422, "invalid_query", "Unknown or repeated query parameter.")
    catalog: Catalog | None = getattr(request.app.state, "catalog", None)
    if catalog is None or catalog.snapshot is None:
        raise CatalogError(503, "catalog_unavailable", "No valid public catalogue is loaded.")
    return catalog


def parse_bounds(value: str | None) -> Bounds | None:
    if value is None:
        return None
    try:
        parts = tuple(float(p) for p in value.split(","))
        if len(parts) != 4:
            raise ValueError
        west, south, east, north = parts
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError
        if (east - west) * (north - south) > 25:
            raise ValueError
    except ValueError:
        raise CatalogError(
            422,
            "invalid_query",
            "bbox requires west,south,east,north; maximum area 25 square degrees; "
            "no antimeridian crossing.",
        ) from None
    return west, south, east, north


def intersects(a: Bounds, b: Bounds) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


class Filters:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=50_000)] = 0,
        bbox: Annotated[str | None, Query(max_length=160)] = None,
        country: Country | None = None,
        region_id: Identifier | None = None,
        catalog_version: Annotated[str | None, Query(pattern=r"^[a-f0-9]{64}$")] = None,
    ) -> None:
        self.limit, self.offset = limit, offset
        self.bounds = parse_bounds(bbox)
        self.country, self.region_id, self.catalog_version = country, region_id, catalog_version


router = APIRouter(
    prefix="/v1",
    tags=["public-catalogue"],
    responses={code: {"model": ErrorResponse} for code in (404, 409, 422, 503)},
)
CatalogDep = Annotated[Catalog, Depends(get_catalog)]
FiltersDep = Annotated[Filters, Depends()]


def page_for(
    kind: Literal["regions", "species", "cells", "metadata"],
    request: Request,
    catalog: Catalog,
    query: Filters,
) -> Page[Region | Species | Cell | Source]:
    snapshot = catalog.snapshot
    assert isinstance(snapshot, Snapshot)
    if query.catalog_version and query.catalog_version != catalog.version:
        raise CatalogError(
            409, "catalog_version_conflict", "Catalogue changed; restart pagination."
        )
    regions = catalog.region_index
    if query.region_id and query.region_id not in regions:
        raise CatalogError(404, "region_not_found", "Region is not in the public catalogue.")
    if kind == "cells" and query.region_id is None and query.bounds is None:
        raise CatalogError(
            422, "invalid_query", "A region_id or bounded bbox is required for cells."
        )
    if kind == "metadata" and (query.bounds or query.country or query.region_id):
        raise CatalogError(422, "invalid_query", "Spatial filters are not supported for metadata.")
    if kind == "species" and query.bounds:
        raise CatalogError(
            422, "invalid_query", "bbox is not supported for species; use region_id."
        )
    records = catalog.collections[kind]
    matched: list[Region | Species | Cell | Source] = []
    for record in records:
        region_ids = (
            (record.id,) if isinstance(record, Region) else getattr(record, "region_ids", ())
        )
        if query.region_id and query.region_id not in region_ids:
            continue
        if query.country and not any(regions[r].country_code == query.country for r in region_ids):
            continue
        if (
            query.bounds
            and isinstance(record, Region | Cell)
            and not intersects(record.bounds, query.bounds)
        ):
            continue
        matched.append(record)
    end = query.offset + query.limit
    next_url = None
    if end < len(matched):
        parameters = dict(request.query_params)
        parameters.update(offset=str(end), limit=str(query.limit), catalog_version=catalog.version)
        next_url = f"?{urlencode(parameters)}"
    state = getattr(snapshot.availability, kind)
    return Page[Region | Species | Cell | Source](
        status=state.status,
        reason=state.reason,
        catalog_version=catalog.version,
        published_at=snapshot.published_at,
        pagination=Pagination(
            limit=query.limit, offset=query.offset, total=len(matched), next=next_url
        ),
        items=tuple(matched[query.offset : end]),
        spatial_filter="envelope_intersects" if query.bounds else None,
    )


@router.get(
    "/regions", response_model=Page[Region], summary="List public administrative display geometries"
)
def regions(request: Request, catalog: CatalogDep, query: FiltersDep) -> object:
    return page_for("regions", request, catalog, query)


@router.get(
    "/species",
    response_model=Page[Species],
    summary="List admitted public taxa, never inferred occurrences",
)
def species(request: Request, catalog: CatalogDep, query: FiltersDep) -> object:
    return page_for("species", request, catalog, query)


@router.get(
    "/cells",
    response_model=Page[Cell],
    summary="List precomputed public cells; no HTTP grid generation",
)
def cells(request: Request, catalog: CatalogDep, query: FiltersDep) -> object:
    return page_for("cells", request, catalog, query)


@router.get(
    "/metadata",
    response_model=Page[Source],
    summary="List source versions, rights, dates and transformations",
)
def metadata(request: Request, catalog: CatalogDep, query: FiltersDep) -> object:
    return page_for("metadata", request, catalog, query)
