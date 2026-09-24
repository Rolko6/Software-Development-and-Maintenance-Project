def test_health_returns_200(client):
    """GET /health responds with HTTP 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_expected_body(client):
    """GET /health responds with exactly {"status": "healthy"}."""
    response = client.get("/health")
    assert response.json() == {"status": "healthy"}
