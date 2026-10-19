from flask import request

from app import create_app


def test_unknown_route_returns_json_404(client):
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["error"]["code"] == "not_found"


def test_unexpected_error_returns_generic_500_without_details():
    app = create_app("testing")

    @app.get("/boom")
    def boom():
        raise ValueError("secret internal detail")

    response = app.test_client().get("/boom")
    body = response.get_data(as_text=True)

    assert response.status_code == 500
    assert response.get_json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected error occurred.",
        }
    }
    assert "secret internal detail" not in body
    assert "Traceback" not in body


def test_oversized_request_body_is_rejected():
    # The size limit applies when an endpoint reads the body, so use a
    # test-only endpoint that does.
    app = create_app("testing")

    @app.post("/echo-size")
    def echo_size():
        return {"size": len(request.get_data())}

    client = app.test_client()
    small = client.post("/echo-size", data=b"x" * 10)
    too_big = client.post("/echo-size", data=b"x" * (1024 * 1024 + 1))

    assert small.status_code == 200
    assert too_big.status_code == 413
    assert too_big.get_json()["error"]["code"] == "request_entity_too_large"
