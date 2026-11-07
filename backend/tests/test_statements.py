"""Balances from earlier terms, fee statements and printable bills (E3).
All names, amounts and payment codes are made up."""

import itertools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event

from app.extensions import db

PASSWORD = "correct horse battery"
API = "/api/v1/school"
NOT_FOUND_ID = "00000000-0000-0000-0000-000000000000"

# 2026: Amani in Grade 3 East, one term (Tuition 10,000).
YEAR_2026 = {
    "name": "2026",
    "starts_on": "2026-01-05",
    "ends_on": "2026-11-27",
    "terms": [{"number": 1, "starts_on": "2026-01-05", "ends_on": "2026-04-02"}],
}
# 2027: Amani and Chausiku in Grade 4 East, Baraka in Grade 4 West, three
# terms of 17,000 each (Tuition 15,000, Activity 2,000; Boarding optional).
YEAR_2027 = {
    "name": "2027",
    "starts_on": "2027-01-04",
    "ends_on": "2027-11-26",
    "terms": [
        {"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"},
        {"number": 2, "starts_on": "2027-05-03", "ends_on": "2027-08-05"},
        {"number": 3, "starts_on": "2027-08-30", "ends_on": "2027-11-19"},
    ],
}
ITEMS = [
    {"name": "Tuition", "amount_kes": 15_000},
    {"name": "Activity", "amount_kes": 2_000},
    {"name": "Boarding", "amount_kes": 30_000, "is_optional": True},
]
CODES = (f"QA{n:08d}" for n in itertools.count(1))


def _today() -> str:
    """The real Kenyan date: payments may not be dated in the future."""
    return datetime.now(ZoneInfo("Africa/Nairobi")).date().isoformat()


def _days_ago(days: int) -> str:
    return (datetime.now(ZoneInfo("Africa/Nairobi")).date() - timedelta(days=days)).isoformat()


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _ok(response, status=200):
    assert response.status_code == status, response.get_json()
    return response.get_json()


def _error(response, status):
    assert response.status_code == status, response.get_json()
    return response.get_json()["error"]


def _as(app, role, school="a"):
    return _client_for(app, f"{role}.{school}@example.com")


def _class(admin, year_id, grade, stream, students):
    body = {"academic_year_id": year_id, "grade": grade, "stream": stream}
    class_id = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    _ok(admin.post(f"{API}/classes/{class_id}/students", json={"student_ids": students}), 201)


def _issue(admin, year_id, term, grade, items):
    path = f"{API}/fees/years/{year_id}/terms/{term}/grades/{grade}"
    _ok(admin.put(path, json={"items": items}))
    bills = _ok(admin.post(f"{path}/issue"))["bills"]
    return {bill["student"]["full_name"].split()[0]: bill["id"] for bill in bills}


def _set_up_school(admin, code):
    students = {}
    for n, name in enumerate(("Amani", "Baraka", "Chausiku")):
        body = {"admission_number": f"{code.upper()}-{n + 1}", "full_name": f"{name} Pupil"}
        students[name] = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    y2026 = _ok(admin.post(f"{API}/academic-years", json=YEAR_2026), 201)["academic_year"]["id"]
    _class(admin, y2026, "grade_3", "East", [students["Amani"]])
    y2027 = _ok(admin.post(f"{API}/academic-years", json=YEAR_2027), 201)["academic_year"]["id"]
    _class(admin, y2027, "grade_4", "West", [students["Baraka"]])
    _class(admin, y2027, "grade_4", "East", [students["Amani"], students["Chausiku"]])
    bills = {(2026, 1): _issue(admin, y2026, 1, "grade_3", [ITEMS[0] | {"amount_kes": 10_000}])}
    for term in (1, 2, 3):
        bills[(2027, term)] = _issue(admin, y2027, term, "grade_4", ITEMS)
    return {"students": students, "years": {2026: y2026, 2027: y2027}, "bills": bills}


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """Schools A and B, each with one user per role and the bills above:
    Amani 10,000 (2026 Term 1) and 17,000 in each 2027 term; Baraka and
    Chausiku 17,000 in each 2027 term."""
    made = {}
    for code in ("a", "b"):
        school_id = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        for role in ("school_admin", "principal", "finance_officer", "registrar", "teacher"):
            add_member(make_user(email=f"{role}.{code}@example.com"), school_id, role)
        admin = _as(db_app, "school_admin", code)
        made[code] = {"admin": admin, **_set_up_school(admin, code)}
    return made


