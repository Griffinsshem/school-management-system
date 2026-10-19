def test_health_returns_ok(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.is_json
    assert response.get_json() == {"status": "ok"}


def test_health_rejects_other_methods(client):
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]
    assert response.get_json()["error"]["code"] == "method_not_allowed"
