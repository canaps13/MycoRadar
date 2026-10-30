"""Bounded, offline equal-area grid generation. No scores, inference or HTTP calls."""

import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from numpy.typing import NDArray
from pyproj import CRS, Transformer, network
from pyproj.exceptions import ProjError
from shapely import get_coordinate_dimension, segmentize, transform
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

GRID_VERSION = "epsg6933-v1"
HARD_MAX_CANDIDATES = 100_000
MIN_AREA_M2 = 1e-6
TO_METRIC = Transformer.from_crs(4326, 6933, always_xy=True)
TO_WGS84 = Transformer.from_crs(6933, 4326, always_xy=True)
WORLD = box(*TO_METRIC.transform_bounds(-180, -86, 180, 86))


class GridError(ValueError):
    """An input cannot produce a scientifically honest grid under this contract."""


def reproject(geometry: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    def coordinates(points: NDArray[np.float64]) -> NDArray[np.float64]:
        x, y = transformer.transform(points[:, 0], points[:, 1], errcheck=True)
        return np.column_stack((x, y))

    return transform(geometry, coordinates)


def validate_polygon(geometry: BaseGeometry, *, allow_empty: bool = False) -> None:
    if not isinstance(geometry, Polygon | MultiPolygon):
        raise GridError("Polygon or MultiPolygon required")
    if geometry.is_empty:
        if allow_empty:
            return
        raise GridError("Empty geometry")
    if get_coordinate_dimension(geometry) != 2:
        raise GridError("Only explicit 2D geometries are supported")
    if not all(math.isfinite(value) for value in geometry.bounds) or not geometry.is_valid:
        raise GridError("Invalid or nonfinite geometry; no automatic repair")


def _densify(geometry: BaseGeometry, step: float) -> BaseGeometry:
    if not isinstance(geometry, Polygon | MultiPolygon):
        raise GridError("Polygon required for densification")
    parts = geometry.geoms if isinstance(geometry, MultiPolygon) else (geometry,)
    count = 0
    for part in parts:
        for ring in (part.exterior, *part.interiors):
            coordinates = list(ring.coords)
            count += 1
            for a, b in pairwise(coordinates):
                count += max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
                if count > 250_000:
                    raise GridError("Densification budget exceeded; split the source extract")
    return segmentize(geometry, step)


def project(geometry: BaseGeometry, source_crs: str, *, allow_empty: bool = False) -> BaseGeometry:
    """Reject unknown CRS, unsupported domain, and ambiguous antimeridian crossings."""
    validate_polygon(geometry, allow_empty=allow_empty)
    if network.is_network_enabled():  # type: ignore[attr-defined]  # Public pyproj re-export.
        raise GridError("Network PROJ transformations are disabled for reproducible jobs")
    try:
        crs = CRS.from_user_input(source_crs)
        if not crs.to_authority() or not (crs.is_geographic or crs.is_projected):
            raise GridError("An identified geographic/projected CRS is required")
        if len(crs.axis_info) != 2:
            raise GridError("Only two-dimensional source CRS are supported")
        if geometry.is_empty:
            return geometry
        if crs.is_geographic:
            if crs.axis_info[0].unit_name != "degree":
                raise GridError("Geographic input must use degrees")
            step = 0.01
        else:
            step = 1000 / crs.axis_info[0].unit_conversion_factor
        to_wgs = Transformer.from_crs(
            crs, 4326, always_xy=True, allow_ballpark=False, only_best=True
        )
        wgs = reproject(geometry, to_wgs)
        validate_polygon(wgs)
        left, bottom, right, top = wgs.bounds
        if not (-180 <= left <= right <= 180 and -86 <= bottom <= top <= 86):
            raise GridError("Grid v1 supports longitudes [-180,180] and latitudes [-86,86]")
        components = wgs.geoms if isinstance(wgs, MultiPolygon) else (wgs,)
        if any(part.bounds[2] - part.bounds[0] > 180 for part in components):
            raise GridError("Cut antimeridian-crossing polygons explicitly before this job")
        if crs.to_epsg() == 6933:
            return geometry  # Preserve exact grid-aligned metric coordinates.
        dense = _densify(geometry, step)
        wgs = reproject(dense, to_wgs)
        dense_wgs = _densify(wgs, 0.01)
        result = reproject(dense_wgs, TO_METRIC)
        validate_polygon(result)
        return result
    except ProjError as error:
        raise GridError("CRS transformation unavailable or invalid") from error


@dataclass(frozen=True)
class Mask:
    """Positive geometry AND the area where absence of a feature actually means zero."""

    geometry: BaseGeometry
    coverage: BaseGeometry

    def __post_init__(self) -> None:
        validate_polygon(self.geometry, allow_empty=True)
        validate_polygon(self.coverage)
        if not self.geometry.is_empty and not self.coverage.covers(self.geometry):
            raise GridError("Mask features extend outside declared coverage")


@dataclass(frozen=True)
class GridCell:
    cell_id: str
    resolution_m: int
    column: int
    row: int
    geometry: BaseGeometry  # Full canonical footprint in EPSG:6933, never region-clipped.
    region_area_m2: float
    land_fraction: float | None
    forest_fraction: float | None
    land_status: str
    forest_status: str


@dataclass(frozen=True)
class GridBatch:
    cells: tuple[GridCell, ...]
    candidate_count: int


def _status(mask: Mask | None, cell: BaseGeometry) -> str:
    if mask is None or mask.coverage.intersection(cell).area <= MIN_AREA_M2:
        return "unavailable"
    return "complete" if mask.coverage.covers(cell) else "partial"


def generate_grid(
    boundary: BaseGeometry,
    resolutions: tuple[int, ...],
    *,
    land: Mask | None = None,
    forest: Mask | None = None,
    max_candidates: int = 50_000,
    experimental_fine_grid: bool = False,
) -> GridBatch:
    """Inputs are projected, validated polygons. Areas/fractions refer to full grid footprints."""
    validate_polygon(boundary)
    if not WORLD.covers(boundary):
        raise GridError("Geometry outside the projected grid domain")
    if not resolutions or any(type(size) is not int or size <= 0 for size in resolutions):
        raise GridError("Positive integer resolutions are required")
    if len(set(resolutions)) != len(resolutions):
        raise GridError("Duplicate resolutions")
    if min(resolutions) < 250 and not experimental_fine_grid:
        raise GridError("Sub-250m grids require explicit experimental_fine_grid")
    if type(max_candidates) is not int or not 1 <= max_candidates <= HARD_MAX_CANDIDATES:
        raise GridError("Candidate budget out of bounds")
    components = boundary.geoms if isinstance(boundary, MultiPolygon) else (boundary,)
    candidates: set[tuple[int, int, int]] = set()
    # Check the rectangular work budget before allocating or doing per-cell intersections.
    work = 0
    for size in sorted(resolutions):
        for part in components:
            left, bottom, right, top = part.bounds
            columns = range(math.floor(left / size), math.ceil(right / size))
            rows = range(math.floor(bottom / size), math.ceil(top / size))
            work += len(columns) * len(rows)
            if work > max_candidates:
                raise GridError("Candidate budget exceeded; split territory or use coarser cells")
            candidates.update((size, column, row) for column in columns for row in rows)
    prepared = prep(boundary)
    cells = []
    for size, column, row in sorted(candidates):
        footprint: BaseGeometry = box(
            column * size, row * size, (column + 1) * size, (row + 1) * size
        )
        footprint = footprint.intersection(WORLD)
        if not prepared.intersects(footprint):
            continue
        region_area = footprint.intersection(boundary).area
        if region_area <= MIN_AREA_M2:
            continue  # Shared edges and floating-point slivers are not new cells.
        land_status = _status(land, footprint)
        land_fraction = None
        forest_fraction = None
        land_geometry = None
        if land is not None and land_status == "complete":
            land_geometry = land.geometry.intersection(footprint)
            if land_geometry.area <= MIN_AREA_M2:
                continue  # Exclude marine cells only when land coverage proves it.
            land_fraction = min(1.0, land_geometry.area / footprint.area)
        forest_status = _status(forest, footprint)
        if land_status == "unavailable":
            forest_status = "unavailable"
        elif land_status != "complete" and forest_status == "complete":
            forest_status = "partial"
        if forest is not None and land_geometry is not None and forest_status == "complete":
            # Forest cannot contribute area outside the known terrestrial mask.
            forest_fraction = min(
                land_fraction or 0.0,
                forest.geometry.intersection(land_geometry).area / footprint.area,
            )
        cells.append(
            GridCell(
                f"{GRID_VERSION}:{size}:{column}:{row}",
                size,
                column,
                row,
                footprint,
                region_area,
                land_fraction,
                forest_fraction,
                land_status,
                forest_status,
            )
        )
    return GridBatch(tuple(cells), work)
