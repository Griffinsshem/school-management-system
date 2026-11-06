"""Payments, cancellations and receipt numbers in the database itself (E2).

Like the other *_db tests, these talk to PostgreSQL directly as the API's
user (sms_app), to prove the database keeps schools apart and enforces its
own rules even if an endpoint had a bug: above all, that money received is
only ever added to, never changed or deleted, and that receipt numbers are
never used twice. All names, amounts and codes are made up.
"""

import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from app.extensions import db
from app.models.payments import NEXT_RECEIPT_NUMBER_SQL

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
FOREIGN_KEY_VIOLATION = "23503"
STRING_TOO_LONG = "22001"

TABLES = ("receipt_counters", "payments", "payment_cancellations")


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


def _payment(connection, s, **overrides):
    values = {
        "school_id": s["school"],
        "bill_id": s["bill"],
        "amount_kes": 20_000,
        "method": "mpesa",
        "reference": "SJK3ABCD12",
        "paid_on": "2027-01-10",
        "paid_by": "Otieno Demo",
        "receipt_number": 1,
        "recorded_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "payments", **values)


def _cancellation(connection, s, **overrides):
    values = {
        "school_id": s["school"],
        "payment_id": s["payment"],
        "reason": "Entered twice by mistake",
        "cancelled_by_user_id": s["user"],
        **overrides,
    }
    return _insert(connection, "payment_cancellations", **values)


def _counter(connection, s, last_number=1):
    connection.execute(
        text("INSERT INTO receipt_counters (school_id, last_number) VALUES (:school, :n)"),
        {"school": s["school"], "n": last_number},
    )


def _next_number(connection, school_id) -> int:
    return connection.execute(text(NEXT_RECEIPT_NUMBER_SQL), {"school_id": school_id}).scalar_one()


@pytest.fixture
def two_schools(db_app, make_school, make_user):
    """Schools A and B, each with a 2027 year, Term 1, a Grade 4 class, two
    students, Grade 4's Term 1 structure (Tuition 15,000), both students'
    Term 1 bills, one M-Pesa payment (receipt 1) on the first student's bill
    and the school's receipt counter at 1."""
    data = {}
    for code in ("a", "b"):
        school = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        user = make_user(email=f"bursar.{code}@example.com")
        with db_app.app_context(), db.engine.begin() as connection:
            _in_school(connection, school)
            year = _insert(
                connection, "academic_years", school_id=school, name="2027",
                starts_on="2027-01-04", ends_on="2027-11-26",
            )  # fmt: skip
            term = _insert(
                connection, "terms", school_id=school, academic_year_id=year, number=1,
                starts_on="2027-01-04", ends_on="2027-04-01",
            )  # fmt: skip
            school_class = _insert(
                connection, "classes", school_id=school, academic_year_id=year,
                grade="grade_4", stream="East",
            )  # fmt: skip
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
            structure = _insert(
                connection, "fee_structures", school_id=school, academic_year_id=year,
                term_id=term, grade="grade_4", updated_by_user_id=user,
            )  # fmt: skip
            bills = [
                _insert(
                    connection,
                    "bills",
                    school_id=school,
                    academic_year_id=year,
                    term_id=term,
                    structure_id=structure,
                    class_id=school_class,
                    student_id=student,
                    issued_by_user_id=user,
                )  # fmt: skip
                for student in students
            ]
            s = {"school": school, "user": user, "bill": bills[0], "other_bill": bills[1]}
            s["payment"] = _payment(connection, s)
            _counter(connection, s)
        data[code] = s
    return data


def _expect(sqlstate, error, statement, *args, **kwargs):
    with pytest.raises(error) as excinfo:
        statement(*args, **kwargs)
    assert excinfo.value.orig.sqlstate == sqlstate


def _count(connection, table) -> int:
    return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608


# Keeping schools apart.


@pytest.mark.parametrize("table", ("receipt_counters", "payments"))
def test_only_the_current_schools_payment_rows_are_visible(db_app, two_schools, table):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        rows = connection.execute(text(f"SELECT DISTINCT school_id FROM {table}"))  # noqa: S608
        assert list(rows.scalars()) == [a["school"]]

        _in_school(connection, None)
        assert _count(connection, table) == 0


def test_only_the_current_schools_cancellations_are_visible(db_app, two_schools):
    with db_app.app_context(), db.engine.connect() as connection:
        for code in ("a", "b"):
            _in_school(connection, two_schools[code]["school"])
            _cancellation(connection, two_schools[code])
        _in_school(connection, two_schools["a"]["school"])
        rows = connection.execute(text("SELECT school_id FROM payment_cancellations"))
        assert list(rows.scalars()) == [two_schools["a"]["school"]]
        _in_school(connection, None)
        assert _count(connection, "payment_cancellations") == 0


@pytest.mark.parametrize(
    ("write", "why"),
    [
        (lambda c, b: _payment(c, b, receipt_number=2, reference="SJK3ABCD99"), "a payment"),
        (lambda c, b: _cancellation(c, b), "a cancellation"),
        (lambda c, b: _next_number(c, b["school"]), "a receipt number"),
    ],
)
def test_payment_rows_cannot_be_written_into_another_school(db_app, two_schools, write, why):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        _expect(INSUFFICIENT_PRIVILEGE, ProgrammingError, write, connection, two_schools["b"])


def test_another_schools_counter_cannot_be_changed(db_app, two_schools):
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, two_schools["a"]["school"])
        changed = connection.execute(
            text("UPDATE receipt_counters SET last_number = 99 WHERE school_id = :school"),
            {"school": two_schools["b"]["school"]},
        )
        assert changed.rowcount == 0


