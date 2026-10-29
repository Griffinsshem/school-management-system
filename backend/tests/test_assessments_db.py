"""Assessments and marks in the database itself (D4).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug. All names and scores are made up.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from app.extensions import db

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
FOREIGN_KEY_VIOLATION = "23503"
NUMERIC_OUT_OF_RANGE = "22003"

TABLES = ["assessments", "marks"]


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


def _assessment(connection, s, name="Mid-term", **overrides):
    """An assessment of school data `s` (from the fixture), changed by `overrides`."""
    values = {
        "school_id": s["school"],
        "academic_year_id": s["year"],
        "class_id": s["class"],
        "class_subject_id": s["maths"],
        "term_id": s["term1"],
        "name": name,
        "max_score": 50,
        "held_on": "2027-03-01",
        "created_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "assessments", **values)


def _mark(connection, s, assessment, student=None, **overrides):
    values = {
        "school_id": s["school"],
        "assessment_id": assessment,
        "student_id": student or s["students"][0],
        "score": Decimal("12.5"),
        "did_not_sit": False,
        "updated_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "marks", **values)


@pytest.fixture
def two_schools(db_app, make_school, make_user):
    """Schools A and B, each with: a 2027 year with Terms 1 and 2; a 2028
    year with Term 1; Grade 4 and Grade 5 classes in 2027, each taking
    Mathematics; two students; and a Mid-term in Grade 4 Mathematics, Term 1,
    with one mark."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        user = make_user(email=f"teacher.{code}@example.com")
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)

            def year(name, starts, ends, connection=connection, school=school):
                return _insert(
                    connection, "academic_years", school_id=school, name=name,
                    starts_on=starts, ends_on=ends,
                )  # fmt: skip

            def term(year_id, number, starts, ends, connection=connection, school=school):
                return _insert(
                    connection, "terms", school_id=school, academic_year_id=year_id,
                    number=number, starts_on=starts, ends_on=ends,
                )  # fmt: skip

            def school_class(grade, year_id, connection=connection, school=school):
                return _insert(
                    connection, "classes", school_id=school, academic_year_id=year_id,
                    grade=grade, stream="East",
                )  # fmt: skip

            y2027 = year("2027", "2027-01-04", "2027-11-26")
            y2028 = year("2028", "2028-01-10", "2028-11-24")
            term1 = term(y2027, 1, "2027-01-04", "2027-04-01")
            term2 = term(y2027, 2, "2027-05-03", "2027-08-06")
            term_2028 = term(y2028, 1, "2028-01-10", "2028-04-07")
            grade4 = school_class("grade_4", y2027)
            grade5 = school_class("grade_5", y2027)
            subject = _insert(connection, "subjects", school_id=school, name="Mathematics")
            maths = _insert(
                connection, "class_subjects", school_id=school, class_id=grade4, subject_id=subject
            )
            maths5 = _insert(
                connection, "class_subjects", school_id=school, class_id=grade5, subject_id=subject
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
            s = {
                "school": school,
                "user": user,
                "year": y2027,
                "year_2028": y2028,
                "term1": term1,
                "term2": term2,
                "term_2028": term_2028,
                "class": grade4,
                "class5": grade5,
                "maths": maths,
                "maths5": maths5,
                "students": students,
            }
            s["assessment"] = _assessment(connection, s)
            s["mark"] = _mark(connection, s, s["assessment"])
        data[code] = s
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


def test_rows_cannot_be_written_into_another_school(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _assessment, connection, two_schools["b"], "End-term",
        )  # fmt: skip


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE assessments SET name = 'Changed' WHERE school_id = :school",
        "UPDATE marks SET score = 0 WHERE school_id = :school",
        "DELETE FROM marks WHERE school_id = :school",
    ],
)
def test_another_schools_rows_cannot_be_changed_or_removed(db_app, two_schools, statement):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        result = connection.execute(text(statement), {"school": two_schools["b"]["school"]})
        assert result.rowcount == 0


# An assessment's class, subject, term and year belong together.


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"class_subject_id": "maths5"}, "another class's subject"),
        ({"term_id": "term_2028"}, "a term of another year"),
        ({"academic_year_id": "year_2028", "term_id": "term_2028"}, "a class of another year"),
        ({"class_id": "class5"}, "a subject the class does not take"),
    ],
)
def test_an_assessment_cannot_mix_classes_subjects_or_years(db_app, two_schools, change, why):
    a = two_schools["a"]
    overrides = {column: a[key] for column, key in change.items()}
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _assessment, connection, a, "End-term", **overrides,
        )  # fmt: skip


@pytest.mark.parametrize("column", ["class_subject_id", "class_id", "term_id"])
def test_an_assessment_cannot_point_into_another_school(db_app, two_schools, column):
    a, b = two_schools["a"], two_schools["b"]
    key = {"class_subject_id": "maths", "class_id": "class", "term_id": "term1"}[column]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _assessment, connection, a, "End-term", **{column: b[key]},
        )  # fmt: skip


