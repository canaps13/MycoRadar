"""Synthetic polygons only. Geometry tests do not claim real forest coverage or predictions."""

import math

import pytest
from mycoradar.grid import (
    TO_WGS84,
    GridError,
    Mask,
    generate_grid,
    project,
    reproject,
)
from pyproj import Geod, Transformer, network
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union


def test_aligned_boundaries_negative_indices_and_stable_ids() -> None:
    first = generate_grid(box(-1000, -1000, 1000, 1000), (1000,)).cells
    assert {(cell.column, cell.row) for cell in first} == {(-1, -1), (-1, 0), (0, -1), (0, 0)}
    assert {cell.cell_id for cell in first} == {
        f"epsg6933-v1:1000:{column}:{row}" for column in (-1, 0) for row in (-1, 0)
    }
    assert all(cell.geometry.area == 1_000_000 for cell in first)
    expanded = generate_grid(box(-2000, -2000, 2000, 2000), (1000,)).cells
    by_id = {cell.cell_id: cell.geometry for cell in expanded}
    assert all(by_id[cell.cell_id].equals_exact(cell.geometry, 0) for cell in first)


def test_multiresolution_parent_alignment_and_area_conservation() -> None:
    boundary = box(0, 0, 2000, 2000)
    batch = generate_grid(boundary, (1000, 2000))
    assert batch == generate_grid(boundary, (2000, 1000))
    fine = [cell for cell in batch.cells if cell.resolution_m == 1000]
    coarse = [cell for cell in batch.cells if cell.resolution_m == 2000]
    assert len(fine) == 4 and len(coarse) == 1
    assert unary_union([cell.geometry for cell in fine]).equals(coarse[0].geometry)
    assert sum(cell.region_area_m2 for cell in fine) == boundary.area


def test_holes_and_partial_intersections_do_not_clip_canonical_cells() -> None:
    boundary = Polygon(box(0, 0, 3000, 3000).exterior, [box(1000, 1000, 2000, 2000).exterior])
    assert len(generate_grid(boundary, (1000,)).cells) == 8
    triangle = Polygon([(0, 0), (2000, 0), (0, 2000)])
    cells = generate_grid(triangle, (1000,)).cells
    assert len(cells) == 3
    assert sum(cell.region_area_m2 for cell in cells) == triangle.area
    assert all(cell.geometry.area == 1_000_000 for cell in cells)


def test_missing_masks_are_unknown_not_zero_and_do_not_exclude_cells() -> None:
    cells = generate_grid(box(0, 0, 1000, 1000), (1000,)).cells
    assert len(cells) == 1
    assert cells[0].land_fraction is None and cells[0].forest_fraction is None
    assert cells[0].land_status == cells[0].forest_status == "unavailable"


def test_known_sea_exclusion_coastline_and_forest_clipped_to_land() -> None:
    boundary = box(0, 0, 2000, 2000)
    coverage = box(-1000, -1000, 3000, 3000)
    land = Mask(box(0, 0, 500, 2000), coverage)
    forest = Mask(box(-500, 0, 250, 2000), coverage)
    cells = generate_grid(boundary, (1000,), land=land, forest=forest).cells
    assert len(cells) == 2 and all(cell.column == 0 for cell in cells)
    assert all(cell.land_fraction == 0.5 and cell.forest_fraction == 0.25 for cell in cells)
    assert all(cell.land_status == cell.forest_status == "complete" for cell in cells)
    assert generate_grid(boundary, (1000,), land=Mask(Polygon(), coverage)).cells == ()


def test_known_empty_forest_is_zero_but_partial_coverage_remains_unknown() -> None:
    boundary = box(0, 0, 1000, 1000)
    land = Mask(boundary, boundary)
    known = generate_grid(boundary, (1000,), land=land, forest=Mask(Polygon(), boundary)).cells[0]
    assert known.forest_fraction == 0
    partial = Mask(Polygon(), box(0, 0, 500, 1000))
    unknown = generate_grid(boundary, (1000,), land=partial, forest=Mask(boundary, boundary)).cells[
        0
    ]
    assert unknown.land_status == unknown.forest_status == "partial"
    assert unknown.land_fraction is None and unknown.forest_fraction is None
    forest_partial = generate_grid(boundary, (1000,), land=land, forest=partial).cells[0]
    assert forest_partial.forest_status == "partial" and forest_partial.forest_fraction is None


