from fastapi.testclient import TestClient

from resiliant_z.api import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["project"] == "RESILIANT-Z"
