"""Shared opt-in guard: migrations are tested only on explicitly isolated databases."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from mycoradar.database import ROOT
from mycoradar.settings import get_settings
from sqlalchemy import Engine, create_engine


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
    try:
        yield engine, config
    finally:
        engine.dispose()
