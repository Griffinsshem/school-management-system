"""Guardians and their links to students in the database itself (D2).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug. All names, numbers and emails are
made up.
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


def _guardian(connection, school, phone="+254700000001", name="Wanjiru Example", email=None):
    return _insert(
        connection, "guardians", school_id=school, full_name=name, phone=phone, email=email
    )


def _link(connection, school, student, guardian, relationship="mother", is_primary=False):
    return _insert(
        connection, "student_guardians", school_id=school, student_id=student,
        guardian_id=guardian, relationship=relationship, is_primary=is_primary,
    )  # fmt: skip


@pytest.fixture
def two_schools(db_app, make_school):
    """Schools A and B, each with two students and one guardian, who is the
    first student's primary guardian."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)
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
            guardian = _guardian(connection, school)
            link = _link(connection, school, students[0], guardian, is_primary=True)
        data[code] = {"school": school, "students": students, "guardian": guardian, "link": link}
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


@pytest.mark.parametrize("table", ["guardians", "student_guardians"])
def test_only_the_current_schools_rows_are_visible(db_app, two_schools, table):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text(f"SELECT school_id FROM {table}")).scalars()  # noqa: S608
        assert list(rows) == [a["school"]]

        _in_school(connection, None)
        count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
        assert count == 0


def test_guardians_cannot_be_written_into_another_school(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _guardian, connection, two_schools["b"]["school"], "+254700000002",
        )  # fmt: skip


def test_another_schools_guardians_cannot_be_changed(db_app, two_schools):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        changed = connection.execute(
            text("UPDATE guardians SET full_name = 'Changed' WHERE id = :id"),
            {"id": two_schools["b"]["guardian"]},
        )
        assert changed.rowcount == 0


@pytest.mark.parametrize("other", ["student", "guardian"])
def test_a_link_cannot_point_into_another_school(db_app, two_schools, other):
    a, b = two_schools["a"], two_schools["b"]
    student = b["students"][1] if other == "student" else a["students"][1]
    guardian = b["guardian"] if other == "guardian" else a["guardian"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _link, connection, a["school"], student, guardian,
        )  # fmt: skip


# One record per phone number per school.


def test_a_phone_number_is_used_once_per_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _guardian, connection, a["school"])
    # Another school may have the same number (a new transaction: the
    # refused one is over).
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["b"]["school"])
        count = connection.execute(
            text("SELECT count(*) FROM guardians WHERE phone = '+254700000001'")
        ).scalar_one()
        assert count == 1


# What a guardian may hold.


@pytest.mark.parametrize(
    ("phone", "refused"),
    [
        ("+254712345678", None),
        ("+254112345678", None),
        ("0712345678", CHECK_VIOLATION),  # local form: the API converts it
        ("254712345678", CHECK_VIOLATION),
        ("+254812345678", CHECK_VIOLATION),  # not a mobile prefix
        ("+25471234567", CHECK_VIOLATION),  # too short
        ("+2547123456789", STRING_TOO_LONG),
        (" +254712345678", STRING_TOO_LONG),
    ],
)
def test_phones_are_stored_in_one_standard_form(db_app, two_schools, phone, refused):
    school = two_schools["a"]["school"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school)
        if refused is None:
            _guardian(connection, school, phone)
        else:
            error = DataError if refused == STRING_TOO_LONG else IntegrityError
            _expect(refused, error, _guardian, connection, school, phone)


@pytest.mark.parametrize(
    ("email", "ok"),
    [
        (None, True),
        ("parent@example.com", True),
        ("Parent@example.com", False),
        (" parent@example.com", False),
        ("parent", False),
        ("a b@example.com", False),
        ("", False),
    ],
)
def test_emails_are_optional_and_normalised(db_app, two_schools, email, ok):
    school = two_schools["a"]["school"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school)
        if ok:
            _guardian(connection, school, "+254700000009", email=email)
        else:
            _expect(
                CHECK_VIOLATION, IntegrityError,
                _guardian, connection, school, "+254700000009", email=email,
            )  # fmt: skip


@pytest.mark.parametrize("name", ["", " Wanjiru", "Wanjiru "])
def test_names_are_trimmed(db_app, two_schools, name):
    school = two_schools["a"]["school"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school)
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _guardian, connection, school, "+254700000009", name,
        )  # fmt: skip


# Links.


@pytest.mark.parametrize(
    ("relationship", "ok"),
    [("father", True), ("grandparent", True), ("other_relative", True), ("uncle", False),
     ("Mother", False)],
)  # fmt: skip
def test_relationships_come_from_the_list(db_app, two_schools, relationship, ok):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        args = (connection, a["school"], a["students"][1], a["guardian"], relationship)
        if ok:
            _link(*args)
        else:
            _expect(CHECK_VIOLATION, IntegrityError, _link, *args)


def test_a_guardian_is_linked_to_a_student_once(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _link, connection, a["school"], a["students"][0], a["guardian"], "father",
        )  # fmt: skip


def test_a_student_has_at_most_one_primary_guardian(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        second = _guardian(connection, a["school"], "+254700000002")
        # Not primary: fine. Primary for another student: fine.
        _link(connection, a["school"], a["students"][0], second, "father")
        third = _guardian(connection, a["school"], "+254700000003")
        _link(connection, a["school"], a["students"][1], third, "father", is_primary=True)
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            connection.execute,
            text("UPDATE student_guardians SET is_primary = true WHERE guardian_id = :id"),
            {"id": second},
        )  # fmt: skip


# What can be removed.


@pytest.mark.parametrize(
    "statement",
    ["DELETE FROM guardians", "TRUNCATE guardians", "TRUNCATE student_guardians"],
)
def test_the_api_user_cannot_delete_guardians_or_empty_links(db_app, two_schools, statement):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_one_link_can_be_removed(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        removed = connection.execute(
            text("DELETE FROM student_guardians WHERE id = :id"), {"id": a["link"]}
        )
        assert removed.rowcount == 1
        # The guardian stays.
        count = connection.execute(text("SELECT count(*) FROM guardians")).scalar_one()
        assert count == 1


@pytest.mark.parametrize("table", ["students", "guardians"])
def test_linked_students_and_guardians_cannot_disappear(
    db_app, two_schools, schema_owner_engine, table
):
    a = two_schools["a"]
    row = a["students"][0] if table == "students" else a["guardian"]
    # Even the schema owner, which is not limited by Row-Level Security.
    with schema_owner_engine.begin() as connection, pytest.raises(IntegrityError) as excinfo:
        connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row})  # noqa: S608
    assert excinfo.value.orig.sqlstate == FOREIGN_KEY_VIOLATION
