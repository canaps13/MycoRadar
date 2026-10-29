from fastapi.testclient import TestClient
from mycoradar.main import app

client = TestClient(app)


def test_health_is_available_without_database_or_provider() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "service": "mycoradar-api"}


def test_health_contract_is_documented_in_openapi() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    operation = document["paths"]["/health"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"] == "#/components/schemas/HealthResponse"


def test_predictions_are_not_fabricated_by_bootstrap() -> None:
    assert client.get("/v1/predictions").status_code == 404
