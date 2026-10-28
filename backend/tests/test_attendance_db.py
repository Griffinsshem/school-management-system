"""Attendance registers and marks in the database itself (D1).

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
CHECK_VIOLATION = "23514"
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


def _register(connection, school, year, school_class, user, day="2027-02-01"):
    return _insert(
        connection, "attendance_registers", school_id=school, academic_year_id=year,
        class_id=school_class, date=day, taken_by_user_id=user, updated_by_user_id=user,
    )  # fmt: skip


def _mark(connection, school, register, student, status="present", reason=None):
    return _insert(
        connection, "attendance_marks", school_id=school, register_id=register,
        student_id=student, status=status, reason=reason,
    )  # fmt: skip


@pytest.fixture
def two_schools(db_app, make_school, make_user):
    """Schools A and B, each with a year 2027, a class, two students (the
    first enrolled) and a register for 1 February 2027 marking the first
    student present."""
    user = make_user(email="teacher@example.com")
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)
            year = _insert(
                connection, "academic_years", school_id=school, name="2027",
                starts_on="2027-01-04", ends_on="2027-11-26",
            )  # fmt: skip
            school_class = _insert(
                connection, "classes", school_id=school, academic_year_id=year, grade="grade_4"
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
            enrolment = _insert(
                connection, "enrolments", school_id=school, academic_year_id=year,
                class_id=school_class, student_id=students[0],
            )  # fmt: skip
            register = _register(connection, school, year, school_class, user)
            _mark(connection, school, register, students[0])
        data[code] = {
            "school": school,
            "year": year,
            "class": school_class,
            "students": students,
            "enrolment": enrolment,
            "register": register,
        }
    data["user"] = user
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


@pytest.mark.parametrize("table", ["attendance_registers", "attendance_marks"])
def test_only_the_current_schools_rows_are_visible(db_app, two_schools, table):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text(f"SELECT school_id FROM {table}")).scalars()  # noqa: S608
        assert list(rows) == [a["school"]]

        _in_school(connection, None)
        count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count == 0


def test_registers_cannot_be_written_into_another_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _register, connection, b["school"], b["year"], b["class"], two_schools["user"],
            day="2027-02-02",
        )  # fmt: skip


def test_another_schools_marks_cannot_be_changed(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        changed = connection.execute(
            text("UPDATE attendance_marks SET status = 'absent' WHERE register_id = :id"),
            {"id": b["register"]},
        )
        assert changed.rowcount == 0


def test_a_register_cannot_be_for_another_schools_class(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _register, connection, a["school"], a["year"], b["class"], two_schools["user"],
            day="2027-02-02",
        )  # fmt: skip


@pytest.mark.parametrize("other", ["student", "register"])
def test_a_mark_cannot_point_into_another_school(db_app, two_schools, other):
    a, b = two_schools["a"], two_schools["b"]
    register = b["register"] if other == "register" else a["register"]
    student = b["students"][1] if other == "student" else a["students"][1]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _mark, connection, a["school"], register, student,
        )  # fmt: skip


# One register per class per day, one mark per student.


def test_one_register_per_class_per_day(db_app, two_schools):
    a, user = two_schools["a"], two_schools["user"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _register, connection, a["school"], a["year"], a["class"], user,
        )  # fmt: skip
    # Another day is fine (a new transaction: the refused one is over).
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _register(connection, a["school"], a["year"], a["class"], user, "2027-02-02")


def test_one_mark_per_student_per_register(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _mark, connection, a["school"], a["register"], a["students"][0], "absent",
        )  # fmt: skip


# What a mark may say.


@pytest.mark.parametrize(
    ("status", "reason", "sqlstate"),
    [
        ("absent", None, None),
        ("absent", "sick", None),
        ("absent", "permission", None),
        ("late", None, None),
        ("excused", None, CHECK_VIOLATION),  # not a status
        ("present", "sick", CHECK_VIOLATION),  # only absences have a reason
        ("late", "unknown", CHECK_VIOLATION),
        ("absent", "had a fever", CHECK_VIOLATION),  # no free text about children
    ],
)
def test_marks_hold_a_status_and_only_listed_reasons(db_app, two_schools, status, reason, sqlstate):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        if sqlstate is None:
            _mark(connection, a["school"], a["register"], a["students"][1], status, reason)
        else:
            _expect(
                sqlstate, IntegrityError,
                _mark, connection, a["school"], a["register"], a["students"][1], status, reason,
            )  # fmt: skip


# Nothing is deleted; history stays.


@pytest.mark.parametrize("table", ["attendance_registers", "attendance_marks"])
@pytest.mark.parametrize("statement", ["DELETE FROM {table}", "TRUNCATE {table}"])
def test_the_api_user_cannot_delete(db_app, two_schools, table, statement):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement.format(table=table)))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_marks_stay_when_a_student_leaves_the_class(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        connection.execute(text("DELETE FROM enrolments WHERE id = :id"), {"id": a["enrolment"]})
        count = connection.execute(
            text("SELECT count(*) FROM attendance_marks WHERE student_id = :id"),
            {"id": a["students"][0]},
        ).scalar_one()
        assert count == 1


def test_a_student_with_marks_cannot_disappear(db_app, two_schools, schema_owner_engine):
    student = two_schools["a"]["students"][0]
    # Even the schema owner, which is not limited by Row-Level Security.
    with schema_owner_engine.begin() as connection, pytest.raises(IntegrityError) as excinfo:
        connection.execute(text("DELETE FROM enrolments WHERE student_id = :id"), {"id": student})
        connection.execute(text("DELETE FROM students WHERE id = :id"), {"id": student})
    assert excinfo.value.orig.sqlstate == FOREIGN_KEY_VIOLATION
