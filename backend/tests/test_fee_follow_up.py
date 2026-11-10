"""Pay-by dates and the list of students owing (E4).

"Today" is fixed by replacing the school's clock, so these tests mean the
same next year as now. All names, phone numbers, amounts and payment codes
are made up.
"""

import itertools
import time
import uuid
from datetime import date

import pytest
from sqlalchemy import event, select, text

from app.api.v1 import academic_years
from app.extensions import db
from app.models import AuditEvent

PASSWORD = "correct horse battery"
API = "/api/v1/school"
ARREARS = f"{API}/fees/arrears"
NOT_FOUND_ID = "00000000-0000-0000-0000-000000000000"

# 2026: Amani in Grade 3 East, one term (Tuition 10,000), no pay-by date.
YEAR_2026 = {
    "name": "2026",
    "starts_on": "2026-01-05",
    "ends_on": "2026-11-27",
    "terms": [{"number": 1, "starts_on": "2026-01-05", "ends_on": "2026-04-02"}],
}
# 2027: Amani and Chausiku in Grade 4 East, Baraka in Grade 4 West, three
# terms of 17,000 each.
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
ITEMS = [{"name": "Tuition", "amount_kes": 15_000}, {"name": "Activity", "amount_kes": 2_000}]
TODAY = date(2027, 6, 1)  # Term 2 of 2027
CODES = (f"QB{n:08d}" for n in itertools.count(1))


@pytest.fixture(autouse=True)
def today(monkeypatch):
    """The school's "today": 1 June 2027 unless a test moves it."""
    clock = {"today": TODAY}
    monkeypatch.setattr(academic_years, "school_today", lambda: clock["today"])
    return clock


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


def _grade_path(year_id, term, grade="grade_4"):
    return f"{API}/fees/years/{year_id}/terms/{term}/grades/{grade}"


def _class(admin, year_id, grade, stream, students):
    body = {"academic_year_id": year_id, "grade": grade, "stream": stream}
    class_id = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    _ok(admin.post(f"{API}/classes/{class_id}/students", json={"student_ids": students}), 201)
    return class_id


def _issue(admin, year_id, term, grade, items):
    path = _grade_path(year_id, term, grade)
    _ok(admin.put(path, json={"items": items}))
    bills = _ok(admin.post(f"{path}/issue"))["bills"]
    return {bill["student"]["full_name"].split()[0]: bill["id"] for bill in bills}


def _set_up_school(admin, code):
    students = {}
    for n, name in enumerate(("Amani", "Baraka", "Chausiku")):
        body = {"admission_number": f"{code.upper()}-{n + 1}", "full_name": f"{name} Pupil"}
        students[name] = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    y2026 = _ok(admin.post(f"{API}/academic-years", json=YEAR_2026), 201)["academic_year"]["id"]
    classes = {"3 East": _class(admin, y2026, "grade_3", "East", [students["Amani"]])}
    y2027 = _ok(admin.post(f"{API}/academic-years", json=YEAR_2027), 201)["academic_year"]["id"]
    classes["4 West"] = _class(admin, y2027, "grade_4", "West", [students["Baraka"]])
    classes["4 East"] = _class(
        admin, y2027, "grade_4", "East", [students["Amani"], students["Chausiku"]]
    )
    bills = {(2026, 1): _issue(admin, y2026, 1, "grade_3", [ITEMS[0] | {"amount_kes": 10_000}])}
    for term in (1, 2, 3):
        bills[(2027, term)] = _issue(admin, y2027, term, "grade_4", ITEMS)
    for name, phone, relationship in (
        ("Wanjiru Parent", f"+2547000{code == 'a' and '0' or '1'}0101", "mother"),
        ("Otieno Parent", f"+2547000{code == 'a' and '0' or '1'}0102", "father"),
    ):
        body = {"full_name": name, "phone": phone, "relationship": relationship}
        _ok(admin.post(f"{API}/students/{students['Amani']}/guardians", json=body), 201)
    return {
        "students": students,
        "years": {2026: y2026, 2027: y2027},
        "classes": classes,
        "bills": bills,
    }


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """Schools A and B, each with one user per role and the bills above:
    Amani 10,000 (2026 Term 1) and 17,000 in each 2027 term; Baraka and
    Chausiku 17,000 in each 2027 term. Amani's mother is the primary
    guardian; the others have no guardian recorded."""
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


