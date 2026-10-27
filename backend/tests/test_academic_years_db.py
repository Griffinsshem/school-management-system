"""School years and terms in the database itself (C1).

Like tests/test_row_level_security.py, these talk to PostgreSQL directly as
the API's user (sms_app), to prove the database keeps schools apart and
enforces its own rules even if an endpoint had a bug.
"""

import uuid
from datetime import date

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


def _add_term(
    connection, school_id, year_id, number=1, starts_on="2027-01-04", ends_on="2027-04-01"
):
    connection.execute(
        text(
            "INSERT INTO terms (id, school_id, academic_year_id, number, starts_on, ends_on) "
            "VALUES (:id, :school, :year, :number, :starts, :ends)"
        ),
        {
            "id": uuid.uuid4(),
            "school": school_id,
            "year": year_id,
            "number": number,
            "starts": starts_on,
            "ends": ends_on,
        },
    )


@pytest.fixture
def two_schools(db_app, make_school):
    """School A and School B, each with a year 2027 and its Term 1."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    years = {}
    with db_app.app_context(), db.engine.begin() as connection:
        for school in (school_a, school_b):
            _in_school(connection, school)
            years[school] = _add_year(connection, school)
            _add_term(connection, school, years[school])
            # Each transaction-local setting lasts until the next SET.
    return school_a, school_b, years


def _count(connection, table) -> int:
    return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


@pytest.mark.parametrize("table", ["academic_years", "terms"])
def test_only_the_current_schools_rows_are_visible(db_app, two_schools, table):
    school_a, school_b, _ = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        assert _count(connection, table) == 1
        rows = connection.execute(
            text(f"SELECT school_id FROM {table}")  # noqa: S608
        ).scalars()
        assert set(rows) == {school_a}

        _in_school(connection, None)
        assert _count(connection, table) == 0


def test_rows_cannot_be_written_into_another_school(db_app, two_schools):
    school_a, school_b, years = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(ProgrammingError) as excinfo:
            _add_year(connection, school_b, name="2028")
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_another_schools_rows_cannot_be_changed(db_app, two_schools):
    school_a, school_b, years = two_schools
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, school_a)
        changed = connection.execute(
            text("UPDATE academic_years SET name = 'Taken over' WHERE id = :id"),
            {"id": years[school_b]},
        )
        assert changed.rowcount == 0


def test_a_term_cannot_belong_to_another_schools_year(db_app, two_schools):
    school_a, school_b, years = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(IntegrityError) as excinfo:
            _add_term(connection, school_a, years[school_b], number=2)
        assert excinfo.value.orig.sqlstate == FOREIGN_KEY_VIOLATION


@pytest.mark.parametrize("table", ["academic_years", "terms"])
@pytest.mark.parametrize("statement", ["DELETE FROM {table}", "TRUNCATE {table}"])
def test_the_api_user_cannot_delete(db_app, two_schools, table, statement):
    school_a, _, _ = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement.format(table=table)))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


@pytest.mark.parametrize(
    ("name", "starts_on", "ends_on"),
    [
        (" 2028", "2028-01-03", "2028-11-24"),  # untrimmed name
        ("", "2028-01-03", "2028-11-24"),  # empty name
        ("2028", "2028-11-24", "2028-01-03"),  # ends before it starts
        ("2028", "2028-01-03", "2028-01-03"),  # no length at all
        ("2028", "2028-01-01", "2029-02-05"),  # 401 days
    ],
)
def test_database_rejects_malformed_years(db_app, two_schools, name, starts_on, ends_on):
    school_a, _, _ = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(IntegrityError) as excinfo:
            _add_year(connection, school_a, name=name, starts_on=starts_on, ends_on=ends_on)
        assert excinfo.value.orig.sqlstate == CHECK_VIOLATION


def test_a_year_of_exactly_400_days_is_allowed(db_app, two_schools):
    school_a, _, _ = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        _add_year(connection, school_a, name="2028", starts_on="2028-01-01", ends_on="2029-02-04")
        assert (date(2029, 2, 4) - date(2028, 1, 1)).days == 400


def test_year_names_are_unique_within_a_school_only(db_app, two_schools):
    school_a, school_b, _ = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(IntegrityError) as excinfo:
            _add_year(connection, school_a, name="2027")
        assert excinfo.value.orig.sqlstate == UNIQUE_VIOLATION
    # Both schools already have a "2027" (see the fixture).


@pytest.mark.parametrize(
    ("number", "starts_on", "ends_on", "sqlstate"),
    [
        (1, "2027-04-27", "2027-07-30", UNIQUE_VIOLATION),  # a second Term 1
        (4, "2027-08-23", "2027-10-22", CHECK_VIOLATION),  # no Term 4
        (0, "2027-08-23", "2027-10-22", CHECK_VIOLATION),
        (2, "2027-07-30", "2027-04-27", CHECK_VIOLATION),  # ends before it starts
    ],
)
def test_database_rejects_malformed_terms(
    db_app, two_schools, number, starts_on, ends_on, sqlstate
):
    school_a, _, years = two_schools
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, school_a)
        with pytest.raises(IntegrityError) as excinfo:
            _add_term(connection, school_a, years[school_a], number, starts_on, ends_on)
        assert excinfo.value.orig.sqlstate == sqlstate
