"""Classes and class teachers in the database itself (C2).

Like tests/test_academic_years_db.py, these talk to PostgreSQL directly as
the API's user (sms_app), to prove the database keeps schools apart and
enforces its own rules even if an endpoint had a bug.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.extensions import db
from app.models.school_class import GRADES, grade_exists_in, grades_in

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
FOREIGN_KEY_VIOLATION = "23503"


def _in_school(connection, school_id) -> None:
    value = str(school_id) if school_id else ""
    connection.execute(
        text("SELECT set_config('app.current_school_id', :value, true)"), {"value": value}
    )


def _add_year(connection, school_id, name="2027", starts_on="2027-01-04", ends_on="2027-11-26"):
    year_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO academic_years (id, school_id, name, starts_on, ends_on) "
            "VALUES (:id, :school, :name, :starts, :ends)"
        ),
        {"id": year_id, "school": school_id, "name": name, "starts": starts_on, "ends": ends_on},
    )
    return year_id


def _add_class(connection, school_id, year_id, grade="grade_4", stream="East"):
    class_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO classes (id, school_id, academic_year_id, grade, stream) "
            "VALUES (:id, :school, :year, :grade, :stream)"
        ),
        {"id": class_id, "school": school_id, "year": year_id, "grade": grade, "stream": stream},
    )
    return class_id


def _add_teacher(connection, school_id, class_id, membership_id, role="teacher"):
    connection.execute(
        text(
            "INSERT INTO class_teachers (id, school_id, class_id, membership_id, role) "
            "VALUES (:id, :school, :class, :membership, :role)"
        ),
        {
            "id": uuid.uuid4(),
            "school": school_id,
            "class": class_id,
            "membership": membership_id,
            "role": role,
        },
    )


@pytest.fixture
def two_schools(db_app, make_school, make_user, add_member):
    """Schools A and B, each with a year 2027, a class Grade 4 East, a
    teacher assigned to it, and a principal."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        teacher = add_member(make_user(email=f"teacher.{code}@example.com"), school, "teacher")
        principal = add_member(
            make_user(email=f"principal.{code}@example.com"), school, "principal"
        )
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)
            year = _add_year(connection, school)
            school_class = _add_class(connection, school, year)
            _add_teacher(connection, school, school_class, teacher)
        data[code] = {
            "school": school,
            "year": year,
            "class": school_class,
            "teacher": teacher,
            "principal": principal,
        }
    return data


def _expect(connection, sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(connection, *args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


@pytest.mark.parametrize("table", ["classes", "class_teachers"])
def test_only_the_current_schools_rows_are_visible(db_app, two_schools, table):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text(f"SELECT school_id FROM {table}")).scalars()  # noqa: S608
        assert list(rows) == [a["school"]]

        _in_school(connection, None)
        count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count == 0


def test_rows_cannot_be_written_into_another_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            connection, INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _add_class, b["school"], b["year"], "grade_5",
        )  # fmt: skip


def test_another_schools_rows_cannot_be_changed_or_removed(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        changed = connection.execute(
            text("UPDATE classes SET stream = 'Taken' WHERE id = :id"), {"id": b["class"]}
        )
        removed = connection.execute(
            text("DELETE FROM class_teachers WHERE class_id = :id"), {"id": b["class"]}
        )
        assert (changed.rowcount, removed.rowcount) == (0, 0)


def test_a_class_cannot_belong_to_another_schools_year(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            connection, FOREIGN_KEY_VIOLATION, IntegrityError,
            _add_class, a["school"], b["year"], "grade_5",
        )  # fmt: skip


def test_a_class_teacher_cannot_come_from_another_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            connection, FOREIGN_KEY_VIOLATION, IntegrityError,
            _add_teacher, a["school"], a["class"], b["teacher"],
        )  # fmt: skip


def test_a_teacher_cannot_be_assigned_to_another_schools_class(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            connection, FOREIGN_KEY_VIOLATION, IntegrityError,
            _add_teacher, a["school"], b["class"], a["teacher"],
        )  # fmt: skip


# Only teachers can be class teachers.


