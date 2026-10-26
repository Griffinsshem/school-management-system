"""Only our own frontend may call the API (app.frontend_proxy)."""

import pytest

from app import create_app
from app.errors import ApiError
from app.frontend_proxy import CLIENT_IP_HEADER, EXEMPT_PATHS, PROXY_SECRET_HEADER, client_ip

SECRET = "s" * 40
ME = "/api/v1/auth/me"
LOGIN = "/api/v1/auth/login"


def proxied_app(**overrides):
    return create_app("testing", overrides={"PROXY_SHARED_SECRET": SECRET, **overrides})


def via_proxy(ip="203.0.113.9", secret=SECRET):
    return {PROXY_SECRET_HEADER: secret, CLIENT_IP_HEADER: ip}


def test_without_a_configured_secret_nothing_changes(client):
    response = client.get(ME)

    assert response.status_code == 401


@pytest.mark.parametrize("headers", [{}, {PROXY_SECRET_HEADER: "wrong"}, {PROXY_SECRET_HEADER: ""}])
def test_requests_without_the_right_secret_are_refused(headers):
    client = proxied_app().test_client()

    for response in (
        client.get(ME, headers=headers),
        client.post(LOGIN, json={"email": "a@example.com", "password": "x"}, headers=headers),
        client.get("/api/v1/no-such-endpoint", headers=headers),
    ):
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "forbidden"


def test_requests_with_the_right_secret_are_handled_normally():
    response = proxied_app().test_client().get(ME, headers=via_proxy())

    assert response.status_code == 401  # Reached the endpoint: not logged in.


def test_health_checks_need_no_secret():
    assert EXEMPT_PATHS == {"/api/v1/health", "/api/v1/health/ready"}
    response = proxied_app().test_client().get("/api/v1/health")

    assert response.status_code == 200


def address_seen(app, headers):
    with app.test_request_context(ME, headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.5"}):
        app.preprocess_request()
        return client_ip()


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        ("203.0.113.9", "203.0.113.9"),
        (" 2001:DB8::1 ", "2001:db8::1"),
        ("203.0.113.9, 198.51.100.2", "10.0.0.5"),
        ("not-an-ip", "10.0.0.5"),
        ("", "10.0.0.5"),
    ],
)
def test_client_ip_comes_from_the_frontend_only_when_well_formed(sent, expected):
    assert address_seen(proxied_app(), via_proxy(ip=sent)) == expected


def test_client_ip_header_is_ignored_without_a_configured_secret():
    app = create_app("testing")

    assert address_seen(app, {CLIENT_IP_HEADER: "203.0.113.9"}) == "10.0.0.5"


def test_client_ip_header_with_a_wrong_secret_is_refused():
    with pytest.raises(ApiError):
        address_seen(proxied_app(), via_proxy(secret="wrong"))


def test_each_visitor_has_their_own_login_limit(migrated_database, db_app):
    app = proxied_app(LOGIN_MAX_FAILURES_PER_IP=3)
    client = app.test_client()

    def fail(email, ip):
        body = {"email": email, "password": "wrong password here"}
        return client.post(LOGIN, json=body, headers=via_proxy(ip=ip))

    for number in range(3):
        assert fail(f"user{number}@example.com", "203.0.113.1").status_code == 401

    assert fail("fresh@example.com", "203.0.113.1").status_code == 429
    assert fail("fresh@example.com", "203.0.113.2").status_code == 401
