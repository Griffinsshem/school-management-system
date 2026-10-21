import hashlib

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select

from app import create_app
from app.api.v1 import auth as auth_module
from app.extensions import db
from app.models import User, UserSession

LOGIN = "/api/v1/auth/login"
PASSWORD = "correct horse battery"


def _login(client, email="ada@example.com", password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def _session_cookie(response) -> str:
    return next(h for h in response.headers.getlist("Set-Cookie") if h.startswith("sms_session="))


def test_successful_login_returns_the_user_and_sets_the_cookie(db_app, make_user):
    make_user()
    response = _login(db_app.test_client())

    assert response.status_code == 200
    assert response.get_json() == {
        "user": {
            "id": response.get_json()["user"]["id"],
            "email": "ada@example.com",
            "full_name": "Ada Example",
            "is_platform_admin": False,
        }
    }
    cookie = _session_cookie(response)
    for flag in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=28800"):
        assert flag in cookie
    assert "Secure" not in cookie  # Plain-http development and tests.


def test_production_cookie_is_secure_with_host_prefix(migrated_database, make_user):
    make_user()
    app = create_app(
        "testing",
        overrides={"AUTH_COOKIE_SECURE": True, "FRONTEND_ORIGIN": "https://app.example.com"},
    )

    response = _login(app.test_client())
    cookies = response.headers.getlist("Set-Cookie")

    assert response.status_code == 200
    assert any(c.startswith("__Host-sms_session=") and "Secure" in c for c in cookies)


def test_only_a_hash_of_the_token_is_stored(db_app, make_user):
    make_user()
    response = _login(db_app.test_client())
    token = _session_cookie(response).split(";")[0].split("=", 1)[1]

    assert token not in response.get_data(as_text=True)
    with db_app.app_context():
        stored = db.session.scalars(select(UserSession.token_hash)).all()
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]


def test_login_ignores_email_letter_case_and_records_the_time(db_app, make_user):
    make_user()
    response = _login(db_app.test_client(), email="  ADA@Example.com ")

    assert response.status_code == 200
    with db_app.app_context():
        assert db.session.scalar(select(User.last_login_at)) is not None


@pytest.mark.parametrize(
    ("email", "password", "active"),
    [
        ("ada@example.com", "wrong password here", True),  # wrong password
        ("nobody@example.com", PASSWORD, True),  # unknown email
        ("ada@example.com", PASSWORD, False),  # deactivated account
    ],
)
def test_every_login_failure_looks_identical(db_app, make_user, email, password, active):
    make_user(is_active=active)
    response = _login(db_app.test_client(), email=email, password=password)
    error = response.get_json()["error"]

    assert response.status_code == 401
    assert (error["code"], error["message"]) == (
        "invalid_credentials",
        "Invalid email or password.",
    )
    assert "Set-Cookie" not in response.headers


def test_unknown_email_still_runs_a_full_password_check(db_app, monkeypatch):
    calls = []
    real_verify = auth_module.verify_password

    def counting_verify(password_hash, password):
        calls.append(password_hash)
        return real_verify(password_hash, password)

    monkeypatch.setattr(auth_module, "verify_password", counting_verify)
    _login(db_app.test_client(), email="nobody@example.com")

    assert len(calls) == 1
    assert calls[0].startswith("$argon2id$v=19$m=19456,t=2,p=1$")


def test_old_password_hash_is_upgraded_at_login(db_app, make_user):
    user_id = make_user()
    with db_app.app_context():
        user = db.session.get(User, user_id)
        user.password_hash = PasswordHasher(time_cost=1, memory_cost=8192).hash(PASSWORD)
        db.session.commit()

    assert _login(db_app.test_client()).status_code == 200
    with db_app.app_context():
        upgraded = db.session.get(User, user_id).password_hash
    assert upgraded.startswith("$argon2id$v=19$m=19456,t=2,p=1$")


@pytest.mark.parametrize(
    "body",
    [
        {"email": "ada@example.com"},
        {"password": PASSWORD},
        {"email": "ada@example.com", "password": PASSWORD, "is_platform_admin": True},
        {"email": "ada@example.com", "password": "x" * 129},
        {"email": 123, "password": PASSWORD},
    ],
)
def test_invalid_login_bodies_are_rejected(db_app, body):
    response = db_app.test_client().post(LOGIN, json=body)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "invalid_request"
    assert response.get_json()["error"]["details"]


def test_validation_errors_never_echo_the_password(db_app):
    secret = "my-secret-password-value"
    response = db_app.test_client().post(
        LOGIN, json={"email": "ada@example.com", "password": secret, "unexpected": secret}
    )

    assert response.status_code == 422
    assert secret not in response.get_data(as_text=True)


def test_a_json_array_is_rejected(db_app):
    response = db_app.test_client().post(LOGIN, json=["ada@example.com", PASSWORD])

    assert response.status_code == 422


def test_failed_login_logs_contain_no_email_or_password(migrated_database, make_user, capsys):
    make_user()
    app = create_app("testing")

    _login(app.test_client(), password="wrong password here")
    output = capsys.readouterr().out

    assert "Login failed" in output
    assert "ada@example.com" not in output
    assert "wrong password here" not in output
