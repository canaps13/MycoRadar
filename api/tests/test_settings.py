import pytest
from mycoradar.settings import Settings
from pydantic import ValidationError


def test_password_is_escaped_by_url_builder_and_hidden_from_repr() -> None:
    settings = Settings(_env_file=None, pg_password="fixture@:/?%value")
    assert settings.database_url.password == "fixture@:/?%value"
    assert "fixture@:/?%value" not in str(settings.database_url)
    assert "fixture@:/?%value" not in repr(settings)


def test_port_is_validated() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pg_port=70000)


def test_environment_can_override_database_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGHOST", "configured-host")
    assert Settings(_env_file=None).pg_host == "configured-host"
