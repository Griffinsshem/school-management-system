import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from flask_migrate import upgrade
from sqlalchemy import text

from app import create_app
from app.auth.passwords import hash_password
from app.extensions import db
from app.models import Membership, School, User

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TEST_ENV_KEYS = ("TEST_DATABASE_URL", "TEST_MIGRATION_DATABASE_URL")
# Emptied after every test that uses the `db_app` fixture, children first.
TABLES_TO_CLEAN = ("login_attempts", "sessions", "memberships", "schools", "users")


def pytest_configure(config):
    """Use test connection strings from the environment, or else from backend/.env.

    Only the TEST_* keys are read from .env. Development secrets and the
    development database URL are never loaded into the test process.
    """
    if not ENV_FILE.exists():
        return
    values = dotenv_values(ENV_FILE)
    for key in TEST_ENV_KEYS:
        if key not in os.environ and values.get(key):
            os.environ[key] = values[key]


@pytest.fixture
def app():
    app = create_app("testing")
    yield app
    # Close this app's pooled database connections.
    with app.app_context():
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def migrated_database():
    """Bring the test database to the latest migration once per test run."""
    app = create_app("testing")
    with app.app_context():
        upgrade()
        db.engine.dispose()


@pytest.fixture
def db_app(migrated_database, app):
    """An app whose test database has every table, emptied again after the test."""
    yield app
    with app.app_context():
        db.session.remove()
        for table in TABLES_TO_CLEAN:
            db.session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 (fixed names)
        db.session.commit()


@pytest.fixture
def make_user(db_app):
    """Create a user in the test database and return its ID."""

    def _make(email="ada@example.com", password="correct horse battery", **fields):
        with db_app.app_context():
            user = User(
                email=email,
                full_name="Ada Example",
                password_hash=hash_password(password),
                **fields,
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    return _make


@pytest.fixture
def make_school(db_app):
    """Create a school in the test database and return its ID."""

    def _make(code="greenfield-academy", name="Greenfield Academy", county_code=47, **fields):
        with db_app.app_context():
            school = School(code=code, name=name, county_code=county_code, **fields)
            db.session.add(school)
            db.session.commit()
            return school.id

    return _make


@pytest.fixture
def add_member(db_app):
    """Give a user a role in a school and return the membership ID."""

    def _add(user_id, school_id, role="teacher", **fields):
        with db_app.app_context():
            membership = Membership(user_id=user_id, school_id=school_id, role=role, **fields)
            db.session.add(membership)
            db.session.commit()
            return membership.id

    return _add