# Rows that must belong together.


def test_a_payment_is_for_a_bill_of_its_own_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _payment, connection, a, bill_id=b["bill"], receipt_number=2, reference="SJK3ABCD99",
        )  # fmt: skip


def test_a_cancellation_is_for_a_payment_of_its_own_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            FOREIGN_KEY_VIOLATION, IntegrityError,
            _cancellation, connection, a, payment_id=b["payment"],
        )  # fmt: skip


def test_a_bill_can_have_several_payments(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _payment(connection, a, receipt_number=2, method="cash", reference=None, amount_kes=5_000)
        _payment(connection, a, receipt_number=3, method="bank", reference="FT2027/0042")
        paid = connection.execute(
            text("SELECT sum(amount_kes) FROM payments WHERE bill_id = :bill"), {"bill": a["bill"]}
        ).scalar_one()
        assert paid == 45_000


# Amounts, methods and references.


@pytest.mark.parametrize("amount", [0, -1, 1_000_001])
def test_payments_are_1_to_1_000_000_shillings(db_app, two_schools, amount):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=2, method="cash", reference=None,
            amount_kes=amount,
        )  # fmt: skip


@pytest.mark.parametrize("amount", [1, 1_000_000])
def test_the_smallest_and_largest_payments_are_kept(db_app, two_schools, amount):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _payment(connection, a, receipt_number=2, method="cash", reference=None, amount_kes=amount)


def test_only_known_methods_are_accepted(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=2, method="card", reference=None,
        )  # fmt: skip


@pytest.mark.parametrize(
    ("method", "reference", "why"),
    [
        ("cash", "R-12", "cash has no reference"),
        ("mpesa", None, "M-Pesa needs its code"),
        ("mpesa", "sjk3abcd34", "an M-Pesa code is in capitals"),
        ("mpesa", "SJK3ABCD3", "an M-Pesa code is 10 characters, not 9"),
        ("mpesa", "SJK3ABCD345", "an M-Pesa code is 10 characters, not 11"),
        ("mpesa", "SJK3 ABCD3", "an M-Pesa code has no spaces"),
        ("mpesa", "SJK3-ABCD3", "an M-Pesa code is letters and digits only"),
        ("bank", None, "a bank payment needs a reference"),
        ("bank", " FT1", "references are never padded"),
        ("bank", "FT1 ", "references are never padded"),
        ("cheque", "\t000123", "references are never padded"),
    ],
)
def test_references_fit_the_method(db_app, two_schools, method, reference, why):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=2, method=method, reference=reference,
        )  # fmt: skip