def test_outside_mask_coverage_is_unavailable() -> None:
    cell = generate_grid(
        box(0, 0, 1000, 1000),
        (1000,),
        land=Mask(Polygon(), box(3000, 3000, 4000, 4000)),
    ).cells[0]
    assert cell.land_status == "unavailable" and cell.land_fraction is None
    with pytest.raises(GridError, match="outside declared coverage"):
        Mask(box(0, 0, 1000, 1000), box(0, 0, 500, 500))


@pytest.mark.parametrize("size", [0, -1, 0.5, True])
def test_invalid_resolutions_are_rejected(size: int) -> None:
    with pytest.raises(GridError):
        generate_grid(box(0, 0, 1000, 1000), (size,))


def test_fine_grid_requires_explicit_experiment_and_work_is_bounded() -> None:
    with pytest.raises(GridError, match="experimental"):
        generate_grid(box(0, 0, 100, 100), (50,))
    assert len(generate_grid(box(0, 0, 100, 100), (50,), experimental_fine_grid=True).cells) == 4
    with pytest.raises(GridError, match="budget exceeded"):
        generate_grid(box(0, 0, 10000, 10000), (1000,), max_candidates=99)
    with pytest.raises(GridError, match="Duplicate"):
        generate_grid(box(0, 0, 1000, 1000), (1000, 1000))


@pytest.mark.parametrize(
    "geometry",
    [
        Polygon(),
        Point(0, 0),
        Polygon([(0, 0), (1, 1), (0, 1), (1, 0)]),
        Polygon([(0, 0, 1), (1, 0, 1), (1, 1, 1)]),
    ],
)
def test_invalid_geometries_are_rejected_without_repair(geometry: Polygon) -> None:
    with pytest.raises(GridError):
        project(geometry, "EPSG:4326")


@pytest.mark.parametrize("crs", ["EPSG:0", "unknown", "EPSG:4978", "EPSG:4979"])
def test_unknown_or_unsupported_crs_is_rejected(crs: str) -> None:
    with pytest.raises(GridError):
        project(box(0, 0, 1, 1), crs)


def test_lon_lat_axis_order_reprojection_and_equal_area() -> None:
    source = box(5, 43, 5.02, 43.02)
    metric = project(source, "EPSG:4326")
    assert metric.centroid.x > 0 and metric.centroid.y > 0
    expected, _ = Geod(ellps="WGS84").geometry_area_perimeter(source)
    assert metric.area == pytest.approx(abs(expected), rel=1e-5)
    back = reproject(metric, TO_WGS84)
    assert back.bounds == pytest.approx(source.bounds, abs=1e-7)
    local = reproject(source, Transformer.from_crs(4326, 2154, always_xy=True))
    assert project(local, "EPSG:2154").area == pytest.approx(metric.area, rel=1e-5)
    nz = project(box(174, -42, 174.01, -41.99), "EPSG:4326")
    assert nz.centroid.x > 0 and nz.centroid.y < 0 and math.isfinite(nz.area)


def test_poles_and_uncut_dateline_are_explicitly_unsupported() -> None:
    with pytest.raises(GridError, match="latitudes"):
        project(box(0, 87, 1, 88), "EPSG:4326")
    with pytest.raises(GridError, match="antimeridian"):
        project(box(-179, -1, 179, 1), "EPSG:4326")
    split = MultiPolygon([box(-180, -1, -179.99, -0.99), box(179.99, -1, 180, -0.99)])
    cells = generate_grid(project(split, "EPSG:4326"), (1000,), max_candidates=100)
    assert cells.cells and cells.candidate_count < 100


def test_network_transformations_are_not_silently_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(network, "is_network_enabled", lambda: True)
    with pytest.raises(GridError, match="Network"):
        project(box(0, 0, 1, 1), "EPSG:4326")
