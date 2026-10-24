"""TEMPORARY (B10): the client-IP diagnostic endpoint. Removed with it."""

import pytest

from app import create_app

URL = "/api/v1/diagnostics/client-ip"


def make_client(**overrides):
    return create_app("testing", overrides=overrides).test_client()


def test_off_by_default(client):
    response = client.get(URL)

    assert response.status_code == 404


def test_off_unless_the_setting_is_exactly_1(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/unused")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example.com")
    for value, expected in (("true", 404), ("0", 404), ("1", 200)):
        monkeypatch.setenv("CLIENT_IP_DIAGNOSTICS", value)
        response = create_app().test_client().get(URL)
        assert response.status_code == expected, value


def test_shows_own_addresses_without_trusting_headers():
    client = make_client(CLIENT_IP_DIAGNOSTICS=True)

    response = client.get(
        URL,
        headers={"X-Forwarded-For": "203.0.113.7, 198.51.100.2"},
        environ_base={"REMOTE_ADDR": "10.0.0.5"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert body["trusted_proxy_count"] == 0
    # Not trusted: the rate limiter uses the socket address, not the header.
    assert body["rate_limit_ip"] == "10.0.0.5"
    assert body["socket_peer"] == "10.0.0.5"
    assert body["headers"]["X-Forwarded-For"] == "203.0.113.7, 198.51.100.2"
    assert body["headers"]["CF-Connecting-IP"] is None


@pytest.mark.parametrize(("count", "expected"), [(1, "198.51.100.2"), (2, "203.0.113.7")])
def test_shows_what_the_rate_limiter_would_use_behind_proxies(count, expected):
    client = make_client(CLIENT_IP_DIAGNOSTICS=True, TRUSTED_PROXY_COUNT=count)

    body = client.get(
        URL,
        headers={"X-Forwarded-For": "203.0.113.7, 198.51.100.2"},
        environ_base={"REMOTE_ADDR": "10.0.0.5"},
    ).get_json()

    assert body["rate_limit_ip"] == expected
    assert body["socket_peer"] == "10.0.0.5"
