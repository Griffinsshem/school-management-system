import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import create_app
from app.extensions import db

INSUFFICIENT_PRIVILEGE = "42501"
UNREACHABLE_URL = "postgresql+psycopg://nobody:wrong-password@127.0.0.1:1/unreachable_test"


def test_ready_returns_ok_when_database_is_reachable(client):
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_ready_returns_503_without_details_when_database_is_unreachable():
    app = create_app("testing", overrides={"SQLALCHEMY_DATABASE_URI": UNREACHABLE_URL})

    response = app.test_client().get("/api/v1/health/ready")
    body = response.get_data(as_text=True)

    assert response.status_code == 503
    assert response.get_json() == {"status": "unavailable"}
    for detail in ("127.0.0.1", "nobody", "unreachable_test", "psycopg", "Traceback"):
        assert detail not in body


def test_liveness_does_not_touch_the_database():
    app = create_app("testing", overrides={"SQLALCHEMY_DATABASE_URI": UNREACHABLE_URL})

    response = app.test_client().get("/api/v1/health")

    assert response.status_code == 200


def test_runtime_user_has_no_elevated_attributes(app):
    with app.app_context():
        row = db.session.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()

    assert tuple(row) == (False, False, False, False)


def test_runtime_user_cannot_change_the_schema(app):
    with app.app_context(), db.engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text("CREATE TABLE privilege_probe (id integer)"))

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
