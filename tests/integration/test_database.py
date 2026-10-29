"""Opt-in tests on a dedicated, disposable PostGIS database; never fake its presence."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from mycoradar.database import ROOT, database_is_ready, required_revision
from mycoradar.settings import get_settings
from sqlalchemy import Engine, create_engine, text

pytestmark = pytest.mark.integration


@pytest.fixture
def database() -> Iterator[tuple[Engine, Config]]:
    if os.environ.get("MYCORADAR_TEST_DATABASE") != "1":
        pytest.skip("Requires an isolated PostGIS database and MYCORADAR_TEST_DATABASE=1")
    settings = get_settings()
    if not settings.pg_database.startswith("mycoradar_test"):
        pytest.fail("Integration tests require a dedicated database named mycoradar_test...")
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
    yield engine, config
    engine.dispose()


def test_real_postgis_and_schema_are_ready(database: tuple[Engine, Config]) -> None:
    engine, _ = database
    assert database_is_ready(engine)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT ST_SRID(ST_SetSRID(ST_MakePoint(1, 2), 4326))")
            ).scalar_one()
            == 4326
        )


def test_migration_can_be_replayed(database: tuple[Engine, Config]) -> None:
    engine, config = database
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            required_revision()
        )


def test_revision_rollback_preserves_postgis(database: tuple[Engine, Config]) -> None:
    engine, config = database
    try:
        command.downgrade(config, "base")
        assert not database_is_ready(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT postgis_version()")).scalar_one()
    finally:
        command.upgrade(config, "head")
    assert database_is_ready(engine)
