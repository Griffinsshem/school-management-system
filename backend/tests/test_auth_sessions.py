from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.auth import sessions as sessions_module
from app.extensions import db
from app.models import User, UserSession

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
PASSWORD = "correct horse battery"


@pytest.fixture
def logged_in(db_app, make_user):
    """A test client holding a fresh session cookie, plus that cookie's token."""
    make_user()
    client = db_app.test_client()
    response = client.post(LOGIN, json={"email": "ada@example.com", "password": PASSWORD})
    assert response.status_code == 200
    return client, client.get_cookie("sms_session").value


@pytest.fixture
def clock(monkeypatch):
    """Move the session clock forward without waiting."""
    start = sessions_module.utcnow()
    state = {"offset": timedelta(0)}
    monkeypatch.setattr(sessions_module, "utcnow", lambda: start + state["offset"])

    def advance_to(offset: timedelta) -> None:
        state["offset"] = offset

    return advance_to


def _session_count(app) -> int:
    with app.app_context():
        return db.session.scalar(select(func.count()).select_from(UserSession))


def test_me_requires_a_session(db_app):
    response = db_app.test_client().get(ME)

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_me_returns_the_logged_in_user(logged_in):
    client, _token = logged_in

    response = client.get(ME)

    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == "ada@example.com"


def test_logout_ends_the_session_on_the_server(db_app, logged_in):
    client, token = logged_in

    response = client.post(LOGOUT)

    assert response.status_code == 204
    assert any("sms_session=;" in c for c in response.headers.getlist("Set-Cookie"))
    assert _session_count(db_app) == 0
    # Replaying the old cookie no longer works.
    client.set_cookie("sms_session", token)
    assert client.get(ME).status_code == 401


def test_logout_without_a_session_is_harmless(db_app):
    assert db_app.test_client().post(LOGOUT).status_code == 204


def test_every_login_issues_a_new_token(db_app, make_user):
    make_user()
    client = db_app.test_client()
    credentials = {"email": "ada@example.com", "password": PASSWORD}

    client.post(LOGIN, json=credentials)
    first = client.get_cookie("sms_session").value
    client.post(LOGIN, json=credentials)
    second = client.get_cookie("sms_session").value

    assert first != second
    assert _session_count(db_app) == 2


@pytest.mark.parametrize("token", ["not-a-real-token", "x" * 500])
def test_unknown_or_oversized_tokens_are_refused(db_app, token):
    client = db_app.test_client()
    client.set_cookie("sms_session", token)

    assert client.get(ME).status_code == 401


def test_idle_session_expires_after_30_minutes(db_app, logged_in, clock):
    client, _token = logged_in

    clock(timedelta(minutes=29))
    assert client.get(ME).status_code == 200  # Activity resets the idle timer...
    clock(timedelta(minutes=29 + 31))
    assert client.get(ME).status_code == 401  # ...but 31 idle minutes end it.
    assert _session_count(db_app) == 0


def test_activity_keeps_a_session_alive_until_the_absolute_limit(logged_in, clock):
    client, _token = logged_in

    for minutes in range(20, 8 * 60, 20):  # A request every 20 minutes all day.
        clock(timedelta(minutes=minutes))
        assert client.get(ME).status_code == 200

    clock(timedelta(hours=8))
    assert client.get(ME).status_code == 401


def test_last_seen_is_written_at_most_once_a_minute(db_app, logged_in, clock):
    client, _token = logged_in
    with db_app.app_context():
        first_seen = db.session.scalar(select(UserSession.last_seen_at))

    clock(timedelta(seconds=30))
    client.get(ME)
    with db_app.app_context():
        assert db.session.scalar(select(UserSession.last_seen_at)) == first_seen

    clock(timedelta(seconds=90))
    client.get(ME)
    with db_app.app_context():
        assert db.session.scalar(select(UserSession.last_seen_at)) > first_seen


def test_deactivated_user_is_logged_out_on_the_next_request(db_app, logged_in):
    client, _token = logged_in
    with db_app.app_context():
        db.session.scalar(select(User)).is_active = False
        db.session.commit()

    assert client.get(ME).status_code == 401
    assert _session_count(db_app) == 0


def test_prune_sessions_deletes_only_expired_sessions(db_app, logged_in, make_user):
    _client, _token = logged_in
    with db_app.app_context():
        expired = db.session.scalar(select(UserSession))
        expired.expires_at = expired.expires_at - timedelta(hours=9)
        db.session.commit()
    make_user(email="bea@example.com")
    db_app.test_client().post(LOGIN, json={"email": "bea@example.com", "password": PASSWORD})

    result = db_app.test_cli_runner().invoke(args=["prune-sessions"])

    assert result.exit_code == 0, result.output
    assert "Deleted 1 expired sessions" in result.output
    assert _session_count(db_app) == 1