def _due(client, school, term, due_on, year=2027, code="a", grade="grade_4"):
    path = _grade_path(school[code]["years"][year], term, grade)
    return client.put(f"{path}/due-date", json={"due_on": due_on})


def _pay(client, bill_id, amount, paid_on=None, method="mpesa"):
    body = {"amount_kes": amount, "method": method, "paid_on": paid_on or TODAY.isoformat()}
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


def _owing(client, **filters):
    return _ok(client.get(ARREARS, query_string=filters))


def _row(body, name):
    rows = [r for r in body["students"] if r["student"]["full_name"] == f"{name} Pupil"]
    return rows[0] if rows else None


def _events(app, action):
    with app.app_context():
        rows = db.session.execute(
            select(AuditEvent.outcome, AuditEvent.target_type).where(AuditEvent.action == action)
        )
        return [tuple(row) for row in rows]


# Pay-by dates.


def test_a_pay_by_date_shows_on_the_structure_overview_bills_and_printed_bills(db_app, school):
    admin = school["a"]["admin"]
    view = _ok(_due(admin, school, 2, "2027-05-14"))
    assert view["structure"]["due_on"] == "2027-05-14"
    overview = _ok(admin.get(f"{API}/fees/years/{school['a']['years'][2027]}/terms/2"))
    assert overview["grades"][0]["structure"]["due_on"] == "2027-05-14"
    bill = _bill(admin, _bill_id(school, 2027, 2))
    assert (bill["due_on"], bill["overdue"]) == ("2027-05-14", True)
    printed = _ok(admin.get(f"{_grade_path(school['a']['years'][2027], 2)}/bills/print"))
    assert printed["due_on"] == "2027-05-14"
    # Other terms and grades keep none.
    assert _bill(admin, _bill_id(school, 2027, 3))["due_on"] is None
    assert _bill(admin, _bill_id(school, 2027, 3))["overdue"] is False


def test_a_bill_is_overdue_only_after_its_pay_by_day_and_while_something_is_owed(
    db_app, school, today
):
    admin = school["a"]["admin"]
    bill_id = _bill_id(school, 2027, 2)
    _ok(_due(admin, school, 2, "2027-06-01"))
    assert _bill(admin, bill_id)["overdue"] is False  # the pay-by day itself
    today["today"] = date(2027, 6, 2)
    assert _bill(admin, bill_id)["overdue"] is True
    _pay(admin, bill_id, 16_999, paid_on="2027-06-02")
    assert _bill(admin, bill_id)["overdue"] is True  # 1 shilling still owed
    _pay(admin, bill_id, 1, paid_on="2027-06-02")
    assert _bill(admin, bill_id)["overdue"] is False


def test_the_pay_by_date_can_be_moved_and_removed_after_issuing_and_each_change_is_audited(
    db_app, school
):
    admin = school["a"]["admin"]
    _ok(_due(admin, school, 2, "2027-05-14"))
    _ok(_due(admin, school, 2, "2027-05-14"))  # unchanged: not audited again
    _ok(_due(admin, school, 2, "2027-06-30"))
    assert _bill(admin, _bill_id(school, 2027, 2))["overdue"] is False
    assert _ok(_due(admin, school, 2, None))["structure"]["due_on"] is None
    assert _events(db_app, "fee_structure.due_date_changed") == [("success", "fee_structure")] * 3