def test_an_empty_reference_is_refused(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=2, method="bank", reference="",
        )  # fmt: skip


def test_references_are_at_most_40_characters(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _payment(connection, a, receipt_number=2, method="bank", reference="R" * 40)
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            STRING_TOO_LONG, DataError,
            _payment, connection, a, receipt_number=3, method="bank", reference="R" * 41,
        )  # fmt: skip


@pytest.mark.parametrize(
    ("method", "reference"),
    [("mpesa", "TKL9XYZW01"), ("bank", "FT 2027/0042 KCB"), ("cheque", "000123"), ("cash", None)],
)
def test_each_method_accepts_its_kind_of_reference(db_app, two_schools, method, reference):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _payment(connection, a, receipt_number=2, method=method, reference=reference)


# Never the same payment twice.


@pytest.mark.parametrize(
    ("method", "first", "second"),
    [
        ("mpesa", "SJK3ABCD12", "SJK3ABCD12"),
        ("bank", "ft2027/0042", "FT2027/0042"),
        ("cheque", "00123a", "00123A"),
    ],
)
def test_the_same_reference_is_not_recorded_twice_ignoring_case(
    db_app, two_schools, method, first, second
):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        if method != "mpesa":  # The fixture already holds SJK3ABCD12.
            _payment(connection, a, receipt_number=2, method=method, reference=first)
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=3, method=method, reference=second,
            bill_id=a["other_bill"],
        )  # fmt: skip


def test_a_reference_can_repeat_for_another_method_or_school(db_app, two_schools):
    a, b = two_schools["a"], two_schools["b"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        # A bank slip may carry the same characters as an M-Pesa code.
        _payment(connection, a, receipt_number=2, method="bank", reference="SJK3ABCD12")
    # School B already holds SJK3ABCD12 too (the fixture): schools are separate.
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, b["school"])
        assert connection.execute(text("SELECT reference FROM payments")).scalar_one() == (
            "SJK3ABCD12"
        )


def test_cash_payments_need_no_reference_and_can_be_many(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        for number in (2, 3):
            _payment(connection, a, receipt_number=number, method="cash", reference=None)


# Receipt numbers.


def test_a_receipt_number_is_used_once_in_a_school(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            UNIQUE_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=1, method="cash", reference=None,
        )  # fmt: skip


@pytest.mark.parametrize("number", [0, -5])
def test_receipt_numbers_start_at_1(db_app, two_schools, number):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=number, method="cash", reference=None,
        )  # fmt: skip


def test_the_counter_gives_1_first_then_one_more_each_time(db_app, make_school):
    school = make_school(code="new-school", name="New School")
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, school)
        assert [_next_number(connection, school) for _ in range(3)] == [1, 2, 3]