def _bill_id(school, year, term, name="Amani", code="a"):
    return school[code]["bills"][(year, term)][name]


def _pay(client, bill_id, amount, paid_on=None, method="mpesa"):
    body = {"amount_kes": amount, "method": method, "paid_on": paid_on or _today()}
    if method == "mpesa":
        body["reference"] = next(CODES)
    return _ok(client.post(f"{API}/fees/bills/{bill_id}/payments", json=body), 201)["payment"]


def _cancel(client, payment_id, reason="Entered twice by mistake"):
    _ok(client.post(f"{API}/fees/payments/{payment_id}/cancellation", json={"reason": reason}), 201)


def _adjust(client, bill_id, amount, reason):
    body = {"amount_kes": amount, "reason": reason}
    _ok(client.post(f"{API}/fees/bills/{bill_id}/adjustments", json=body), 201)


def _bill(client, bill_id):
    return _ok(client.get(f"{API}/fees/bills/{bill_id}"))


def _statement(client, student_id):
    return _ok(client.get(f"{API}/fees/students/{student_id}/statement"))


def _print_path(school, term=2, grade="grade_4", code="a", year=2027):
    year_id = school[code]["years"][year]
    return f"{API}/fees/years/{year_id}/terms/{term}/grades/{grade}/bills/print"


# Who may see what.


@pytest.mark.parametrize("role", ["teacher", "registrar"])
def test_teachers_and_registrars_see_no_statements_or_printable_bills(db_app, school, role):
    client = _as(db_app, role)
    student = school["a"]["students"]["Amani"]
    assert _error(client.get(f"{API}/fees/students/{student}/statement"), 403)
    assert _error(client.get(_print_path(school)), 403)


@pytest.mark.parametrize("role", ["school_admin", "principal", "finance_officer"])
def test_fee_readers_see_statements_and_printable_bills(db_app, school, role):
    client = _as(db_app, role)
    assert _statement(client, school["a"]["students"]["Amani"])["entries"]
    assert len(_ok(client.get(_print_path(school)))["bills"]) == 3


def test_another_schools_students_and_terms_are_not_found(db_app, school):
    client = _as(db_app, "finance_officer")
    other_student = school["b"]["students"]["Amani"]
    error = _error(client.get(f"{API}/fees/students/{other_student}/statement"), 404)
    assert error["message"] == "Student not found."
    assert _error(client.get(f"{API}/fees/students/{NOT_FOUND_ID}/statement"), 404)
    assert _error(client.get(_print_path(school, code="b")), 404)


def test_a_grade_with_no_classes_that_year_has_no_printable_bills(db_app, school):
    client = _as(db_app, "finance_officer")
    error = _error(client.get(_print_path(school, grade="grade_9")), 404)
    assert error["message"] == "There are no classes of this grade in this school year."
    assert _error(client.get(_print_path(school, grade="form_9")), 404)


# The balance from earlier terms on a bill.


def test_a_bill_shows_the_balance_from_earlier_terms_and_the_amount_due_now(db_app, school):
    client = _as(db_app, "finance_officer")
    term2 = _bill(client, _bill_id(school, 2027, 2))
    assert term2["balance_kes"] == 17_000
    # 2026 Term 1 (another grade and class) and 2027 Term 1; not Term 3.
    assert term2["earlier"] == {
        "balance_kes": 27_000,
        "bills": [
            {
                "id": _bill_id(school, 2026, 1),
                "term": {"number": 1},
                "year": {"name": "2026"},
                "balance_kes": 10_000,
            },
            {
                "id": _bill_id(school, 2027, 1),
                "term": {"number": 1},
                "year": {"name": "2027"},
                "balance_kes": 17_000,
            },
        ],
    }
    assert term2["due_now_kes"] == 44_000
    assert term2["school"] == {"name": "School A"}