def test_a_pay_by_date_runs_from_90_days_before_the_term_to_its_last_day(db_app, school):
    admin = school["a"]["admin"]
    # Term 1 of 2027: 4 Jan to 1 Apr; 90 days before is 6 Oct 2026.
    assert _ok(_due(admin, school, 1, "2026-10-06"))["structure"]["due_on"] == "2026-10-06"
    assert _ok(_due(admin, school, 1, "2027-04-01"))["structure"]["due_on"] == "2027-04-01"
    for outside in ("2026-10-05", "2027-04-02"):
        error = _error(_due(admin, school, 1, outside), 422)
        assert error["code"] == "due_date_out_of_range"
        assert error["message"] == (
            "Choose a pay-by date from 6 Oct 2026 to 1 Apr 2027 (the term's last day)."
        )
    assert _bill(admin, _bill_id(school, 2027, 1))["due_on"] == "2027-04-01"


@pytest.mark.parametrize(
    "body",
    [
        {"due_on": 1_810_252_800},  # midnight 14 May 2027 in seconds: not a date
        {"due_on": "14/05/2027"},
        {"due_on": "2027-02-30"},
        {},
        {"due_on": "2027-05-14", "extra": 1},
    ],
)
def test_invalid_pay_by_dates_are_refused(db_app, school, body):
    path = f"{_grade_path(school['a']['years'][2027], 2)}/due-date"
    assert school["a"]["admin"].put(path, json=body).status_code == 422
    assert _bill(school["a"]["admin"], _bill_id(school, 2027, 2))["due_on"] is None


def test_a_pay_by_date_needs_a_saved_fee_structure(db_app, school):
    admin = school["a"]["admin"]
    body = {"academic_year_id": school["a"]["years"][2027], "grade": "grade_5", "stream": "North"}
    _ok(admin.post(f"{API}/classes", json=body), 201)
    error = _error(_due(admin, school, 2, "2027-05-14", grade="grade_5"), 409)
    assert error["message"] == "Save the fee structure before setting a pay-by date."
    assert _due(admin, school, 2, "2027-05-14", grade="grade_9").status_code == 404
    assert _events(db_app, "fee_structure.due_date_changed") == [("denied", "term")]


def test_who_may_set_a_pay_by_date(db_app, school):
    assert _due(_as(db_app, "finance_officer"), school, 2, "2027-05-14").status_code == 200
    for role in ("principal", "teacher", "registrar"):
        assert _due(_as(db_app, role), school, 2, "2027-06-14").status_code == 403, role
    # Another school's year is not found, and nothing changed there.
    other_year = school["b"]["years"][2027]
    path = f"{_grade_path(other_year, 2)}/due-date"
    assert school["a"]["admin"].put(path, json={"due_on": "2027-05-14"}).status_code == 404
    assert _bill(school["b"]["admin"], _bill_id(school, 2027, 2, code="b"))["due_on"] is None


# Students owing.


def test_each_student_owing_is_listed_with_what_they_owe_and_whom_to_call(db_app, school):
    body = _owing(_as(db_app, "finance_officer"))
    assert body["today"] == "2027-06-01"
    assert body["school"] == {"name": "School A"}
    assert [r["student"]["full_name"] for r in body["students"]] == [
        "Amani Pupil",  # 61,000: the largest first
        "Baraka Pupil",  # 51,000, then by name
        "Chausiku Pupil",
    ]
    amani = body["students"][0]
    assert amani == {
        "student": {
            "id": school["a"]["students"]["Amani"],
            "full_name": "Amani Pupil",
            "admission_number": "A-1",
        },
        "class": {
            "id": school["a"]["classes"]["4 East"],
            "name": "Grade 4 East",
            "grade": "grade_4",
            "year": {"name": "2027"},  # her latest class, not 2026's Grade 3 East
        },
        "left_school": False,
        "owed_kes": 61_000,
        "overdue_kes": 0,
        "oldest_unpaid": {"term": {"number": 1}, "year": {"name": "2026"}},
        "last_payment": None,
        "contact": {
            "full_name": "Wanjiru Parent",
            "relationship": "mother",
            "phone": "+254700000101",
        },
    }
    assert _row(body, "Baraka")["contact"] is None
    assert body["totals"] == {"students": 3, "owed_kes": 163_000, "overdue_kes": 0}
    assert body["filters"] == {
        "grades": [{"code": "grade_4", "name": "Grade 4"}],
        "classes": [
            {
                "id": school["a"]["classes"]["4 East"],
                "name": "Grade 4 East",
                "grade": "grade_4",
                "year": {"name": "2027"},
            },
            {
                "id": school["a"]["classes"]["4 West"],
                "name": "Grade 4 West",
                "grade": "grade_4",
                "year": {"name": "2027"},
            },
        ],
    }


