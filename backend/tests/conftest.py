import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values
from flask_migrate import upgrade
from sqlalchemy import create_engine, text

from app import create_app
from app.auth.passwords import hash_password
from app.extensions import db
from app.models import Invitation, Membership, School, Student, User
from app.school_context import set_database_school

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TEST_ENV_KEYS = ("TEST_DATABASE_URL", "TEST_MIGRATION_DATABASE_URL")
# Emptied after every test that uses the `db_app` fixture, children first.
# The schema owner does the emptying: the API's user cannot delete audit
# events, and Row-Level Security hides other schools' students from it.
TABLES_TO_CLEAN = (
    "audit_events",
    "login_attempts",
    "sessions",
    "invitations",
    "attendance_marks",
    "attendance_registers",
    "student_guardians",
    "guardians",
    "subject_teachers",
    "class_subjects",
    "subjects",
    "enrolments",
    "class_teachers",
    "classes",
    "terms",
    "academic_years",
    "students",
    "memberships",
    "schools",
    "users",
)


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


@pytest.fixture(scope="session")
def schema_owner_engine(migrated_database):
    """A connection as the schema owner (sms_migrator), for test set-up and clean-up.

    The owner is not limited by the API user's restrictions (append-only
    audit events, Row-Level Security), so it can see and empty everything.
    """
    app = create_app("testing")
    engine = create_engine(app.config["MIGRATION_DATABASE_URI"])
    # Start from empty tables, even if something else left data behind (for
    # example the browser tests' server, which shares this database).
    _empty_tables(engine)
    yield engine
    engine.dispose()


def _empty_tables(engine) -> None:
    with engine.begin() as connection:
        for table in TABLES_TO_CLEAN:
            connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608 (fixed names)


@pytest.fixture
def db_app(migrated_database, schema_owner_engine, app):
    """An app whose test database has every table, emptied again after the test."""
    yield app
    with app.app_context():
        db.session.remove()
    _empty_tables(schema_owner_engine)


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


@pytest.fixture
def make_student(db_app):
    """Create a student in a school (through Row-Level Security) and return its ID."""

    def _make(school_id, admission_number="ADM-001", full_name="Demo Student", **fields):
        with db_app.app_context():
            set_database_school(school_id)
            student = Student(
                school_id=school_id,
                admission_number=admission_number,
                full_name=full_name,
                **fields,
            )
            db.session.add(student)
            db.session.flush()
            # Read the ID before committing: afterwards, reloading the row
            # would run in a new transaction with no school, and RLS hides it.
            student_id = student.id
            db.session.commit()
            return student_id

    return _make


@pytest.fixture
def make_invitation(db_app):
    """Create an invitation (through Row-Level Security); return (id, token)."""

    def _make(school_id, invited_by, email="invitee@example.com", role="teacher", **fields):
        token = fields.pop("token", None) or f"test-token-{email}-{role}"
        now = datetime.now(UTC)
        values = {"expires_at": now + timedelta(days=7)} | fields
        with db_app.app_context():
            set_database_school(school_id)
            invitation = Invitation(
                school_id=school_id,
                email=email,
                role=role,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                invited_by_user_id=invited_by,
                **values,
            )
            db.session.add(invitation)
            db.session.flush()
            invitation_id = invitation.id
            db.session.commit()
            return invitation_id, token

    return _make