def test_the_first_bill_has_nothing_from_earlier_terms(db_app, school):
    client = _as(db_app, "finance_officer")
    first = _bill(client, _bill_id(school, 2026, 1))
    assert first["earlier"] == {"balance_kes": 0, "bills": []}
    assert first["due_now_kes"] == first["balance_kes"] == 10_000
    # Baraka's first bill is 2027 Term 1: Amani's bills are not his.
    baraka = _bill(client, _bill_id(school, 2027, 1, "Baraka"))
    assert baraka["earlier"] == {"balance_kes": 0, "bills": []}


def test_later_terms_are_never_counted(db_app, school):
    client = _as(db_app, "finance_officer")
    term1 = _bill(client, _bill_id(school, 2027, 1))
    assert term1["earlier"]["balance_kes"] == 10_000
    assert [b["year"]["name"] for b in term1["earlier"]["bills"]] == ["2026"]
    term3 = _bill(client, _bill_id(school, 2027, 3))
    assert term3["earlier"]["balance_kes"] == 10_000 + 17_000 + 17_000


def test_a_payment_or_cancellation_on_an_old_bill_shows_at_once(db_app, school):
    client = _as(db_app, "school_admin")
    old, new = _bill_id(school, 2027, 1), _bill_id(school, 2027, 2)
    payment = _pay(client, old, 7_000)
    assert _bill(client, new)["earlier"]["balance_kes"] == 27_000 - 7_000
    assert _bill(client, new)["due_now_kes"] == 17_000 + 20_000
    _cancel(client, payment["id"])
    assert _bill(client, new)["earlier"]["balance_kes"] == 27_000


def test_settled_earlier_bills_are_not_listed_and_a_credit_lowers_the_amount_due(db_app, school):
    client = _as(db_app, "finance_officer")
    _pay(client, _bill_id(school, 2026, 1), 10_000)  # settled
    _pay(client, _bill_id(school, 2027, 1), 22_000)  # 5,000 overpaid
    term2 = _bill(client, _bill_id(school, 2027, 2))
    assert term2["earlier"]["balance_kes"] == -5_000
    assert [(b["year"]["name"], b["balance_kes"]) for b in term2["earlier"]["bills"]] == [
        ("2027", -5_000)
    ]
    assert term2["due_now_kes"] == 12_000


def test_adjustments_on_earlier_bills_count(db_app, school):
    client = _as(db_app, "finance_officer")
    _adjust(client, _bill_id(school, 2026, 1), -4_000, "Bursary")
    assert _bill(client, _bill_id(school, 2027, 2))["earlier"]["balance_kes"] == 6_000 + 17_000


def test_payments_and_changes_also_answer_with_the_earlier_balance(db_app, school):
    client = _as(db_app, "school_admin")
    bill = _bill_id(school, 2027, 2)
    response = client.post(
        f"{API}/fees/bills/{bill}/payments",
        json={"amount_kes": 2_000, "method": "cash", "paid_on": _today()},
    )
    assert _ok(response, 201)["bill"]["due_now_kes"] == 44_000 - 2_000
    body = {"amount_kes": 1_000, "reason": "Trip"}
    assert (
        _ok(client.post(f"{API}/fees/bills/{bill}/adjustments", json=body), 201)["due_now_kes"]
        == 44_000 - 2_000 + 1_000
    )


def test_another_schools_bills_never_count(db_app, school):
    other = school["b"]["admin"]
    _pay(other, _bill_id(school, 2027, 1, code="b"), 17_000)
    client = _as(db_app, "finance_officer")
    assert _bill(client, _bill_id(school, 2027, 2))["earlier"]["balance_kes"] == 27_000


# Statements.


def _rows(statement):
    return [
        (e["kind"], e["description"], e["debit_kes"], e["credit_kes"], e["balance_kes"])
        for e in statement["entries"]
    ]


