"""Opt-in tests on a dedicated, disposable PostGIS database; never fake its presence."""

import pytest
from alembic import command
from alembic.config import Config
from mycoradar.database import database_is_ready, required_revision
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration


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
