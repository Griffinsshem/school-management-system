"""Report card comments in the database itself (D7).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug. All names and comments are made up.
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


def _comment(connection, s, comment="Works hard and helps others.", **overrides):
    """A comment of school data `s` (from the fixture), changed by `overrides`."""
    values = {
        "school_id": s["school"],
        "academic_year_id": s["year"],
        "class_id": s["class"],
        "term_id": s["term1"],
        "student_id": s["students"][0],
        "comment": comment,
        "updated_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "report_comments", **values)


@pytest.fixture
def two_schools(db_app, make_school, make_user):
    """Schools A and B, each with: a 2027 year with Terms 1 and 2; a 2028
    year with Term 1; a Grade 4 class in 2027 and one in 2028; two students;
    and a comment for the first student in Grade 4, 2027, Term 1."""
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
            s = {
                "school": school,
                "user": user,
                "year": y2027,
                "year_2028": y2028,
                "term1": term(y2027, 1, "2027-01-04", "2027-04-01"),
                "term2": term(y2027, 2, "2027-05-03", "2027-08-06"),
                "term_2028": term(y2028, 1, "2028-01-10", "2028-04-07"),
                "class": school_class("grade_4", y2027),
                "class_2028": school_class("grade_4", y2028),
                "students": [
                    _insert(
                        connection,
                        "students",
                        school_id=school,
                        admission_number=f"ADM-{n}",
                        full_name=f"Pupil {n}",
                    )  # fmt: skip
                    for n in (1, 2)
                ],
            }
            s["comment"] = _comment(connection, s)
        data[code] = s
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


# Keeping schools apart.


def test_only_the_current_schools_comments_are_visible(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text("SELECT DISTINCT school_id FROM report_comments"))
        assert list(rows.scalars()) == [a["school"]]

        _in_school(connection, None)
        count = connection.execute(text("SELECT count(*) FROM report_comments")).scalar_one()
        assert count == 0


def test_comments_cannot_be_written_into_another_school(db_app, two_schools):
    b = two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            _comment, connection, b, student_id=b["students"][1],
        )  # fmt: skip


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE report_comments SET comment = 'Changed.' WHERE school_id = :school",
        "DELETE FROM report_comments WHERE school_id = :school",
    ],
)
def test_another_schools_comments_cannot_be_changed_or_removed(db_app, two_schools, statement):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        result = connection.execute(text(statement), {"school": two_schools["b"]["school"]})
        assert result.rowcount == 0


# The class, term, year and student belong together.


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda a, b: {"term_id": a["term_2028"]}, "a term of another school year"),
        (lambda a, b: {"class_id": a["class_2028"]}, "a class of another school year"),
        (
            lambda a, b: {"academic_year_id": a["year_2028"]},
            "a year that is not the class's and term's",
        ),
        (lambda a, b: {"student_id": b["students"][1]}, "a student of another school"),
        (lambda a, b: {"class_id": b["class"]}, "a class of another school"),
        (lambda a, b: {"term_id": b["term2"]}, "a term of another school"),
    ],
)
def test_a_comment_cannot_point_at_rows_that_do_not_belong_together(
    db_app, two_schools, change, why
):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _comment, connection, a, **{"student_id": a["students"][1], **change(a, b)},
        )  # fmt: skip


def test_one_comment_per_student_class_and_term(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _comment, connection, a, "Another comment.")


def test_the_same_student_can_have_comments_in_other_terms_and_classes(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _comment(connection, a, term_id=a["term2"])
        _comment(
            connection, a, class_id=a["class_2028"], academic_year_id=a["year_2028"],
            term_id=a["term_2028"],
        )  # fmt: skip
        _comment(connection, a, student_id=a["students"][1])
        count = connection.execute(text("SELECT count(*) FROM report_comments")).scalar_one()
        assert count == 4


# The comment itself.


@pytest.mark.parametrize(
    "comment",
    ["", " ", " Leading space.", "Trailing space. ", "Trailing newline.\n", "\tTab first."],
)
def test_a_comment_is_never_empty_or_padded(db_app, two_schools, comment):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _comment, connection, a, comment, student_id=a["students"][1],
        )  # fmt: skip


@pytest.mark.parametrize(
    "comment", ["A", "Good term.\nKeep reading every day.", "x" * 500, "Amefanya vizuri sana."]
)
def test_plain_comments_up_to_500_characters_are_kept(db_app, two_schools, comment):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        comment_id = _comment(connection, a, comment, student_id=a["students"][1])
        stored = connection.execute(
            text("SELECT comment FROM report_comments WHERE id = :id"), {"id": comment_id}
        ).scalar_one()
        assert stored == comment


def test_a_comment_longer_than_500_characters_is_refused(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            STRING_TOO_LONG, DataError,
            _comment, connection, a, "x" * 501, student_id=a["students"][1],
        )  # fmt: skip


# Clearing and emptying.


def test_a_comment_can_be_cleared_in_its_own_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        result = connection.execute(
            text("DELETE FROM report_comments WHERE id = :id"), {"id": a["comment"]}
        )
        assert result.rowcount == 1


def test_the_table_cannot_be_emptied(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text("TRUNCATE report_comments"))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
