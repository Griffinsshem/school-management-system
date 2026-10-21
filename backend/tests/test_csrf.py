import pytest

LOGIN = "/api/v1/auth/login"
CREDENTIALS = {"email": "nobody@example.com", "password": "correct horse battery"}


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:3001"])
def test_state_changing_request_from_another_origin_is_refused(db_app, origin):
    response = db_app.test_client().post(LOGIN, json=CREDENTIALS, headers={"Origin": origin})

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden_origin"


def test_request_from_the_frontend_origin_is_allowed(db_app):
    response = db_app.test_client().post(
        LOGIN, json=CREDENTIALS, headers={"Origin": "http://localhost:3000"}
    )

    assert response.status_code == 401  # Reached the login check: unknown user.


def test_request_without_an_origin_header_is_allowed(db_app):
    # Non-browser clients (curl, tests) send no Origin; CSRF needs a browser.
    assert db_app.test_client().post(LOGIN, json=CREDENTIALS).status_code == 401


@pytest.mark.parametrize(
    "content_type", ["application/x-www-form-urlencoded", "multipart/form-data", "text/plain"]
)
def test_non_json_bodies_are_refused(db_app, content_type):
    response = db_app.test_client().post(
        LOGIN, data="email=a%40b.com&password=x", content_type=content_type
    )

    assert response.status_code == 415
    assert response.get_json()["error"]["code"] == "unsupported_media_type"


def test_safe_methods_are_not_blocked_by_origin(db_app):
    response = db_app.test_client().get(
        "/api/v1/auth/me", headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 401  # Not 403: GET requests change nothing.


def test_logout_needs_no_body(db_app):
    assert db_app.test_client().post("/api/v1/auth/logout").status_code == 204
