"""Row-Level Security on `students`, tested below the application layer.

These tests talk to PostgreSQL directly as the API's user (sms_app), the
way a buggy endpoint would, to prove the database itself keeps schools apart.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.auth.schools import current_school, school_required
from app.extensions import db
from app.models import Student

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
PASSWORD = "correct horse battery"


def _in_school(connection, school_id) -> None:
    value = str(school_id) if school_id else ""
    connection.execute(
        text("SELECT set_config('app.current_school_id', :value, true)"), {"value": value}
    )


def _admission_numbers(connection, where="") -> list[str]:
    rows = connection.execute(text(f"SELECT admission_number FROM students {where}"))  # noqa: S608
    return sorted(row[0] for row in rows)


@pytest.fixture
def two_schools(db_app, make_school, make_student):
    """School A with students A1 and A2; School B with student B1."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    make_student(school_a, "A1")
    make_student(school_a, "A2")
    make_student(school_b, "B1")
    return school_a, school_b


def test_only_the_current_schools_rows_are_visible(db_app, two_schools):
    school_a, school_b = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)

        assert _admission_numbers(connection) == ["A1", "A2"]
        # Even an explicit request for School B's rows returns nothing.
        assert _admission_numbers(connection, f"WHERE school_id = '{school_b}'") == []


@pytest.mark.parametrize("school", [None, "made-up"])
def test_no_school_or_an_unknown_school_sees_nothing(db_app, two_schools, school):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, uuid.uuid4() if school else None)

        assert _admission_numbers(connection) == []


def test_without_any_setting_nothing_is_visible(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        assert _admission_numbers(connection) == []


def test_rows_cannot_be_written_into_another_school(db_app, two_schools):
    school_a, school_b = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(
                text(
                    "INSERT INTO students (id, school_id, admission_number, full_name) "
                    "VALUES (:id, :school, 'X1', 'Intruder')"
                ),
                {"id": uuid.uuid4(), "school": school_b},
            )

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_rows_cannot_be_moved_to_another_school(db_app, two_schools):
    school_a, school_b = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(
                text("UPDATE students SET school_id = :b WHERE admission_number = 'A1'"),
                {"b": school_b},
            )

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_another_schools_rows_cannot_be_changed_or_deleted(db_app, two_schools):
    school_a, _school_b = two_schools
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, school_a)
        updated = connection.execute(text("UPDATE students SET full_name = 'Changed'"))
        deleted = connection.execute(text("DELETE FROM students WHERE admission_number = 'B1'"))

        assert updated.rowcount == 2  # Only School A's two students.
        assert deleted.rowcount == 0


def test_the_school_setting_ends_with_the_transaction(db_app, two_schools):
    """A pooled connection reused by the next request carries no school."""
    school_a, _school_b = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        with connection.begin():
            _in_school(connection, school_a)
            assert _admission_numbers(connection) == ["A1", "A2"]

        with connection.begin():
            setting = connection.execute(
                text("SELECT current_setting('app.current_school_id', true)")
            ).scalar()
            assert setting in (None, "")
            assert _admission_numbers(connection) == []


def test_the_api_user_cannot_switch_row_level_security_off(db_app):
    with db_app.app_context(), db.engine.connect() as connection:
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text("ALTER TABLE students DISABLE ROW LEVEL SECURITY"))

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_the_schema_owner_sees_every_school(two_schools, schema_owner_engine):
    with schema_owner_engine.connect() as connection:
        assert _admission_numbers(connection) == ["A1", "A2", "B1"]


def test_requests_see_only_their_active_schools_students(
    db_app, two_schools, make_user, add_member
):
    """The app wiring: the active school reaches the database, even after a commit."""
    school_a, school_b = two_schools
    user_id = make_user()
    add_member(user_id, school_a)

    @db_app.get("/test-only/students")
    @school_required
    def students_in_session():
        db.session.commit()  # A later transaction must still be limited.
        rows = db.session.scalars(
            db.select(Student.admission_number).where(Student.school_id.in_([school_a, school_b]))
        )
        return {"school": current_school().code, "students": sorted(rows)}

    client = db_app.test_client()
    client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": PASSWORD})

    assert client.get("/test-only/students").get_json() == {
        "school": "school-a",
        "students": ["A1", "A2"],
    }


def test_admission_numbers_are_unique_within_a_school_only(db_app, two_schools, make_student):
    school_a, school_b = two_schools

    make_student(school_b, "A1")  # Same number as School A's: allowed.
    with pytest.raises(IntegrityError) as excinfo:
        make_student(school_a, "A1")

    assert excinfo.value.orig.sqlstate == UNIQUE_VIOLATION


@pytest.mark.parametrize(
    "fields",
    [
        {"admission_number": ""},
        {"admission_number": " A9 "},
        {"full_name": ""},
        {"full_name": " Demo "},
    ],
)
def test_database_rejects_blank_or_untrimmed_values(db_app, make_school, make_student, fields):
    school_id = make_school()
    values = {"admission_number": "A9", "full_name": "Demo Student"} | fields

    with pytest.raises(IntegrityError) as excinfo:
        make_student(school_id, **values)

    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION


def test_repr_does_not_reveal_the_childs_details():
    student = Student(admission_number="ADM-7", full_name="Demo Child")
    student.id = uuid.uuid4()

    assert repr(student) == f"<Student {student.id}>"
