"""Enrolments in the database itself (C3).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.extensions import db

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"


def _in_school(connection, school_id) -> None:
    value = str(school_id) if school_id else ""
    connection.execute(
        text("SELECT set_config('app.current_school_id', :value, true)"), {"value": value}
    )


def _insert(connection, table, **values):
    values = {"id": uuid.uuid4(), **values}
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    connection.execute(
        text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"),  # noqa: S608
        values,
    )
    return values["id"]


def _enrol(connection, school, year, school_class, student):
    return _insert(
        connection,
        "enrolments",
        school_id=school,
        academic_year_id=year,
        class_id=school_class,
        student_id=student,
    )


@pytest.fixture
def two_schools(db_app, make_school):
    """Schools A and B, each with years 2027 and 2028, classes Grade 4 East
    and Grade 5 in 2027 and Grade 5 in 2028, and two students; student 1 is
    in Grade 4 East in 2027."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)
            y2027 = _insert(
                connection, "academic_years", school_id=school, name="2027",
                starts_on="2027-01-04", ends_on="2027-11-26",
            )  # fmt: skip
            y2028 = _insert(
                connection, "academic_years", school_id=school, name="2028",
                starts_on="2028-01-10", ends_on="2028-11-24",
            )  # fmt: skip
            g4 = _insert(
                connection, "classes", school_id=school, academic_year_id=y2027,
                grade="grade_4", stream="East",
            )  # fmt: skip
            g5 = _insert(
                connection, "classes", school_id=school, academic_year_id=y2027, grade="grade_5"
            )
            g5_2028 = _insert(
                connection, "classes", school_id=school, academic_year_id=y2028, grade="grade_5"
            )
            students = [
                _insert(
                    connection,
                    "students",
                    school_id=school,
                    admission_number=f"ADM-{n}",
                    full_name=f"Pupil {n}",
                )  # fmt: skip
                for n in (1, 2)
            ]
            enrolment = _enrol(connection, school, y2027, g4, students[0])
        data[code] = {
            "school": school,
            "y2027": y2027,
            "y2028": y2028,
            "g4": g4,
            "g5": g5,
            "g5_2028": g5_2028,
            "students": students,
            "enrolment": enrolment,
        }
    return data


def _expect(sqlstate, error, statement, *args):
    with pytest.raises(error) as excinfo:
        statement(*args)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


def test_only_the_current_schools_enrolments_are_visible(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text("SELECT school_id FROM enrolments")).scalars()
        assert list(rows) == [a["school"]]

        _in_school(connection, None)
        assert connection.execute(text("SELECT count(*) FROM enrolments")).scalar_one() == 0


def test_enrolments_cannot_be_written_into_another_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _enrol, connection, b["school"], b["y2027"], b["g5"], b["students"][1],
        )  # fmt: skip


def test_another_schools_enrolments_cannot_be_moved_or_removed(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        moved = connection.execute(
            text("UPDATE enrolments SET class_id = :to WHERE id = :id"),
            {"to": b["g5"], "id": b["enrolment"]},
        )
        removed = connection.execute(
            text("DELETE FROM enrolments WHERE id = :id"), {"id": b["enrolment"]}
        )
        assert (moved.rowcount, removed.rowcount) == (0, 0)


@pytest.mark.parametrize("other", ["student", "class"])
def test_the_student_and_class_must_be_of_the_same_school(db_app, two_schools, other):
    a, b = two_schools["a"], two_schools["b"]
    student = b["students"][1] if other == "student" else a["students"][1]
    school_class = b["g5"] if other == "class" else a["g5"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _enrol, connection, a["school"], a["y2027"], school_class, student,
        )  # fmt: skip


def test_the_class_must_be_in_the_enrolments_year(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        # Says 2027, but the class is a 2028 class.
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _enrol, connection, a["school"], a["y2027"], a["g5_2028"], a["students"][1],
        )  # fmt: skip


# One class per student per year.


def test_a_student_is_in_one_class_per_year(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _enrol, connection, a["school"], a["y2027"], a["g5"], a["students"][0],
        )  # fmt: skip


def test_a_student_has_a_class_in_each_year(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _enrol(connection, a["school"], a["y2028"], a["g5_2028"], a["students"][0])
        count = connection.execute(
            text("SELECT count(*) FROM enrolments WHERE student_id = :id"),
            {"id": a["students"][0]},
        ).scalar_one()
        assert count == 2


def test_a_student_moves_within_the_year_only(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        moved = connection.execute(
            text("UPDATE enrolments SET class_id = :to WHERE id = :id"),
            {"to": a["g5"], "id": a["enrolment"]},
        )
        assert moved.rowcount == 1
        with pytest.raises(IntegrityError) as excinfo:
            connection.execute(
                text("UPDATE enrolments SET class_id = :to WHERE id = :id"),
                {"to": a["g5_2028"], "id": a["enrolment"]},
            )
        assert excinfo.value.orig.sqlstate == FOREIGN_KEY_VIOLATION


# What the API's database user may remove.


def test_the_api_user_cannot_empty_the_table(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text("TRUNCATE enrolments"))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_the_api_user_can_remove_an_enrolment_in_its_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        removed = connection.execute(
            text("DELETE FROM enrolments WHERE id = :id"), {"id": a["enrolment"]}
        )
        assert removed.rowcount == 1


def test_an_enrolled_student_and_class_cannot_disappear(db_app, two_schools, schema_owner_engine):
    a = two_schools["a"]
    # Even the schema owner, which is not limited by Row-Level Security.
    for table, row in (("students", a["students"][0]), ("classes", a["g4"])):
        with schema_owner_engine.begin() as connection, pytest.raises(IntegrityError) as excinfo:
            connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row})  # noqa: S608
        assert excinfo.value.orig.sqlstate == FOREIGN_KEY_VIOLATION
