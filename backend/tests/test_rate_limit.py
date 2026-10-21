from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import create_app
from app.api.v1 import auth as auth_module
from app.extensions import db
from app.models import LoginAttempt

LOGIN = "/api/v1/auth/login"
PASSWORD = "correct horse battery"
WRONG = "wrong password here"


def _login(client, email="ada@example.com", password=WRONG, **kwargs):
    return client.post(LOGIN, json={"email": email, "password": password}, **kwargs)


def _attempt_count(app, key_type) -> int:
    with app.app_context():
        query = select(func.count()).select_from(LoginAttempt)
        return db.session.scalar(query.where(LoginAttempt.key_type == key_type))


def test_account_is_limited_after_10_failures(db_app, make_user):
    make_user()
    client = db_app.test_client()
    for _ in range(10):
        assert _login(client).status_code == 401

    blocked = _login(client, password=PASSWORD)  # Even the right password is refused.

    assert blocked.status_code == 429
    assert blocked.get_json()["error"]["code"] == "too_many_attempts"
    assert 1 <= int(blocked.headers["Retry-After"]) <= 15 * 60


def test_limit_lifts_once_failures_leave_the_window(db_app, make_user, monkeypatch):
    make_user()
    client = db_app.test_client()
    for _ in range(10):
        _login(client)
    assert _login(client).status_code == 429

    later = auth_module.utcnow() + timedelta(minutes=16)
    monkeypatch.setattr(auth_module, "utcnow", lambda: later)

    assert _login(client, password=PASSWORD).status_code == 200


def test_other_accounts_are_not_affected(db_app, make_user):
    make_user()
    make_user(email="bea@example.com")
    client = db_app.test_client()
    for _ in range(10):
        _login(client)

    assert _login(client, email="bea@example.com", password=PASSWORD).status_code == 200


def test_successful_login_clears_the_account_failures(db_app, make_user):
    make_user()
    client = db_app.test_client()
    for _ in range(3):
        _login(client)

    assert _login(client, password=PASSWORD).status_code == 200
    assert _attempt_count(db_app, "account") == 0
    assert _attempt_count(db_app, "ip") == 3  # IP failures still count.


def test_ip_is_limited_across_accounts(migrated_database, db_app):
    app = create_app("testing", overrides={"LOGIN_MAX_FAILURES_PER_IP": 3})
    client = app.test_client()
    for number in range(3):
        assert _login(client, email=f"user{number}@example.com").status_code == 401

    assert _login(client, email="fresh@example.com").status_code == 429


def test_neither_email_nor_ip_is_stored(db_app):
    _login(db_app.test_client(), email="secret.person@example.com")

    with db_app.app_context():
        stored = db.session.execute(select(LoginAttempt.key_type, LoginAttempt.key_hash)).all()
    assert {key_type for key_type, _ in stored} == {"account", "ip"}
    for _key_type, key_hash in stored:
        assert len(key_hash) == 64
        assert "secret" not in key_hash and "127.0.0.1" not in key_hash


@pytest.mark.parametrize(("proxy_count", "second_ip_status"), [(1, 401), (0, 429)])
def test_forwarded_ip_is_trusted_only_behind_a_configured_proxy(
    migrated_database, db_app, proxy_count, second_ip_status
):
    app = create_app(
        "testing",
        overrides={"LOGIN_MAX_FAILURES_PER_IP": 3, "TRUSTED_PROXY_COUNT": proxy_count},
    )
    client = app.test_client()
    for number in range(3):
        _login(client, email=f"user{number}@example.com", headers={"X-Forwarded-For": "10.0.0.1"})

    response = _login(client, email="fresh@example.com", headers={"X-Forwarded-For": "10.0.0.2"})

    # With a trusted proxy, 10.0.0.2 is a different client. Without one, the
    # header is ignored, so nobody can dodge the limit by faking it.
    assert response.status_code == second_ip_status