def test_what_is_owed_is_the_final_balance_of_each_statement(db_app, school):
    admin = school["a"]["admin"]
    _adjust(admin, _bill_id(school, 2026, 1), -2_500, "Bursary")
    kept = _pay(admin, _bill_id(school, 2027, 1), 9_000)
    gone = _pay(admin, _bill_id(school, 2027, 2), 4_000, method="cash")
    _cancel(admin, gone["id"])
    _pay(admin, _bill_id(school, 2027, 1, "Chausiku"), 20_000)  # 3,000 credit on Term 1
    _adjust(admin, _bill_id(school, 2027, 3, "Baraka"), 1_200, "Replaced textbook")
    assert kept["receipt_number"] == 1

    body = _owing(admin)
    for name in ("Amani", "Baraka", "Chausiku"):
        student_id = school["a"]["students"][name]
        statement = _ok(admin.get(f"{API}/fees/students/{student_id}/statement"))
        assert _row(body, name)["owed_kes"] == statement["totals"]["balance_kes"], name
    assert _row(body, "Amani")["owed_kes"] == 10_000 - 2_500 + 51_000 - 9_000
    assert _row(body, "Chausiku")["owed_kes"] == 51_000 - 20_000


def test_a_student_whose_credit_covers_everything_is_not_listed(db_app, school):
    admin = school["a"]["admin"]
    _pay(admin, _bill_id(school, 2027, 3, "Baraka"), 51_500)  # all three terms and 500 more
    assert _row(_owing(admin), "Baraka") is None
    _pay(admin, _bill_id(school, 2027, 1, "Chausiku"), 50_999)
    assert _row(_owing(admin), "Chausiku")["owed_kes"] == 1


def test_overdue_counts_bills_past_their_pay_by_date_but_never_more_than_is_owed(
    db_app, school, today
):
    admin = school["a"]["admin"]
    _ok(_due(admin, school, 1, "2027-01-15"))
    _ok(_due(admin, school, 2, "2027-05-31"))
    _ok(_due(admin, school, 3, "2027-09-01"))
    # Chausiku's 20,000 credit on Term 3 lowers what the family owes below
    # what is past due.
    _pay(admin, _bill_id(school, 2027, 3, "Chausiku"), 37_000)
    body = _owing(admin)
    amani, chausiku = _row(body, "Amani"), _row(body, "Chausiku")
    # Amani's 2026 bill has no pay-by date, so it is owed but not overdue.
    assert (amani["owed_kes"], amani["overdue_kes"]) == (61_000, 34_000)
    assert (chausiku["owed_kes"], chausiku["overdue_kes"]) == (14_000, 14_000)
    assert body["totals"]["overdue_kes"] == 34_000 + 34_000 + 14_000

    today["today"] = date(2027, 5, 31)  # Term 2's pay-by day: not late yet
    assert _row(_owing(admin), "Amani")["overdue_kes"] == 17_000


