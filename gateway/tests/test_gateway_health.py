"""Tests for the GET /health endpoint."""


def test_health_returns_200_and_healthy_status(client):
    """GET /health returns 200 with exactly {"status": "healthy"}."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
