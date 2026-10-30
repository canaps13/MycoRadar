"""Synthetic fixtures only: no real boundaries, occurrences or prediction results."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from mycoradar.database import ROOT, database_is_ready
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration

AREA = "MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))"


@pytest.fixture
def populated(database: tuple[Engine, Config]) -> Iterator[Connection]:
    engine, _ = database
    with engine.connect() as connection:
        transaction = connection.begin()
        for statement in (
            "INSERT INTO countries VALUES ('FR', 'Synthetic France'), ('NZ', 'Synthetic NZ')",
            """INSERT INTO regions (id, country_code, name, timezone, geometry)
               VALUES ('test:r1', 'FR', 'Synthetic region', 'Europe/Paris',
                       ST_GeomFromText(:area, 4326)),
                      ('test:r2', 'NZ', 'Synthetic region', 'Pacific/Auckland',
                       ST_GeomFromText(:area, 4326))""",
            """INSERT INTO cells (id, grid_system, resolution_m, geometry)
               VALUES ('test:c1', 'synthetic-grid-v1', 1000, ST_GeomFromText(:area, 4326))""",
            "INSERT INTO cell_regions VALUES ('test:c1', 'test:r1'), ('test:c1', 'test:r2')",
            "INSERT INTO taxa (id, scientific_name) VALUES ('test:t1', 'Synthetic taxon')",
            """INSERT INTO data_providers VALUES
               ('test:p1', 'Synthetic provider', 'https://example.invalid/provider')""",
            """INSERT INTO source_datasets (id, provider_id, product, source_url)
               VALUES ('test:d1', 'test:p1', 'Synthetic dataset', 'https://example.invalid/data')""",
            """INSERT INTO source_versions
                 (id, dataset_id, version, source_url, checksum_sha256, fetched_at)
               VALUES ('test:v1', 'test:d1', 'fixture-v1', 'https://example.invalid/v1',
                       repeat('a', 64), '2026-01-02T00:00:00Z')""",
            """INSERT INTO prediction_runs (id, model_version)
               VALUES ('test:run1', 'synthetic-not-a-prediction')""",
            "INSERT INTO prediction_run_inputs VALUES ('test:run1', 'test:v1')",
            """INSERT INTO occurrences
                (id, taxon_id, source_version_id, source_record_id, geometry)
               VALUES ('test:o1', 'test:t1', 'test:v1', 'fixture-1',
                       ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326))""",
        ):
            connection.execute(text(statement), {"area": AREA})
        try:
            yield connection
        finally:
            transaction.rollback()


def rejects(connection: Connection, sql: str, **parameters: object) -> None:
    with pytest.raises(DBAPIError), connection.begin_nested():
        connection.execute(text(sql), parameters)


def test_private_defaults_unknowns_and_multicountry_links(populated: Connection) -> None:
    row = populated.execute(text("SELECT * FROM occurrences WHERE id='test:o1'")).mappings().one()
    assert row["visibility"] == "private"
    assert row["verification_status"] == "unverified"
    assert row["location_uncertainty_m"] is None
    assert row["event_start"] is None and row["event_end"] is None
    assert populated.execute(text("SELECT land_fraction FROM cells")).scalar_one() is None
    assert populated.execute(text("SELECT enabled FROM regions LIMIT 1")).scalar_one() is False
    assert populated.execute(text("SELECT count(*) FROM cell_regions")).scalar_one() == 2
    assert populated.execute(text("SELECT status FROM source_versions")).scalar_one() == "pending"


@pytest.mark.parametrize("table", ["regions", "cells", "occurrences"])
@pytest.mark.parametrize("srid", [0, 3857])
def test_wrong_or_unknown_srid_is_rejected(populated: Connection, table: str, srid: int) -> None:
    rejects(populated, f"UPDATE {table} SET geometry=ST_SetSRID(geometry, :srid)", srid=srid)


@pytest.mark.parametrize("table", ["regions", "cells"])
@pytest.mark.parametrize(
    "wkt",
    [
        "MULTIPOLYGON EMPTY",
        "MULTIPOLYGON(((0 0,1 1,0 1,1 0,0 0)))",  # Self-intersection.
        "MULTIPOLYGON(((180 0,181 0,181 1,180 1,180 0)))",
        "POINT(0 0)",
        "MULTIPOLYGON Z(((0 0 1,1 0 1,1 1 1,0 0 1)))",
    ],
)
def test_invalid_area_is_rejected(populated: Connection, table: str, wkt: str) -> None:
    rejects(populated, f"UPDATE {table} SET geometry=ST_GeomFromText(:wkt,4326)", wkt=wkt)


@pytest.mark.parametrize("wkt", ["POINT EMPTY", "POINT(181 0)", "POINT(0 91)", AREA])
def test_invalid_observation_location_is_rejected(populated: Connection, wkt: str) -> None:
    rejects(populated, "UPDATE occurrences SET geometry=ST_GeomFromText(:wkt,4326)", wkt=wkt)


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity"])
def test_nonfinite_or_negative_measurements_are_rejected(populated: Connection, value: str) -> None:
    for table, column in (
        ("cells", "resolution_m"),
        ("occurrences", "location_uncertainty_m"),
        ("source_versions", "effective_resolution_m"),
    ):
        rejects(populated, f"UPDATE {table} SET {column}=CAST(:value AS float8)", value=value)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE cells SET resolution_m=0",
        "UPDATE cells SET land_fraction=1.1",
        "UPDATE cells SET land_fraction='NaN'::float8",
        "UPDATE occurrences SET taxon_id='missing'",
        "UPDATE occurrences SET source_version_id='missing'",
        "UPDATE occurrences SET visibility='open'",
        "UPDATE occurrences SET verification_status='invented'",
        "UPDATE occurrences SET event_start='2026-01-01'",  # Incomplete interval.
        "UPDATE occurrences SET event_start='2026-02-01', event_end='2026-01-01'",
        "UPDATE regions SET country_code='missing'",
        "UPDATE countries SET code='fra'",
        "UPDATE source_versions SET checksum_sha256='not-a-checksum'",
        "UPDATE source_versions SET status='validated'",  # Missing licence/credit.
        "UPDATE source_versions SET metadata='[]'",
        "UPDATE source_versions SET transformations='{}'",
        "UPDATE prediction_runs SET status='succeeded'",  # Missing execution dates.
        "DELETE FROM source_versions",  # Keep observation and run provenance.
        "INSERT INTO prediction_run_inputs VALUES ('test:run1', 'missing')",
        "INSERT INTO cell_regions VALUES ('test:c1', 'test:r1')",
        """INSERT INTO source_versions
           SELECT 'test:duplicate', dataset_id, version, source_url, checksum_sha256,
                  fetched_at, source_published_at, license, license_url, attribution, source_crs,
                  effective_resolution_m, coverage_status, status, metadata, transformations
           FROM source_versions""",
        """INSERT INTO occurrences
           SELECT 'test:duplicate', taxon_id, source_version_id, source_record_id,
                  event_start, event_end, verbatim_event_date, geometry, location_uncertainty_m,
                  verification_status, visibility FROM occurrences""",
    ],
)
def test_integrity_and_provenance_constraints(populated: Connection, sql: str) -> None:
    rejects(populated, sql)


def test_run_lineage_known_dates_and_validated_version(populated: Connection) -> None:
    populated.execute(
        text("""
        UPDATE source_versions SET status='validated', license='CC0-1.0',
            license_url='https://creativecommons.org/publicdomain/zero/1.0/',
            attribution='Synthetic fixture, not real data', coverage_status='partial'
    """)
    )
    populated.execute(
        text("""
        UPDATE occurrences SET event_start='2026-01-01', event_end='2026-01-31',
            verbatim_event_date='2026-01', location_uncertainty_m=1500
    """)
    )
    populated.execute(
        text("""
        UPDATE prediction_runs SET status='succeeded', started_at='2026-01-03T00:00:00Z',
            completed_at='2026-01-03T01:00:00Z', data_cutoff='2026-01-02T00:00:00Z'
    """)
    )
    assert (
        populated.execute(
            text("""
        SELECT v.checksum_sha256 FROM prediction_runs r
        JOIN prediction_run_inputs i ON i.run_id=r.id
        JOIN source_versions v ON v.id=i.source_version_id
        WHERE r.id='test:run1'
    """)
        ).scalar_one()
        == "a" * 64
    )
    results = []
    for sql in (ROOT / "docs/sql/MR-006-examples.sql").read_text(encoding="utf-8").split(";"):
        if sql.strip():
            results.append(populated.execute(text(sql)).mappings().all())
    assert len(results) == 3
    assert {row["country_code"] for row in results[0]} == {"FR", "NZ"}
    assert results[1] == []  # The public example must not return our private fixture.
    assert len(results[2]) == 1 and results[2][0]["checksum_sha256"] == "a" * 64


def test_spatial_and_lookup_indexes_exist(populated: Connection) -> None:
    indexes = dict(
        populated.execute(
            text("""
        SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public'
    """)
        ).all()
    )
    for table in ("regions", "cells", "occurrences"):
        assert "USING gist (geometry)" in indexes[f"ix_{table}_geometry"]
    assert "(taxon_id, event_start)" in indexes["ix_occurrences_taxon_date"]
    assert "(region_id, cell_id)" in indexes["ix_cell_regions_region"]
    spatial_columns = populated.execute(
        text("""
        SELECT f_table_name, type, srid, coord_dimension FROM geometry_columns
        WHERE f_table_name IN ('regions', 'cells', 'occurrences')
    """)
    ).all()
    assert sorted(spatial_columns) == [
        ("cells", "MULTIPOLYGON", 4326, 2),
        ("occurrences", "POINT", 4326, 2),
        ("regions", "MULTIPOLYGON", 4326, 2),
    ]


def test_upgrade_downgrade_replay_preserves_extension_and_unrelated_data(
    database: tuple[Engine, Config],
) -> None:
    engine, config = database
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE mr006_test_sentinel (value text)"))
            connection.execute(text("INSERT INTO mr006_test_sentinel VALUES ('keep')"))
        command.downgrade(config, "0001_postgis")
        assert not database_is_ready(engine)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT to_regclass('occurrences')")).scalar_one() is None
            )
            value = connection.execute(text("SELECT value FROM mr006_test_sentinel")).scalar_one()
            assert value == "keep"
            assert connection.execute(text("SELECT postgis_version()")).scalar_one()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert database_is_ready(engine)
        with engine.connect() as connection:
            for table in ("countries", "regions", "cells", "taxa", "occurrences"):
                assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS mr006_test_sentinel"))
