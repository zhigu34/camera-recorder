from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    # Context-manager mode executes FastAPI lifespan, including Alembic
    # migration, SQLite setup, and background worker startup/shutdown.
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
