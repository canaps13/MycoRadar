"""Server-only database configuration; no connection is opened by importing it."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    pg_host: str = Field(default="127.0.0.1", validation_alias="PGHOST")
    pg_port: int = Field(default=55432, ge=1, le=65535, validation_alias="PGPORT")
    pg_database: str = Field(default="mycoradar", validation_alias="PGDATABASE")
    pg_user: str = Field(default="mycoradar", validation_alias="PGUSER")
    pg_password: SecretStr = Field(default=SecretStr(""), validation_alias="PGPASSWORD")
    catalog_path: Path | None = Field(default=None, validation_alias="MYCORADAR_CATALOG_PATH")
    catalog_sha256: str | None = Field(default=None, validation_alias="MYCORADAR_CATALOG_SHA256")

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.pg_user,
            password=self.pg_password.get_secret_value(),
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_database,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
