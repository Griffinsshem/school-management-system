"""KCSE grade boundaries in the database itself (D5).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from app.extensions import db

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
STRING_TOO_LONG = "22001"


def _in_school(connection, school_id) -> None:
    value = str(school_id) if school_id else ""
    connection.execute(
        text("SELECT set_config('app.current_school_id', :value, true)"), {"value": value}
    )


def _boundary(connection, s, grade="A", min_percent=80, **overrides):
    values = {
        "id": uuid.uuid4(),
        "school_id": s["school"],
        "grade": grade,
        "min_percent": min_percent,
        "updated_by_user_id": s["user"],
        **overrides,
    }
    connection.execute(
        text(
            "INSERT INTO grade_boundaries (id, school_id, grade, min_percent, updated_by_user_id)"
            " VALUES (:id, :school_id, :grade, :min_percent, :updated_by_user_id)"
        ),
        values,
    )
    return values["id"]


@pytest.fixture
def two_schools(db_app, make_school, make_user):
    """Schools A and B, each with boundaries for A and E."""
    data = {}
    for code in ("a", "b"):
        s = {
            "school": make_school(code=f"school-{code}", name=f"School {code.upper()}"),
            "user": make_user(email=f"admin.{code}@example.com"),
        }
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, s["school"])
            _boundary(connection, s, "A", 80)
            _boundary(connection, s, "E", 0)
        data[code] = s
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


def test_only_the_current_schools_boundaries_are_visible(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text("SELECT DISTINCT school_id FROM grade_boundaries"))
        assert list(rows.scalars()) == [a["school"]]

        _in_school(connection, None)
        count = connection.execute(text("SELECT count(*) FROM grade_boundaries")).scalar_one()
        assert count == 0


def test_boundaries_cannot_be_written_into_another_school(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _boundary, connection, two_schools["b"], "B", 65,
        )  # fmt: skip


def test_another_schools_boundaries_cannot_be_changed(db_app, two_schools):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        result = connection.execute(
            text("UPDATE grade_boundaries SET min_percent = 90 WHERE school_id = :school"),
            {"school": two_schools["b"]["school"]},
        )
        assert result.rowcount == 0


# What a boundary may be.


def test_all_twelve_kcse_grades_fit(db_app, two_schools):
    a = two_schools["a"]
    others = ["A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        for n, grade in enumerate(others):
            _boundary(connection, a, grade, 75 - 5 * n)
        count = connection.execute(text("SELECT count(*) FROM grade_boundaries")).scalar_one()
        assert count == 12


@pytest.mark.parametrize(
    ("grade", "min_percent"),
    [
        ("F", 10),
        ("a", 80),
        ("A+", 90),
        ("", 50),
        ("B", -1),
        ("B", 101),
    ],
)
def test_database_rejects_malformed_boundaries(db_app, two_schools, grade, min_percent):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _boundary, connection, a, grade, min_percent)


def test_a_cbc_band_is_not_a_kcse_grade(db_app, two_schools):
    # The CBC/KJSEA scale is fixed in code and never stored here.
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(STRING_TOO_LONG, DataError, _boundary, connection, a, "EE1", 90)


@pytest.mark.parametrize("min_percent", [1, 30, 100])
def test_e_always_starts_at_zero(db_app, two_schools, min_percent):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError, connection.execute,
            text("UPDATE grade_boundaries SET min_percent = :value WHERE grade = 'E'"),
            {"value": min_percent},
        )  # fmt: skip


def test_a_grade_is_used_once_per_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _boundary, connection, a, "A", 85)


def test_a_boundary_can_be_changed(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        connection.execute(text("UPDATE grade_boundaries SET min_percent = 85 WHERE grade = 'A'"))
        value = connection.execute(
            text("SELECT min_percent FROM grade_boundaries WHERE grade = 'A'")
        ).scalar_one()
        assert value == 85


# What the API's database user may remove.


@pytest.mark.parametrize(
    "statement", ["DELETE FROM grade_boundaries WHERE grade = 'A'", "TRUNCATE grade_boundaries"]
)
def test_the_api_user_cannot_delete_or_empty_boundaries(db_app, two_schools, statement):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(INSUFFICIENT_PRIVILEGE, ProgrammingError, connection.execute, text(statement))
