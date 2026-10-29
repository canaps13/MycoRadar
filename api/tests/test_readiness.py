from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from mycoradar.database import get_engine, required_revision
from mycoradar.main import app
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError


@pytest.fixture
def database() -> Iterator[MagicMock]:
    engine = MagicMock(spec=Engine)
    app.dependency_overrides[get_engine] = lambda: engine
    yield engine
    app.dependency_overrides.pop(get_engine, None)


def test_ready_requires_postgis_and_current_revision(database: MagicMock) -> None:
    connection = database.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.side_effect = [
        "3.6 test fixture",
        required_revision(),
    ]
    response = TestClient(app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ready"}


def test_missing_database_does_not_affect_liveness_or_leak_credentials(database: MagicMock) -> None:
    database.connect.side_effect = OperationalError(
        "secret-host:password", {}, Exception("private")
    )
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert "private" not in response.text
    assert "password" not in response.text


def test_outdated_revision_is_not_ready(database: MagicMock) -> None:
    connection = database.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one.side_effect = ["3.6 test fixture", "outdated"]
    assert TestClient(app).get("/ready").status_code == 503


def test_missing_extension_or_migration_is_not_ready(database: MagicMock) -> None:
    connection = database.connect.return_value.__enter__.return_value
    connection.execute.side_effect = OperationalError("missing function or table", {}, Exception())
    assert TestClient(app).get("/ready").status_code == 503


def test_readiness_documents_unavailability() -> None:
    document = TestClient(app).get("/openapi.json").json()
    assert "503" in document["paths"]["/ready"]["get"]["responses"]