def test_the_oldest_unpaid_term_and_the_last_payment(db_app, school):
    admin = school["a"]["admin"]
    _pay(admin, _bill_id(school, 2026, 1), 10_000, paid_on="2027-01-10")
    _pay(admin, _bill_id(school, 2027, 2), 500, paid_on="2027-05-20", method="cash")
    _pay(admin, _bill_id(school, 2027, 1), 700, paid_on="2027-05-20", method="cash")
    later = _pay(admin, _bill_id(school, 2027, 1), 9_999, paid_on="2027-05-30")
    _cancel(admin, later["id"])
    # Recorded last, but paid earlier (a late entry): not the last payment.
    _pay(admin, _bill_id(school, 2027, 1), 300, paid_on="2027-02-01")
    amani = _row(_owing(admin), "Amani")
    assert amani["oldest_unpaid"] == {"term": {"number": 1}, "year": {"name": "2027"}}
    # The latest payment that stands; on the same day, the later receipt.
    assert amani["last_payment"] == {"paid_on": "2027-05-20", "amount_kes": 700, "method": "cash"}


def test_a_student_who_left_stays_listed_while_they_owe(db_app, school):
    admin = school["a"]["admin"]
    _ok(admin.post(f"{API}/students/{school['a']['students']['Baraka']}/deactivate"))
    baraka = _row(_owing(admin), "Baraka")
    assert baraka["left_school"] is True
    assert baraka["class"]["name"] == "Grade 4 West"
    assert baraka["owed_kes"] == 51_000


def test_the_list_can_be_filtered(db_app, school):
    admin = school["a"]["admin"]
    _ok(_due(admin, school, 1, "2027-01-15"))
    _pay(admin, _bill_id(school, 2027, 1, "Baraka"), 17_000)
    _pay(admin, _bill_id(school, 2027, 2, "Chausiku"), 10_000)
    classes = school["a"]["classes"]

    def names(**filters):
        body = _owing(admin, **filters)
        assert body["totals"]["students"] == len(body["students"])
        assert body["totals"]["owed_kes"] == sum(r["owed_kes"] for r in body["students"])
        return [r["student"]["full_name"].split()[0] for r in body["students"]]

    assert names(class_id=classes["4 East"]) == ["Amani", "Chausiku"]
    assert names(class_id=classes["4 West"]) == ["Baraka"]
    assert names(grade="grade_4") == ["Amani", "Chausiku", "Baraka"]  # 61,000, 41,000, 34,000
    assert names(grade="grade_3") == []  # Amani is in Grade 4 now
    assert names(overdue="true") == ["Amani", "Chausiku"]
    assert names(min_kes=41_000) == ["Amani", "Chausiku"]
    assert names(min_kes=41_001) == ["Amani"]
    assert names(class_id=classes["4 East"], overdue="true", min_kes=50_000) == ["Amani"]
    # The class choices stay those of everyone owing.
    assert len(_owing(admin, grade="grade_3")["filters"]["classes"]) == 2


@pytest.mark.parametrize(
    "query",
    [
        "grade=grade_99",
        "class_id=not-a-uuid",
        "overdue=perhaps",
        "min_kes=0",
        "min_kes=ten",
        "colour=red",
        "grade=grade_4&grade=grade_3",
    ],
)
def test_invalid_filters_are_refused(db_app, school, query):
    assert school["a"]["admin"].get(f"{ARREARS}?{query}").status_code == 422


def test_an_unknown_class_lists_nobody(db_app, school):
    assert _owing(school["a"]["admin"], class_id=NOT_FOUND_ID)["students"] == []
    other = school["b"]["classes"]["4 East"]
    assert _owing(school["a"]["admin"], class_id=other)["students"] == []


def test_who_may_see_the_list(db_app, school):
    for role in ("principal", "finance_officer"):
        assert len(_owing(_as(db_app, role))["students"]) == 3, role
    for role in ("teacher", "registrar"):
        assert _as(db_app, role).get(ARREARS).status_code == 403, role
    assert db_app.test_client().get(ARREARS).status_code == 401