# Names, maximum scores and locks.


@pytest.mark.parametrize("name", ["Mid-term", "MID-TERM", "mid-term"])
def test_a_name_is_used_once_per_subject_and_term(db_app, two_schools, name):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _assessment, connection, a, name)


def test_the_same_name_is_fine_in_another_term_or_class(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _assessment(connection, a, term_id=a["term2"], held_on="2027-06-01")
        _assessment(connection, a, class_id=a["class5"], class_subject_id=a["maths5"])
        count = connection.execute(
            text("SELECT count(*) FROM assessments WHERE name = 'Mid-term'")
        ).scalar_one()
        assert count == 3


@pytest.mark.parametrize(
    ("overrides", "sqlstate"),
    [
        ({"name": ""}, CHECK_VIOLATION),
        ({"name": " CAT 1"}, CHECK_VIOLATION),
        ({"name": "CAT 1 "}, CHECK_VIOLATION),
        ({"max_score": 0}, CHECK_VIOLATION),
        ({"max_score": 1001}, CHECK_VIOLATION),
        ({"is_locked": True}, CHECK_VIOLATION),
        ({"locked_at": "2027-03-02T10:00:00+03:00"}, CHECK_VIOLATION),
    ],
)
def test_database_rejects_malformed_assessments(db_app, two_schools, overrides, sqlstate):
    a = two_schools["a"]
    values = {"name": "CAT 1", **overrides}
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(sqlstate, IntegrityError, _assessment, connection, a, **values)


def test_a_lock_records_who_and_when(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        locked = _assessment(
            connection, a, "Locked", max_score=1000, is_locked=True,
            locked_at="2027-03-02T10:00:00+03:00", locked_by_user_id=a["user"],
        )  # fmt: skip
        assert connection.execute(
            text("SELECT is_locked FROM assessments WHERE id = :id"), {"id": locked}
        ).scalar_one()


# Marks.


@pytest.mark.parametrize(
    "overrides",
    [
        {"score": Decimal("10"), "did_not_sit": True},
        {"score": None, "did_not_sit": False},
        {"score": Decimal("-0.5")},
    ],
)
def test_a_mark_is_a_score_or_did_not_sit(db_app, two_schools, overrides):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _mark, connection, a, a["assessment"], a["students"][1], **overrides,
        )  # fmt: skip


def test_did_not_sit_and_exact_half_marks_are_kept(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _mark(connection, a, a["assessment"], a["students"][1], score=None, did_not_sit=True)
        rows = connection.execute(
            text("SELECT score, did_not_sit FROM marks ORDER BY did_not_sit")
        ).all()
        assert [tuple(row) for row in rows] == [(Decimal("12.5"), False), (None, True)]


def test_a_second_decimal_place_is_rounded_so_the_api_must_refuse_it(db_app, two_schools):
    # Documents why the API refuses 12.55 instead of passing it on.
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _mark(connection, a, a["assessment"], a["students"][1], score=Decimal("12.55"))
        score = connection.execute(
            text("SELECT score FROM marks WHERE student_id = :id"), {"id": a["students"][1]}
        ).scalar_one()
        assert score == Decimal("12.6")


def test_scores_above_9999_9_do_not_fit(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            NUMERIC_OUT_OF_RANGE, DataError,
            _mark, connection, a, a["assessment"], a["students"][1], score=Decimal("10000"),
        )  # fmt: skip


def test_a_student_has_one_mark_per_assessment(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _mark, connection, a, a["assessment"])


@pytest.mark.parametrize("other", ["assessment", "student"])
def test_a_mark_cannot_point_into_another_school(db_app, two_schools, other):
    a, b = two_schools["a"], two_schools["b"]
    assessment = b["assessment"] if other == "assessment" else a["assessment"]
    student = b["students"][1] if other == "student" else a["students"][1]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _mark, connection, a, assessment, student,
        )  # fmt: skip


# What the API's database user may remove.


@pytest.mark.parametrize("statement", ["TRUNCATE assessments", "TRUNCATE marks"])
def test_the_api_user_cannot_empty_the_tables(db_app, two_schools, statement):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(INSUFFICIENT_PRIVILEGE, ProgrammingError, connection.execute, text(statement))


def test_an_assessment_with_marks_cannot_be_deleted(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError, connection.execute,
            text("DELETE FROM assessments WHERE id = :id"), {"id": a["assessment"]},
        )  # fmt: skip


def test_a_mark_and_then_an_empty_assessment_can_be_deleted(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        marks = connection.execute(text("DELETE FROM marks WHERE id = :id"), {"id": a["mark"]})
        assessments = connection.execute(
            text("DELETE FROM assessments WHERE id = :id"), {"id": a["assessment"]}
        )
        assert (marks.rowcount, assessments.rowcount) == (1, 1)


def test_a_subject_with_assessments_cannot_be_removed_from_its_class(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError, connection.execute,
            text("DELETE FROM class_subjects WHERE id = :id"), {"id": a["maths"]},
        )  # fmt: skip
