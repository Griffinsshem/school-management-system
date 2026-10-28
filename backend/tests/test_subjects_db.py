"""Subjects, class subjects and subject teachers in the database itself (D3).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug. All names are made up.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from app.extensions import db

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
FOREIGN_KEY_VIOLATION = "23503"
STRING_TOO_LONG = "22001"

TABLES = ["subjects", "class_subjects", "subject_teachers"]


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


def _subject(connection, school, name="Mathematics", code=None):
    return _insert(connection, "subjects", school_id=school, name=name, code=code)


def _class_subject(connection, school, class_id, subject):
    return _insert(
        connection, "class_subjects", school_id=school, class_id=class_id, subject_id=subject
    )


def _subject_teacher(connection, school, class_subject, membership, role="teacher"):
    return _insert(
        connection, "subject_teachers", school_id=school, class_subject_id=class_subject,
        membership_id=membership, role=role,
    )  # fmt: skip


@pytest.fixture
def two_schools(db_app, make_school, make_user, add_member):
    """Schools A and B, each with a class Grade 4 East in 2027, a subject
    Mathematics (code MAT) taken by that class and taught by a teacher, a
    second unused subject, and a principal."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        teacher = add_member(make_user(email=f"teacher.{code}@example.com"), school, "teacher")
        principal = add_member(
            make_user(email=f"principal.{code}@example.com"), school, "principal"
        )
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)
            year = _insert(
                connection, "academic_years", school_id=school, name="2027",
                starts_on="2027-01-04", ends_on="2027-11-26",
            )  # fmt: skip
            school_class = _insert(
                connection, "classes", school_id=school, academic_year_id=year,
                grade="grade_4", stream="East",
            )  # fmt: skip
            maths = _subject(connection, school, "Mathematics", "MAT")
            english = _subject(connection, school, "English", "ENG")
            class_subject = _class_subject(connection, school, school_class, maths)
            assignment = _subject_teacher(connection, school, class_subject, teacher)
        data[code] = {
            "school": school,
            "class": school_class,
            "maths": maths,
            "english": english,
            "class_subject": class_subject,
            "assignment": assignment,
            "teacher": teacher,
            "principal": principal,
        }
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


@pytest.mark.parametrize("table", TABLES)
def test_only_the_current_schools_rows_are_visible(db_app, two_schools, table):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text(f"SELECT DISTINCT school_id FROM {table}")).scalars()  # noqa: S608
        assert list(rows) == [a["school"]]

        _in_school(connection, None)
        count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count == 0


def test_subjects_cannot_be_written_into_another_school(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _subject, connection, two_schools["b"]["school"], "Kiswahili",
        )  # fmt: skip


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE subjects SET name = 'Changed' WHERE school_id = :school",
        "DELETE FROM class_subjects WHERE school_id = :school",
        "DELETE FROM subject_teachers WHERE school_id = :school",
    ],
)
def test_another_schools_rows_cannot_be_changed_or_removed(db_app, two_schools, statement):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        result = connection.execute(text(statement), {"school": two_schools["b"]["school"]})
        assert result.rowcount == 0


@pytest.mark.parametrize("other", ["class", "subject"])
def test_a_class_subject_cannot_point_into_another_school(db_app, two_schools, other):
    a, b = two_schools["a"], two_schools["b"]
    class_id = b["class"] if other == "class" else a["class"]
    subject = b["english"] if other == "subject" else a["english"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _class_subject, connection, a["school"], class_id, subject,
        )  # fmt: skip


@pytest.mark.parametrize("other", ["class_subject", "teacher"])
def test_a_subject_teacher_cannot_point_into_another_school(db_app, two_schools, other):
    a, b = two_schools["a"], two_schools["b"]
    class_subject = b["class_subject"] if other == "class_subject" else a["class_subject"]
    teacher = b["teacher"] if other == "teacher" else a["teacher"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        connection.execute(text("DELETE FROM subject_teachers"))
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _subject_teacher, connection, a["school"], class_subject, teacher,
        )  # fmt: skip


# Only teachers teach.


