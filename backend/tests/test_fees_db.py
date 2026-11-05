"""Fee structures and bills in the database itself (E1).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug: above all, that what a family owes
can only be added to, never changed or deleted. All names are made up.
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

TABLES = ("fee_structures", "fee_items", "bills", "bill_lines")


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


def _structure(connection, s, **overrides):
    values = {
        "school_id": s["school"],
        "academic_year_id": s["year"],
        "term_id": s["term2"],
        "grade": "grade_4",
        "updated_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "fee_structures", **values)


def _item(connection, s, name="Lunch", amount=4_000, **overrides):
    values = {
        "school_id": s["school"],
        "structure_id": s["structure"],
        "name": name,
        "amount_kes": amount,
        "is_optional": False,
        "position": 9,
        **overrides,
    }
    return _insert(connection, "fee_items", **values)


def _bill(connection, s, **overrides):
    values = {
        "school_id": s["school"],
        "academic_year_id": s["year"],
        "term_id": s["term1"],
        "structure_id": s["structure"],
        "class_id": s["class"],
        "student_id": s["students"][1],
        "issued_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "bills", **values)


def _line(connection, s, **overrides):
    """A fee line for School s's Boarding (optional) on the first student's bill."""
    values = {
        "school_id": s["school"],
        "bill_id": s["bill"],
        "structure_id": s["structure"],
        "kind": "fee",
        "fee_item_id": s["boarding"],
        "description": "Boarding",
        "amount_kes": 30_000,
        "created_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "bill_lines", **values)


def _adjustment(connection, s, amount=-5_000, reason="Bursary from the county", **overrides):
    return _line(
        connection, s, kind="adjustment", fee_item_id=None, description=reason,
        amount_kes=amount, **overrides,
    )  # fmt: skip


@pytest.fixture
def two_schools(db_app, make_school, make_user):
    """Schools A and B, each with: a 2027 year with Terms 1 and 2; a 2028
    year with Term 1; Grade 4 and Grade 5 classes in 2027 and a Grade 4
    class in 2028; two students; Grade 4's Term 1 structure (Tuition 15,000,
    Boarding 30,000 optional) and Grade 5's (Tuition 16,000); and the first
    student's Term 1 bill with its Tuition line."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        user = make_user(email=f"bursar.{code}@example.com")
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
                "class_grade_5": school_class("grade_5", y2027),
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
            s["structure"] = _structure(connection, s, term_id=s["term1"])
            s["tuition"] = _item(connection, s, "Tuition", 15_000, position=0)
            s["boarding"] = _item(connection, s, "Boarding", 30_000, position=1, is_optional=True)
            s["structure_grade_5"] = _structure(connection, s, term_id=s["term1"], grade="grade_5")
            s["tuition_grade_5"] = _item(
                connection, s, "Tuition", 16_000, position=0, structure_id=s["structure_grade_5"]
            )
            s["bill"] = _bill(connection, s, student_id=s["students"][0])
            s["tuition_line"] = _line(
                connection, s, fee_item_id=s["tuition"], description="Tuition", amount_kes=15_000
            )
        data[code] = s
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


def _count(connection, table) -> int:
    return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


# Keeping schools apart.


@pytest.mark.parametrize("table", TABLES)
def test_only_the_current_schools_fee_rows_are_visible(db_app, two_schools, table):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text(f"SELECT DISTINCT school_id FROM {table}"))  # noqa: S608
        assert list(rows.scalars()) == [a["school"]]

        _in_school(connection, None)
        assert _count(connection, table) == 0


@pytest.mark.parametrize(
    ("write", "why"),
    [
        (lambda c, b: _structure(c, b), "a structure"),
        (lambda c, b: _item(c, b), "an item"),
        (lambda c, b: _bill(c, b), "a bill"),
        (lambda c, b: _adjustment(c, b), "a bill line"),
    ],
)
def test_fee_rows_cannot_be_written_into_another_school(db_app, two_schools, write, why):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(INSUFFICIENT_PRIVILEGE, ProgrammingError, write, connection, two_schools["b"])


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE fee_structures SET grade = 'grade_6' WHERE school_id = :school",
        "UPDATE fee_items SET amount_kes = 1 WHERE school_id = :school",
        "DELETE FROM fee_items WHERE school_id = :school",
    ],
)
def test_another_schools_structures_cannot_be_changed(db_app, two_schools, statement):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        result = connection.execute(text(statement), {"school": two_schools["b"]["school"]})
        assert result.rowcount == 0


# Rows that must belong together.


def test_a_structures_term_is_in_its_year(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _structure, connection, a, term_id=a["term_2028"],
        )  # fmt: skip


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda a, b: {"student_id": b["students"][1]}, "a student of another school"),
        (lambda a, b: {"class_id": a["class_2028"]}, "a class of another school year"),
        (lambda a, b: {"class_id": b["class"]}, "a class of another school"),
        (lambda a, b: {"term_id": a["term2"]}, "a term the structure is not for"),
        (lambda a, b: {"structure_id": b["structure"]}, "a structure of another school"),
        (
            lambda a, b: {
                "academic_year_id": a["year_2028"],
                "term_id": a["term_2028"],
                "class_id": a["class_2028"],
            },
            "a structure of another school year",
        ),  # fmt: skip
    ],
)
def test_a_bill_cannot_point_at_rows_that_do_not_belong_together(db_app, two_schools, change, why):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(FOREIGN_KEY_VIOLATION, IntegrityError, _bill, connection, a, **change(a, b))


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda a, b: {"fee_item_id": a["tuition_grade_5"]}, "an item of another structure"),
        (lambda a, b: {"structure_id": a["structure_grade_5"]}, "not the bill's structure"),
        (lambda a, b: {"fee_item_id": b["boarding"]}, "an item of another school"),
        (lambda a, b: {"bill_id": b["bill"]}, "a bill of another school"),
    ],
)
def test_a_fee_line_is_an_item_of_its_bills_own_structure(db_app, two_schools, change, why):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(FOREIGN_KEY_VIOLATION, IntegrityError, _line, connection, a, **change(a, b))