def test_a_principal_membership_cannot_be_a_class_teacher(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        # The row claims "teacher", but the membership's role is "principal".
        _expect(
            connection, FOREIGN_KEY_VIOLATION, IntegrityError,
            _add_teacher, a["school"], a["class"], a["principal"],
        )  # fmt: skip


def test_the_role_column_may_only_say_teacher(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            connection, CHECK_VIOLATION, IntegrityError,
            _add_teacher, a["school"], a["class"], a["principal"], role="principal",
        )  # fmt: skip


def test_a_teacher_is_assigned_to_a_class_once(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            connection, UNIQUE_VIOLATION, IntegrityError,
            _add_teacher, a["school"], a["class"], a["teacher"],
        )  # fmt: skip


def test_a_class_can_have_several_teachers(db_app, two_schools, make_user, add_member):
    a = two_schools["a"]
    second = add_member(make_user(email="second.teacher@example.com"), a["school"], "teacher")
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _add_teacher(connection, a["school"], a["class"], second)
        count = connection.execute(text("SELECT count(*) FROM class_teachers")).scalar_one()
        assert count == 2


# The class itself.


@pytest.mark.parametrize(
    ("grade", "stream", "sqlstate"),
    [
        ("grade_4", "East", UNIQUE_VIOLATION),  # already exists
        ("grade_13", None, CHECK_VIOLATION),  # no such grade
        ("Grade 4", None, CHECK_VIOLATION),  # labels are not codes
        ("grade_4", " East", CHECK_VIOLATION),  # untrimmed stream
        ("grade_4", "", CHECK_VIOLATION),  # empty stream (use none instead)
    ],
)
def test_database_rejects_malformed_classes(db_app, two_schools, grade, stream, sqlstate):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        with pytest.raises(IntegrityError) as excinfo:
            _add_class(connection, a["school"], a["year"], grade, stream)
        assert excinfo.value.orig.sqlstate == sqlstate


def test_only_one_class_of_a_grade_has_no_stream(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _add_class(connection, a["school"], a["year"], "grade_5", None)
        _expect(
            connection, UNIQUE_VIOLATION, IntegrityError,
            _add_class, a["school"], a["year"], "grade_5", None,
        )  # fmt: skip


def test_the_same_class_name_is_fine_in_another_year_or_stream(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _add_class(connection, a["school"], a["year"], "grade_4", "West")
        later = _add_year(connection, a["school"], "2028", "2028-01-03", "2028-11-24")
        _add_class(connection, a["school"], later, "grade_4", "East")
        assert connection.execute(text("SELECT count(*) FROM classes")).scalar_one() == 3


# What the API's database user may remove.


@pytest.mark.parametrize(
    "statement", ["DELETE FROM classes", "TRUNCATE classes", "TRUNCATE class_teachers"]
)
def test_the_api_user_cannot_delete_classes_or_empty_tables(db_app, two_schools, statement):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_the_api_user_can_remove_an_assignment_in_its_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        removed = connection.execute(
            text("DELETE FROM class_teachers WHERE class_id = :id"), {"id": a["class"]}
        )
        assert removed.rowcount == 1


# Which grades exist in which year (Kenya's move from 8-4-4 to CBC).


def _labels(year: int) -> list[str]:
    return [GRADES[grade] for grade in grades_in(year)]


@pytest.mark.parametrize(
    ("year", "top_grade", "forms"),
    [
        (2024, 8, [1, 2, 3, 4]),
        (2025, 9, [2, 3, 4]),
        (2026, 10, [3, 4]),
        (2027, 11, [4]),
        (2028, 12, []),
        (2040, 12, []),
    ],
)
def test_the_grades_offered_follow_the_transition(year, top_grade, forms):
    expected = (
        ["PP1", "PP2"]
        + [f"Grade {n}" for n in range(1, top_grade + 1)]
        + [f"Form {n}" for n in forms]
    )

    assert _labels(year) == expected


@pytest.mark.parametrize(
    ("grade", "first_year", "last_year"),
    [
        ("grade_10", 2026, None),
        ("grade_12", 2028, None),
        ("form_1", None, 2024),
        ("form_4", None, 2027),
        ("pp1", None, None),
        ("grade_6", None, None),
    ],
)
def test_grade_boundaries(grade, first_year, last_year):
    if first_year:
        assert not grade_exists_in(grade, first_year - 1)
        assert grade_exists_in(grade, first_year)
    if last_year:
        assert grade_exists_in(grade, last_year)
        assert not grade_exists_in(grade, last_year + 1)
    if not first_year and not last_year:
        assert grade_exists_in(grade, 2000) and grade_exists_in(grade, 2100)
