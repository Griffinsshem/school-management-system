import uuid

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.auth.passwords import hash_password
from app.extensions import db
from app.models import Membership, School, User
from app.models.school import (
    KENYA_COUNTIES,
    SchoolCodeError,
    normalize_school_code,
    validate_school_code,
)

INSUFFICIENT_PRIVILEGE = "42501"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def _school(code: str = "greenfield-academy", **fields) -> School:
    values = {"name": "Greenfield Academy", "county_code": 47} | fields
    return School(code=code, **values)


def _user(email: str = "ada@example.com") -> User:
    return User(email=email, full_name="Ada Example", password_hash=hash_password("x" * 12))


def _commit_expecting(sqlstate: str) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        db.session.commit()
    db.session.rollback()
    assert excinfo.value.orig.sqlstate == sqlstate


@pytest.fixture
def user_and_school(db_app):
    """A saved user and school, returned as (user_id, school_id)."""
    with db_app.app_context():
        user, school = _user(), _school()
        db.session.add_all([user, school])
        db.session.commit()
        return user.id, school.id


def test_county_list_follows_the_constitution():
    assert list(KENYA_COUNTIES) == list(range(1, 48))
    assert KENYA_COUNTIES[1] == "Mombasa"
    assert KENYA_COUNTIES[30] == "Baringo"
    assert KENYA_COUNTIES[47] == "Nairobi City"
    assert len(set(KENYA_COUNTIES.values())) == 47


def test_school_code_is_normalized():
    assert normalize_school_code("  Greenfield-Academy ") == "greenfield-academy"


@pytest.mark.parametrize("code", ["abc", "st-marys-2", "a1b", "x" * 50])
def test_valid_school_codes_are_accepted(code):
    validate_school_code(code)


@pytest.mark.parametrize(
    "code", ["", "ab", "x" * 51, "-abc", "abc-", "a--b", "a b c", "abc_d", "Abc", "shule!"]
)
def test_invalid_school_codes_are_rejected(code):
    with pytest.raises(SchoolCodeError):
        validate_school_code(code)


def test_new_school_gets_safe_defaults(db_app):
    with db_app.app_context():
        school = _school(county_code=32)
        db.session.add(school)
        db.session.commit()

        assert isinstance(school.id, uuid.UUID)
        assert school.is_active is True
        # Class positions stay hidden until the school switches them on (D6).
        assert school.show_class_positions is False
        assert school.county_name == "Nakuru"
        assert school.created_at.tzinfo is not None


@pytest.mark.parametrize(
    "fields",
    [
        {"code": "Greenfield"},
        {"code": "green--field"},
        {"code": "ab"},
        {"county_code": 0},
        {"county_code": 48},
        {"name": ""},
        {"name": " Greenfield "},
    ],
)
def test_database_rejects_invalid_schools(db_app, fields):
    with db_app.app_context():
        values = {"code": "greenfield-academy"} | fields
        db.session.add(_school(**values))
        _commit_expecting(CHECK_VIOLATION)


def test_database_rejects_a_duplicate_school_code(db_app):
    with db_app.app_context():
        db.session.add(_school())
        db.session.commit()
        db.session.add(_school(name="Another School"))
        _commit_expecting(UNIQUE_VIOLATION)


def test_new_membership_is_active(db_app, user_and_school):
    user_id, school_id = user_and_school
    with db_app.app_context():
        membership = Membership(user_id=user_id, school_id=school_id, role="teacher")
        db.session.add(membership)
        db.session.commit()

        assert membership.is_active is True


def test_one_person_can_hold_two_roles_in_a_school(db_app, user_and_school):
    user_id, school_id = user_and_school
    with db_app.app_context():
        db.session.add_all(
            [
                Membership(user_id=user_id, school_id=school_id, role="teacher"),
                Membership(user_id=user_id, school_id=school_id, role="guardian"),
            ]
        )
        db.session.commit()


def test_database_rejects_a_duplicate_membership(db_app, user_and_school):
    user_id, school_id = user_and_school
    with db_app.app_context():
        db.session.add(Membership(user_id=user_id, school_id=school_id, role="teacher"))
        db.session.commit()
        db.session.add(Membership(user_id=user_id, school_id=school_id, role="teacher"))
        _commit_expecting(UNIQUE_VIOLATION)


@pytest.mark.parametrize("role", ["platform_admin", "admin", "Teacher", ""])
def test_database_rejects_an_unknown_role(db_app, user_and_school, role):
    user_id, school_id = user_and_school
    with db_app.app_context():
        db.session.add(Membership(user_id=user_id, school_id=school_id, role=role))
        _commit_expecting(CHECK_VIOLATION)


@pytest.mark.parametrize("model", [User, School])
def test_user_or_school_with_memberships_cannot_be_deleted(db_app, user_and_school, model):
    user_id, school_id = user_and_school
    with db_app.app_context():
        db.session.add(Membership(user_id=user_id, school_id=school_id, role="teacher"))
        db.session.commit()
        with pytest.raises(IntegrityError) as excinfo:
            db.session.execute(delete(model))
        db.session.rollback()

    assert excinfo.value.orig.sqlstate == FOREIGN_KEY_VIOLATION


@pytest.mark.parametrize("table", ["schools", "memberships"])
def test_runtime_user_cannot_alter_the_new_tables(db_app, table):
    with db_app.app_context(), db.engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN probe integer"))

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_repr_does_not_reveal_names():
    school = _school()
    school.id = uuid.uuid4()

    assert "greenfield" not in repr(school).lower()
    assert str(school.id) in repr(school)
