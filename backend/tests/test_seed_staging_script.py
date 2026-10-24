"""scripts/seed_staging.py: it only writes to sms_staging, and the demo data
it creates is complete, clearly fake and separated by school."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.auth.passwords import verify_password
from app.extensions import db
from app.models import Membership, School, Student, User
from app.school_context import set_database_school

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_staging.py"
spec = importlib.util.spec_from_file_location("seed_staging", SCRIPT)
seed_staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_staging)

PASSWORD = "staging demo password"  # noqa: S105 (test-only value)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "postgresql+psycopg://sms_app:x@127.0.0.1:5432/sms_dev",
        "postgresql+psycopg://sms_app:x@127.0.0.1:5432/sms_test",
        "postgresql+psycopg://sms_app:x@example.com/sms_staging_old",
    ],
)
def test_refuses_any_database_but_staging(url):
    with pytest.raises(seed_staging.SeedError, match="only runs against 'sms_staging'"):
        seed_staging.check_target(url)


def test_accepts_the_staging_database():
    seed_staging.check_target(
        "postgresql+psycopg://sms_app:x@ep-calm-sun-123.eu-central-1.aws.neon.tech/sms_staging"
        "?sslmode=require"
    )


def test_seed_creates_fake_demo_data(db_app):
    with db_app.app_context():
        counts = seed_staging.seed(PASSWORD)

        assert counts == {"schools": 2, "people": 4, "memberships": 4, "students": 15}
        users = db.session.scalars(select(User)).all()
        assert {user.email.split("@")[1] for user in users} == {"example.com"}
        assert all(verify_password(user.password_hash, PASSWORD) for user in users)
        platform = [user.email for user in users if user.is_platform_admin]
        assert platform == ["staging.platform@example.com"]
        assert db.session.scalar(select(func.count()).select_from(Membership)) == 4


def test_students_are_separated_by_school(db_app):
    with db_app.app_context():
        seed_staging.seed(PASSWORD)
        schools = {school.code: school.id for school in db.session.scalars(select(School))}

        def visible_students(school_id):
            set_database_school(school_id)
            return db.session.scalars(select(Student)).all()

        school_a = visible_students(schools["staging-demo-a"])
        assert len(school_a) == 12
        assert all(student.full_name.endswith(" Demo") for student in school_a)
        assert len(visible_students(schools["staging-demo-b"])) == 3
        assert visible_students(None) == []


def test_seed_runs_only_once(db_app):
    with db_app.app_context():
        seed_staging.seed(PASSWORD)
        with pytest.raises(seed_staging.SeedError, match="already there"):
            seed_staging.seed(PASSWORD)


def test_weak_password_adds_nothing(db_app):
    with db_app.app_context():
        with pytest.raises(seed_staging.SeedError):
            seed_staging.seed("short")
        db.session.rollback()
        assert db.session.scalar(select(func.count()).select_from(School)) == 0
        assert db.session.scalar(select(func.count()).select_from(User)) == 0