def test_each_school_sees_only_its_own_students(db_app, school):
    _pay(school["b"]["admin"], _bill_id(school, 2027, 1, code="b"), 17_000)
    a = _owing(school["a"]["admin"])
    b = _owing(school["b"]["admin"])
    assert {r["student"]["admission_number"] for r in a["students"]} == {"A-1", "A-2", "A-3"}
    assert {r["student"]["admission_number"] for r in b["students"]} == {"B-1", "B-2", "B-3"}
    assert (a["totals"]["owed_kes"], b["totals"]["owed_kes"]) == (163_000, 146_000)
    assert _row(b, "Amani")["contact"]["phone"] == "+254700010101"


def test_nobody_owing_gives_an_empty_list(db_app, make_user, make_school, add_member):
    school_id = make_school(code="school-c", name="School C")
    add_member(make_user(email="school_admin.c@example.com"), school_id, "school_admin")
    body = _owing(_as(db_app, "school_admin", "c"))
    assert body["students"] == []
    assert body["totals"] == {"students": 0, "owed_kes": 0, "overdue_kes": 0}
    assert body["filters"] == {"grades": [], "classes": []}


def test_logs_carry_counts_never_names_or_amounts(db_app, school, caplog):
    caplog.set_level("INFO")
    _owing(school["a"]["admin"])
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Students owing listed: students=3" in logged
    for private in ("Amani", "Wanjiru", "+2547", "61000", "61,000"):
        assert private not in logged


# How it scales.


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


def test_the_list_takes_the_same_few_queries_however_many_students(db_app, school):
    client = _as(db_app, "finance_officer")
    three = _queries(db_app, lambda: _owing(client))
    admin = school["a"]["admin"]
    new = []
    for n in range(4):
        body = {"admission_number": f"A-{10 + n}", "full_name": f"Extra {n} Pupil"}
        new.append(_ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"])
    _ok(
        admin.post(
            f"{API}/classes/{school['a']['classes']['4 West']}/students", json={"student_ids": new}
        ),
        201,
    )
    _ok(admin.post(f"{_grade_path(school['a']['years'][2027], 3)}/issue"))
    assert len(_owing(client)["students"]) == 7
    assert _queries(db_app, lambda: _owing(client)) == three


def _bulk_school(engine, school_id, user_id, students):
    """Students in one class in each of 2029 and 2030, billed in all six
    terms with two lines and one payment each, inserted directly as the
    schema owner; every pay-by date has passed by December 2030."""

    def run(c, sql, **values):
        c.execute(text(sql), values)

    with engine.begin() as c:
        run(
            c,
            "INSERT INTO students (id, school_id, admission_number, full_name)"
            " SELECT gen_random_uuid(), :s, 'BULK-' || n, 'Bulk Pupil ' || n"
            " FROM generate_series(1, :n) AS n",
            s=school_id,
            n=students,
        )
        receipt = 0
        for calendar_year, grade in ((2029, "grade_8"), (2030, "grade_9")):
            year = uuid.uuid4()
            run(
                c,
                "INSERT INTO academic_years (id, school_id, name, starts_on, ends_on)"
                " VALUES (:id, :s, :name, make_date(:cy, 1, 7), make_date(:cy, 12, 20))",
                id=year,
                s=school_id,
                name=str(calendar_year),
                cy=calendar_year,
            )
            run(
                c,
                "INSERT INTO classes (id, school_id, academic_year_id, grade, stream)"
                " VALUES (gen_random_uuid(), :s, :y, :g, 'Bulk')",
                s=school_id,
                y=year,
                g=grade,
            )
            run(
                c,
                "INSERT INTO enrolments (id, school_id, academic_year_id, class_id, student_id)"
                " SELECT gen_random_uuid(), :s, :y, c.id, st.id FROM students st, classes c"
                " WHERE st.school_id = :s AND c.academic_year_id = :y",
                s=school_id,
                y=year,
            )
            for number in (1, 2, 3):
                term, structure = uuid.uuid4(), uuid.uuid4()
                month = 4 * number - 3
                values = {"s": school_id, "y": year, "u": user_id, "cy": calendar_year}
                run(
                    c,
                    "INSERT INTO terms (id, school_id, academic_year_id, number, starts_on,"
                    " ends_on) VALUES (:t, :s, :y, :n, make_date(:cy, :m, 1),"
                    " make_date(:cy, :m, 25))",
                    t=term,
                    n=number,
                    m=month,
                    **values,
                )
                run(
                    c,
                    "INSERT INTO fee_structures (id, school_id, academic_year_id, term_id, grade,"
                    " updated_by_user_id, issued_at, issued_by_user_id, due_on)"
                    " VALUES (:f, :s, :y, :t, :g, :u, now(), :u, make_date(:cy, :m, 5))",
                    f=structure,
                    t=term,
                    g=grade,
                    m=month,
                    **values,
                )
                run(
                    c,
                    "INSERT INTO bills (id, school_id, academic_year_id, term_id, structure_id,"
                    " class_id, student_id, issued_by_user_id)"
                    " SELECT gen_random_uuid(), :s, :y, :t, :f, e.class_id, e.student_id, :u"
                    " FROM enrolments e WHERE e.academic_year_id = :y",
                    t=term,
                    f=structure,
                    **values,
                )
                for amount, name in ((15_000, "Tuition"), (2_000, "Activity")):
                    run(
                        c,
                        "INSERT INTO bill_lines (id, school_id, bill_id, structure_id, kind,"
                        " description, amount_kes, created_by_user_id)"
                        " SELECT gen_random_uuid(), :s, b.id, :f, 'adjustment', :d, :a, :u"
                        " FROM bills b WHERE b.term_id = :t",
                        s=school_id,
                        f=structure,
                        t=term,
                        d=name,
                        a=amount,
                        u=user_id,
                    )
                run(
                    c,
                    "INSERT INTO payments (id, school_id, bill_id, amount_kes, method, paid_on,"
                    " receipt_number, recorded_by_user_id)"
                    " SELECT gen_random_uuid(), :s, b.id, 5000, 'cash', make_date(:cy, :m, 10),"
                    " :r + row_number() OVER (ORDER BY b.id), :u FROM bills b"
                    " WHERE b.term_id = :t",
                    s=school_id,
                    cy=calendar_year,
                    m=month,
                    r=receipt,
                    u=user_id,
                    t=term,
                )
                receipt += students
        run(
            c,
            "INSERT INTO receipt_counters (school_id, last_number) VALUES (:s, :r)",
            s=school_id,
            r=receipt,
        )


def test_a_large_school_is_listed_quickly(
    db_app, make_user, make_school, add_member, schema_owner_engine, today
):
    """1,500 students with 6 terms of bills each (9,000 bills), listed before
    PostgreSQL has statistics on the new rows (the worst case, just after a
    large issue): about a tenth of a second here, where one joined query
    took over 15 s; the limit allows for slower CI machines."""
    school_id = make_school(code="school-big", name="Big School")
    user = make_user(email="school_admin.big@example.com")
    add_member(user, school_id, "school_admin")
    # Statistics from the nearly empty tables, then the new rows.
    with schema_owner_engine.begin() as connection:
        connection.execute(text("ANALYZE"))
    _bulk_school(schema_owner_engine, school_id, user, students=1_500)
    today["today"] = date(2030, 12, 1)
    client = _as(db_app, "school_admin", "big")

    started = time.perf_counter()
    body = _owing(client, overdue="true")
    took = time.perf_counter() - started
    assert body["totals"] == {
        "students": 1_500,
        "owed_kes": 1_500 * 6 * 12_000,
        "overdue_kes": 1_500 * 6 * 12_000,
    }
    assert took < 2, f"took {took:.2f} s"
