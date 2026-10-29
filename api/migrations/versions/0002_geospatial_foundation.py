"""Create the geographic and provenance foundation; do not seed scientific data."""

from alembic import op

revision = "0002_geospatial_foundation"
down_revision = "0001_postgis"
branch_labels = None
depends_on = None

TABLES = (
    "countries",
    "regions",
    "cells",
    "cell_regions",
    "taxa",
    "data_providers",
    "source_datasets",
    "source_versions",
    "prediction_runs",
    "prediction_run_inputs",
    "occurrences",
)


def upgrade() -> None:
    statements = (
        """
        CREATE TABLE countries (
            code text PRIMARY KEY CHECK (code ~ '^[A-Z]{2}$'),
            name text NOT NULL CHECK (btrim(name) <> '')
        )
        """,
        """
        CREATE TABLE regions (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            country_code text NOT NULL REFERENCES countries(code),
            name text NOT NULL CHECK (btrim(name) <> ''),
            timezone text NOT NULL CHECK (btrim(timezone) <> ''),
            enabled boolean NOT NULL DEFAULT false,
            geometry geometry NOT NULL
        )
        """,
        """
        CREATE TABLE cells (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            grid_system text NOT NULL CHECK (btrim(grid_system) <> ''),
            resolution_m double precision NOT NULL
                CHECK (resolution_m > 0 AND resolution_m < 'Infinity'::float8),
            land_fraction double precision CHECK (land_fraction BETWEEN 0 AND 1),
            geometry geometry NOT NULL
        )
        """,
        """
        CREATE TABLE cell_regions (
            cell_id text NOT NULL REFERENCES cells(id),
            region_id text NOT NULL REFERENCES regions(id),
            PRIMARY KEY (cell_id, region_id)
        )
        """,
        """
        CREATE TABLE taxa (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            scientific_name text NOT NULL CHECK (btrim(scientific_name) <> ''),
            authority text,
            gbif_taxon_key bigint UNIQUE CHECK (gbif_taxon_key > 0),
            status text NOT NULL DEFAULT 'unresolved'
                CHECK (status IN ('accepted', 'synonym', 'unresolved'))
        )
        """,
        """
        CREATE TABLE data_providers (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            name text NOT NULL CHECK (btrim(name) <> ''),
            homepage_url text NOT NULL CHECK (btrim(homepage_url) <> '')
        )
        """,
        """
        CREATE TABLE source_datasets (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            provider_id text NOT NULL REFERENCES data_providers(id),
            product text NOT NULL CHECK (btrim(product) <> ''),
            source_url text NOT NULL CHECK (btrim(source_url) <> ''),
            ingestion_policy jsonb NOT NULL DEFAULT '{}'
                CHECK (jsonb_typeof(ingestion_policy) = 'object')
        )
        """,
        """
        CREATE TABLE source_versions (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            dataset_id text NOT NULL REFERENCES source_datasets(id),
            version text NOT NULL CHECK (btrim(version) <> ''),
            source_url text NOT NULL CHECK (btrim(source_url) <> ''),
            checksum_sha256 text NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
            fetched_at timestamptz NOT NULL,
            source_published_at timestamptz,
            license text CHECK (btrim(license) <> ''),
            license_url text CHECK (btrim(license_url) <> ''),
            attribution text CHECK (btrim(attribution) <> ''),
            source_crs text CHECK (btrim(source_crs) <> ''),
            effective_resolution_m double precision
                CHECK (effective_resolution_m > 0
                       AND effective_resolution_m < 'Infinity'::float8),
            coverage_status text NOT NULL DEFAULT 'unavailable'
                CHECK (coverage_status IN ('complete', 'partial', 'unavailable')),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'validated', 'rejected')),
            metadata jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(metadata) = 'object'),
            transformations jsonb NOT NULL DEFAULT '[]'
                CHECK (jsonb_typeof(transformations) = 'array'),
            UNIQUE (dataset_id, version, checksum_sha256),
            CHECK (status <> 'validated' OR
                   (license IS NOT NULL AND license_url IS NOT NULL AND attribution IS NOT NULL))
        )
        """,
        """
        CREATE TABLE prediction_runs (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            model_version text NOT NULL CHECK (btrim(model_version) <> ''),
            status text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
            started_at timestamptz,
            completed_at timestamptz,
            data_cutoff timestamptz,
            CHECK (
                (status = 'queued' AND started_at IS NULL AND completed_at IS NULL) OR
                (status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL) OR
                (status IN ('succeeded', 'failed') AND started_at IS NOT NULL
                 AND completed_at IS NOT NULL AND completed_at >= started_at)
            )
        )
        """,
        """
        CREATE TABLE prediction_run_inputs (
            run_id text NOT NULL REFERENCES prediction_runs(id),
            source_version_id text NOT NULL REFERENCES source_versions(id),
            PRIMARY KEY (run_id, source_version_id)
        )
        """,
        """
        CREATE TABLE occurrences (
            id text PRIMARY KEY CHECK (btrim(id) <> ''),
            taxon_id text NOT NULL REFERENCES taxa(id),
            source_version_id text NOT NULL REFERENCES source_versions(id),
            source_record_id text NOT NULL CHECK (btrim(source_record_id) <> ''),
            event_start date,
            event_end date,
            verbatim_event_date text,
            geometry geometry NOT NULL,
            coord_uncertainty_m double precision
                CHECK (coord_uncertainty_m >= 0
                       AND coord_uncertainty_m < 'Infinity'::float8),
            verification_status text NOT NULL DEFAULT 'unverified'
                CHECK (verification_status IN ('unverified', 'verified', 'rejected')),
            visibility text NOT NULL DEFAULT 'private'
                CHECK (visibility IN ('private', 'restricted', 'public')),
            UNIQUE (source_version_id, source_record_id),
            CHECK ((event_start IS NULL AND event_end IS NULL) OR
                   (event_start IS NOT NULL AND event_end IS NOT NULL AND event_end >= event_start))
        )
        """,
    )
    for statement in statements:
        op.execute(statement)
    for table, geometry_type in (
        ("regions", "MULTIPOLYGON"),
        ("cells", "MULTIPOLYGON"),
        ("occurrences", "POINT"),
    ):
        # A typmod can silently assign 4326 to SRID 0. Explicit constraints reject unknown CRS.
        for name, condition in (
            ("srid", "ST_SRID(geometry) = 4326"),
            ("dims", "ST_NDims(geometry) = 2"),
            ("geotype", f"GeometryType(geometry) = '{geometry_type}'"),
        ):
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT enforce_{name}_geometry CHECK ({condition})"
            )
        op.execute(f"""
            ALTER TABLE {table} ADD CONSTRAINT ck_{table}_geometry CHECK (
                NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry)
                AND ST_XMin(geometry) >= -180 AND ST_XMax(geometry) <= 180
                AND ST_YMin(geometry) >= -90 AND ST_YMax(geometry) <= 90
            )
        """)
        op.execute(f"CREATE INDEX ix_{table}_geometry ON {table} USING gist (geometry)")
    for name, table, columns in (
        ("regions_country", "regions", "country_code"),
        ("cell_regions_region", "cell_regions", "region_id, cell_id"),
        ("datasets_provider", "source_datasets", "provider_id"),
        ("run_inputs_version", "prediction_run_inputs", "source_version_id, run_id"),
        ("occurrences_taxon_date", "occurrences", "taxon_id, event_start"),
    ):
        op.execute(f"CREATE INDEX ix_{name} ON {table} ({columns})")


def downgrade() -> None:
    """Destructive for these business tables; only run after explicit approval outside tests."""
    for table in reversed(TABLES):
        op.drop_table(table)