# One of each.


def test_one_structure_per_grade_and_term(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _structure, connection, a, term_id=a["term1"])


def test_the_same_grade_has_a_structure_in_every_term(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _structure(connection, a)
        _structure(connection, a, grade="grade_5")
        _structure(connection, a, academic_year_id=a["year_2028"], term_id=a["term_2028"])
        assert _count(connection, "fee_structures") == 5


@pytest.mark.parametrize("name", ["Tuition", "tuition", "TUITION"])
def test_item_names_are_unique_in_a_structure_ignoring_case(db_app, two_schools, name):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(UNIQUE_VIOLATION, IntegrityError, _item, connection, a, name)


def test_a_structure_has_many_items_and_names_repeat_across_structures(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        for n, name in enumerate(["Activity", "Lunch", "Transport", "Exams"]):
            _item(connection, a, name, position=2 + n)
        _item(connection, a, "Boarding", structure_id=a["structure_grade_5"], position=1)
        rows = connection.execute(
            text("SELECT count(*) FROM fee_items WHERE structure_id = :id"),
            {"id": a["structure"]},
        )
        assert rows.scalar_one() == 6


def test_one_bill_per_student_and_term(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _bill, connection, a, student_id=a["students"][0],
            structure_id=a["structure_grade_5"], class_id=a["class_grade_5"],
        )  # fmt: skip


def test_an_item_is_on_a_bill_at_most_once(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _line, connection, a, fee_item_id=a["tuition"], description="Tuition",
        )  # fmt: skip


def test_a_bill_can_have_several_adjustments(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _line(connection, a)
        _adjustment(connection, a)
        _adjustment(connection, a, 2_500, "Damaged desk")
        total = connection.execute(
            text("SELECT sum(amount_kes) FROM bill_lines WHERE bill_id = :id"), {"id": a["bill"]}
        ).scalar_one()
        assert total == 15_000 + 30_000 - 5_000 + 2_500


# Amounts, names and kinds.


@pytest.mark.parametrize("amount", [0, -1, 1_000_001])
def test_item_amounts_are_1_to_1_000_000_shillings(db_app, two_schools, amount):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _item, connection, a, amount=amount)


@pytest.mark.parametrize("amount", [1, 1_000_000])
def test_the_smallest_and_largest_item_amounts_are_kept(db_app, two_schools, amount):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _item(connection, a, amount=amount)


@pytest.mark.parametrize("name", ["", " ", " Lunch", "Lunch ", "Lunch\n", "\tLunch"])
def test_item_names_are_never_empty_or_padded(db_app, two_schools, name):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _item, connection, a, name)


def test_item_names_are_at_most_60_characters(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _item(connection, a, "x" * 60)
        _expect(STRING_TOO_LONG, DataError, _item, connection, a, "y" * 61)


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"fee_item_id": None}, "a fee line without an item"),
        ({"amount_kes": -30_000}, "a negative fee line"),
        ({"amount_kes": 0}, "a fee line of 0"),
        ({"kind": "adjustment"}, "an adjustment with an item"),
        ({"kind": "payment"}, "an unknown kind"),
        ({"description": " Boarding"}, "a padded description"),
    ],
)
def test_fee_lines_are_checked(db_app, two_schools, overrides, why):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _line, connection, a, **overrides)


@pytest.mark.parametrize("amount", [0, 1_000_001, -1_000_001])
def test_adjustments_are_never_0_or_beyond_a_million(db_app, two_schools, amount):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _adjustment, connection, a, amount)


@pytest.mark.parametrize("reason", ["", " ", "Bursary ", "\nBursary"])
def test_adjustments_always_give_a_reason(db_app, two_schools, reason):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _adjustment, connection, a, reason=reason)


def test_adjustment_reasons_are_at_most_200_characters(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _adjustment(connection, a, -1_000_000, "x" * 200)
        _expect(STRING_TOO_LONG, DataError, _adjustment, connection, a, reason="y" * 201)


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"grade": "grade_13"}, "a grade that does not exist"),
        ({"issued_at": "2027-01-05T08:00:00+03:00"}, "issued, but by nobody"),
    ],
)
def test_structures_are_checked(db_app, two_schools, overrides, why):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _structure, connection, a, **overrides)


# Only ever added to.


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE bills SET class_id = class_id WHERE id = :bill",
        "DELETE FROM bills WHERE id = :bill",
        "UPDATE bill_lines SET amount_kes = 1 WHERE bill_id = :bill",
        "DELETE FROM bill_lines WHERE bill_id = :bill",
        "DELETE FROM fee_structures WHERE id = :structure",
    ],
)
def test_bills_and_their_lines_are_never_changed_or_deleted(db_app, two_schools, statement):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement), {"bill": a["bill"], "structure": a["structure"]})
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_an_unbilled_item_can_be_removed_but_a_billed_one_cannot(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        removed = connection.execute(
            text("DELETE FROM fee_items WHERE id = :id"), {"id": a["boarding"]}
        )
        assert removed.rowcount == 1
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            connection.execute, text("DELETE FROM fee_items WHERE id = :id"), {"id": a["tuition"]},
        )  # fmt: skip


@pytest.mark.parametrize("table", TABLES)
def test_fee_tables_cannot_be_emptied(db_app, two_schools, table):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(f"TRUNCATE {table}"))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