def test_a_statement_lists_charges_payments_and_cancellations_with_a_running_balance(
    db_app, school
):
    client = _as(db_app, "school_admin")
    t1 = _bill_id(school, 2027, 1)
    _adjust(client, t1, -3_000, "Bursary")
    first = _pay(client, t1, 5_000)
    second = _pay(client, t1, 500, method="cash")
    _cancel(client, second["id"], "Typed twice")

    statement = _statement(client, school["a"]["students"]["Amani"])
    assert _rows(statement) == [
        ("fee", "Tuition", 10_000, None, 10_000),
        ("fee", "Tuition", 15_000, None, 25_000),
        ("fee", "Activity", 2_000, None, 27_000),
        ("fee", "Tuition", 15_000, None, 42_000),
        ("fee", "Activity", 2_000, None, 44_000),
        ("fee", "Tuition", 15_000, None, 59_000),
        ("fee", "Activity", 2_000, None, 61_000),
        ("adjustment", "Bursary", None, 3_000, 58_000),
        ("payment", "Payment", None, 5_000, 53_000),
        ("payment", "Payment", None, 500, 52_500),
        ("cancellation", "Typed twice", 500, None, 53_000),
    ]
    assert statement["totals"] == {"charged_kes": 58_000, "paid_kes": 5_000, "balance_kes": 53_000}
    assert [(e["year"]["name"], e["term"]["number"]) for e in statement["entries"][:4]] == [
        ("2026", 1),
        ("2027", 1),
        ("2027", 1),
        ("2027", 2),
    ]
    payment, cancellation = statement["entries"][9], statement["entries"][10]
    assert (
        payment["payment"]
        == cancellation["payment"]
        == {
            "id": second["id"],
            "receipt_number": second["receipt_number"],
            "method": "cash",
            "reference": None,
        }
    )
    assert statement["entries"][8]["payment"]["reference"] == first["reference"]
    assert statement["entries"][8]["bill_id"] == t1
    assert {e["date"] for e in statement["entries"]} == {_today()}


def test_the_statement_ends_at_the_bills_added_together(db_app, school):
    client = _as(db_app, "finance_officer")
    _pay(client, _bill_id(school, 2026, 1), 12_000)
    _pay(client, _bill_id(school, 2027, 3), 1_000)
    statement = _statement(client, school["a"]["students"]["Amani"])
    term3 = _bill(client, _bill_id(school, 2027, 3))
    owed = term3["balance_kes"] + term3["earlier"]["balance_kes"]
    assert statement["entries"][-1]["balance_kes"] == statement["totals"]["balance_kes"] == owed
    assert owed == 10_000 + 3 * 17_000 - 13_000


def test_entries_follow_the_date_a_payment_was_made(db_app, school):
    client = _as(db_app, "finance_officer")
    _pay(client, _bill_id(school, 2027, 1, "Baraka"), 4_000, paid_on=_days_ago(30))
    statement = _statement(client, school["a"]["students"]["Baraka"])
    assert [e["kind"] for e in statement["entries"]][:2] == ["payment", "fee"]
    assert statement["entries"][0]["date"] == _days_ago(30)
    assert statement["entries"][0]["balance_kes"] == -4_000
    assert statement["entries"][-1]["balance_kes"] == 3 * 17_000 - 4_000


def test_a_statement_heading_names_the_school_student_and_latest_class_only(db_app, school):
    client = _as(db_app, "principal")
    statement = _statement(client, school["a"]["students"]["Amani"])
    assert statement["school"] == {"name": "School A"}
    assert statement["student"] == {
        "id": school["a"]["students"]["Amani"],
        "full_name": "Amani Pupil",
        "admission_number": "A-1",
    }
    assert statement["class_name"] == "Grade 4 East"
    assert statement["printed_on"] == _today()
    # No guardian contacts on paper.
    assert set(statement) == {"school", "student", "class_name", "printed_on", "entries", "totals"}


def test_a_student_with_no_bills_has_an_empty_statement(db_app, school):
    admin = school["a"]["admin"]
    body = {"admission_number": "A-9", "full_name": "Dalila Pupil"}
    student = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    statement = _statement(_as(db_app, "finance_officer"), student)
    assert statement["entries"] == []
    assert statement["class_name"] is None
    assert statement["totals"] == {"charged_kes": 0, "paid_kes": 0, "balance_kes": 0}


# Printable bills for a grade.