def test_a_principal_membership_cannot_be_a_subject_teacher(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _subject_teacher, connection, a["school"], a["class_subject"], a["principal"],
        )  # fmt: skip


def test_the_role_column_may_only_say_teacher(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _subject_teacher, connection, a["school"], a["class_subject"], a["principal"],
            role="principal",
        )  # fmt: skip


# Names and codes.


@pytest.mark.parametrize("name", ["Mathematics", "MATHEMATICS", "mathematics"])
def test_a_subject_name_is_used_once_per_school_whatever_the_case(db_app, two_schools, name):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _subject, connection, a["school"], name)


@pytest.mark.parametrize("code", ["MAT", "mat", "Mat"])
def test_a_subject_code_is_used_once_per_school_whatever_the_case(db_app, two_schools, code):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _subject, connection, a["school"], "Music", code)


def test_many_subjects_may_have_no_code(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _subject(connection, a["school"], "Life Skills")
        _subject(connection, a["school"], "Pastoral Programme")
        count = connection.execute(
            text("SELECT count(*) FROM subjects WHERE code IS NULL")
        ).scalar_one()
        assert count == 2


def test_the_same_name_and_code_are_fine_in_another_school(db_app, two_schools):
    # The fixture gave both schools "Mathematics" with code "MAT".
    with db_app.app_context(), db.engine.connect() as connection:
        for code in ("a", "b"):
            _in_school(connection, two_schools[code]["school"])
            found = connection.execute(
                text("SELECT id FROM subjects WHERE name = 'Mathematics' AND code = 'MAT'")
            ).scalar_one()
            assert found == two_schools[code]["maths"]


@pytest.mark.parametrize(
    ("name", "code", "sqlstate"),
    [
        ("", None, CHECK_VIOLATION),
        (" Music", None, CHECK_VIOLATION),
        ("Music ", None, CHECK_VIOLATION),
        ("Music", "", CHECK_VIOLATION),
        ("Music", " MUS", CHECK_VIOLATION),
        ("M" * 61, None, STRING_TOO_LONG),
        ("Music", "M" * 11, STRING_TOO_LONG),
    ],
)
def test_database_rejects_malformed_subjects(db_app, two_schools, name, code, sqlstate):
    a = two_schools["a"]
    error = DataError if sqlstate == STRING_TOO_LONG else IntegrityError
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(sqlstate, error, _subject, connection, a["school"], name, code)


# Each link once.


def test_a_class_takes_a_subject_once(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _class_subject, connection, a["school"], a["class"], a["maths"],
        )  # fmt: skip


def test_a_teacher_is_assigned_to_a_class_subject_once(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _subject_teacher, connection, a["school"], a["class_subject"], a["teacher"],
        )  # fmt: skip


def test_a_class_subject_can_have_several_teachers(db_app, two_schools, make_user, add_member):
    a = two_schools["a"]
    second = add_member(make_user(email="teacher.a2@example.com"), a["school"], "teacher")
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _subject_teacher(connection, a["school"], a["class_subject"], second)
        count = connection.execute(
            text("SELECT count(*) FROM subject_teachers WHERE class_subject_id = :id"),
            {"id": a["class_subject"]},
        ).scalar_one()
        assert count == 2


# What the API's database user may remove.


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM subjects",
        "TRUNCATE subjects",
        "TRUNCATE class_subjects",
        "TRUNCATE subject_teachers",
    ],
)
def test_the_api_user_cannot_delete_subjects_or_empty_tables(db_app, two_schools, statement):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(INSUFFICIENT_PRIVILEGE, ProgrammingError, connection.execute, text(statement))


def test_a_class_subject_with_teachers_cannot_be_removed(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError, connection.execute,
            text("DELETE FROM class_subjects WHERE id = :id"), {"id": a["class_subject"]},
        )  # fmt: skip


def test_the_api_user_can_remove_links_in_its_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        teachers = connection.execute(
            text("DELETE FROM subject_teachers WHERE id = :id"), {"id": a["assignment"]}
        )
        subjects = connection.execute(
            text("DELETE FROM class_subjects WHERE id = :id"), {"id": a["class_subject"]}
        )
        assert (teachers.rowcount, subjects.rowcount) == (1, 1)
