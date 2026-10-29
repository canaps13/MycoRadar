"""Bounded database probes, independent of HTTP liveness and scientific coverage."""

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from mycoradar.settings import get_settings

ROOT = Path(__file__).resolve().parents[3]


@lru_cache
def required_revision() -> str:
    revision = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    if revision is None:
        raise RuntimeError("No migration head configured")
    return revision


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=3,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
    )


def database_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            version: object = connection.execute(text("SELECT postgis_version()")).scalar_one()
            revision: object = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            return (
                isinstance(version, str)
                and bool(version)
                and isinstance(revision, str)
                and revision == required_revision()
            )
    except SQLAlchemyError:
        # Never include connection details, SQL errors or credentials in the response.
        return False