def test_a_grades_bills_print_class_by_class_with_everything_owed(db_app, school):
    client = _as(db_app, "finance_officer")
    _pay(client, _bill_id(school, 2027, 1, "Baraka"), 20_000)  # 3,000 credit
    _pay(client, _bill_id(school, 2027, 2, "Chausiku"), 1_000)
    printed = _ok(client.get(_print_path(school)))
    assert printed["school"] == {"name": "School A"}
    assert printed["term"]["number"] == 2 and printed["year"]["name"] == "2027"
    assert printed["grade"] == {"code": "grade_4", "name": "Grade 4"}
    summary = [
        (
            b["class_name"],
            b["student"]["full_name"],
            b["total_kes"],
            b["paid_kes"],
            b["balance_kes"],
            b["earlier"]["balance_kes"],
            b["due_now_kes"],
        )
        for b in printed["bills"]
    ]
    assert summary == [
        # Class by class (East before West), then by name.
        ("Grade 4 East", "Amani Pupil", 17_000, 0, 17_000, 27_000, 44_000),
        ("Grade 4 East", "Chausiku Pupil", 17_000, 1_000, 16_000, 17_000, 33_000),
        ("Grade 4 West", "Baraka Pupil", 17_000, 0, 17_000, -3_000, 14_000),
    ]
    assert printed["bills"][0]["lines"] == [
        {"kind": "fee", "description": "Tuition", "amount_kes": 15_000},
        {"kind": "fee", "description": "Activity", "amount_kes": 2_000},
    ]
    assert printed["bills"][0]["id"] == _bill_id(school, 2027, 2)


def test_printable_bills_match_each_bill(db_app, school):
    client = _as(db_app, "school_admin")
    bill = _bill_id(school, 2027, 2, "Chausiku")
    client.post(
        f"{API}/fees/bills/{bill}/adjustments", json={"amount_kes": -500, "reason": "Sibling"}
    )
    printed = {b["id"]: b for b in _ok(client.get(_print_path(school)))["bills"]}
    for bill_id, row in printed.items():
        single = _bill(client, bill_id)
        for key in ("total_kes", "paid_kes", "balance_kes", "earlier", "due_now_kes"):
            assert row[key] == single[key], key
        assert row["lines"] == [
            {k: line[k] for k in ("kind", "description", "amount_kes")} for line in single["lines"]
        ]


def test_a_term_without_a_fee_structure_has_nothing_to_print(db_app, school):
    admin = school["a"]["admin"]
    year = _ok(
        admin.post(
            f"{API}/academic-years",
            json={
                "name": "2028",
                "starts_on": "2028-01-03",
                "ends_on": "2028-11-24",
                "terms": [{"number": 1, "starts_on": "2028-01-03", "ends_on": "2028-03-30"}],
            },
        ),
        201,
    )["academic_year"]["id"]
    body = {"academic_year_id": year, "grade": "grade_5", "stream": "East"}
    _ok(admin.post(f"{API}/classes", json=body), 201)
    path = f"{API}/fees/years/{year}/terms/1/grades/grade_5/bills/print"
    assert _ok(admin.get(path))["bills"] == []


def _queries(app, call) -> int:
    with app.app_context():
        engine = db.engine
    count = [0]

    def counted(*args):
        count[0] += 1

    event.listen(engine, "before_cursor_execute", counted)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", counted)
    return count[0]


def test_printing_a_grade_takes_the_same_few_queries_however_many_bills(db_app, school):
    client = _as(db_app, "finance_officer")
    term1 = _queries(db_app, lambda: _ok(client.get(_print_path(school, term=1))))
    # Three more students in Grade 4 East, billed in Term 2.
    admin = school["a"]["admin"]
    classes = _ok(
        admin.get(f"{API}/classes", query_string={"academic_year_id": school["a"]["years"][2027]})
    )
    east = next(c["id"] for c in classes["classes"] if c["name"] == "Grade 4 East")
    new = []
    for n in range(3):
        body = {"admission_number": f"A-{10 + n}", "full_name": f"Extra {n} Pupil"}
        new.append(_ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"])
    _ok(admin.post(f"{API}/classes/{east}/students", json={"student_ids": new}), 201)
    year = school["a"]["years"][2027]
    _ok(admin.post(f"{API}/fees/years/{year}/terms/2/grades/grade_4/issue"))
    term2 = _queries(db_app, lambda: _ok(client.get(_print_path(school, term=2))))
    assert len(_ok(client.get(_print_path(school, term=2)))["bills"]) == 6
    assert term2 == term1