def test_a_failed_save_uses_no_receipt_number(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        assert _next_number(connection, a["school"]) == 2
        connection.rollback()  # The payment failed: the number goes back.
        _in_school(connection, a["school"])
        assert _next_number(connection, a["school"]) == 2


def test_two_payments_saved_at_once_get_one_number_each(db_app, two_schools):
    """The second save waits for the first and then takes the next number."""
    a = two_schools["a"]
    got: list[int] = []
    errors: list[BaseException] = []
    with db_app.app_context():
        first = db.engine.connect()
        _in_school(first, a["school"])
        got.append(_next_number(first, a["school"]))  # Counter row now locked.

        def second_save():
            try:
                with db_app.app_context(), db.engine.begin() as connection:
                    _in_school(connection, a["school"])
                    got.append(_next_number(connection, a["school"]))
            except BaseException as error:  # noqa: BLE001 (reported below)
                errors.append(error)

        thread = threading.Thread(target=second_save)
        thread.start()
        thread.join(timeout=1)
        assert thread.is_alive(), "the second save should wait for the first"
        first.commit()
        first.close()
        thread.join(timeout=10)
    assert not errors
    assert got == [2, 3]


def test_counters_are_per_school(db_app, two_schools):
    with db_app.app_context(), db.engine.begin() as connection:
        for code in ("a", "b"):
            _in_school(connection, two_schools[code]["school"])
            assert _next_number(connection, two_schools[code]["school"]) == 2


@pytest.mark.parametrize("number", [0, -1])
def test_a_counter_never_holds_less_than_1(db_app, two_schools, number):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            connection.execute,
            text("UPDATE receipt_counters SET last_number = :n"), {"n": number},
        )  # fmt: skip


# Payers and cancellations.


@pytest.mark.parametrize("paid_by", ["", " Otieno", "Otieno ", "\nOtieno"])
def test_payer_names_are_never_empty_or_padded(db_app, two_schools, paid_by):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            CHECK_VIOLATION, IntegrityError,
            _payment, connection, a, receipt_number=2, method="cash", reference=None,
            paid_by=paid_by,
        )  # fmt: skip


def test_payer_names_are_optional_and_at_most_100_characters(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.begin() as connection:
        _in_school(connection, a["school"])
        _payment(connection, a, receipt_number=2, method="cash", reference=None, paid_by=None)
        _payment(connection, a, receipt_number=3, method="cash", reference=None, paid_by="P" * 100)
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            STRING_TOO_LONG, DataError,
            _payment, connection, a, receipt_number=4, method="cash", reference=None,
            paid_by="P" * 101,
        )  # fmt: skip


def test_a_payment_is_cancelled_at_most_once(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _cancellation(connection, a)
        _expect(UNIQUE_VIOLATION, IntegrityError, _cancellation, connection, a, reason="Again")


@pytest.mark.parametrize("reason", ["", " Twice", "Twice ", "\tTwice"])
def test_a_cancellation_always_gives_a_reason(db_app, two_schools, reason):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(CHECK_VIOLATION, IntegrityError, _cancellation, connection, a, reason=reason)


def test_cancellation_reasons_are_at_most_200_characters(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(STRING_TOO_LONG, DataError, _cancellation, connection, a, reason="R" * 201)
        connection.rollback()
        _in_school(connection, a["school"])
        _cancellation(connection, a, reason="R" * 200)


# Never changed, deleted or emptied.


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE payments SET amount_kes = 1 WHERE id = :payment",
        "UPDATE payments SET receipt_number = 99 WHERE id = :payment",
        "DELETE FROM payments WHERE id = :payment",
        "UPDATE payment_cancellations SET reason = 'Other' WHERE payment_id = :payment",
        "DELETE FROM payment_cancellations WHERE payment_id = :payment",
        "DELETE FROM receipt_counters WHERE school_id = :school",
    ],
)
def test_payments_and_cancellations_are_never_changed_or_deleted(db_app, two_schools, statement):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _cancellation(connection, a)
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(statement), {"payment": a["payment"], "school": a["school"]})
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_a_bill_with_payments_is_still_never_deleted(db_app, two_schools):
    a = two_schools["a"]
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, a["school"])
        _expect(
            INSUFFICIENT_PRIVILEGE, ProgrammingError,
            connection.execute, text("DELETE FROM bills WHERE id = :bill"), {"bill": a["bill"]},
        )  # fmt: skip


@pytest.mark.parametrize("table", TABLES)
def test_payment_tables_cannot_be_emptied(db_app, two_schools, table):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, two_schools["a"]["school"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(text(f"TRUNCATE {table}"))
        assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE
