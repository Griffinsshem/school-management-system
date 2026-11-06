"""Fee payments, receipts and cancellations (E2). All names, amounts, phone
numbers and payment codes are made up."""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.api.v1 import academic_years as years_api
from app.extensions import db
from app.models import AuditEvent

PASSWORD = "correct horse battery"
API = "/api/v1/school"
TODAY = "2027-02-10"  # In Term 1: the "today" the date checks use.
YEAR = {
    "name": "2027",
    "starts_on": "2027-01-04",
    "ends_on": "2027-11-26",
    "terms": [{"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"}],
}
ITEMS = [
    {"name": "Tuition", "amount_kes": 15_000},
    {"name": "Activity", "amount_kes": 2_000},
    {"name": "Boarding", "amount_kes": 30_000, "is_optional": True},
]
NOT_FOUND_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(years_api, "school_today", lambda: date.fromisoformat(TODAY))


def _recorded_today() -> str:
    """The real Kenyan date: payments are stamped with the database's clock,
    which the fixed "today" above does not change."""
    return datetime.now(ZoneInfo("Africa/Nairobi")).date().isoformat()


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


def _events(app, action):
    with app.app_context():
        rows = db.session.execute(
            select(AuditEvent.outcome, AuditEvent.target_type, AuditEvent.target_id).where(
                AuditEvent.action == action
            )
        )
        return [(outcome, target_type, str(target_id)) for outcome, target_type, target_id in rows]


def _as(app, role, school="a"):
    return _client_for(app, f"{role}.{school}@example.com")


def _set_up_school(app, admin, code):
    """A 2027 year, Grade 4 East with Amani and Baraka, Grade 4's Term 1
    structure (Tuition 15,000, Activity 2,000; Boarding optional) and the
    two bills (17,000 each). Returns the bills by first name."""
    year = _ok(admin.post(f"{API}/academic-years", json=YEAR), 201)["academic_year"]
    body = {"academic_year_id": year["id"], "grade": "grade_4", "stream": "East"}
    class_id = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    for n, name in enumerate(("Amani", "Baraka")):
        body = {"admission_number": f"{code.upper()}-{n + 1}", "full_name": f"{name} Pupil"}
        student = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
        path = f"{API}/classes/{class_id}/students"
        _ok(admin.post(path, json={"student_ids": [student]}), 201)
    grade = f"{API}/fees/years/{year['id']}/terms/1/grades/grade_4"
    _ok(admin.put(grade, json={"items": ITEMS}))
    bills = _ok(admin.post(f"{grade}/issue"))["bills"]
    return {
        "year": year["id"],
        "term": f"years/{year['id']}/terms/1",
        "bills": {bill["student"]["full_name"].split()[0]: bill["id"] for bill in bills},
    }


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """Schools A and B, each with one user per role, and Grade 4's Term 1
    bills for Amani and Baraka."""
    made = {}
    for code in ("a", "b"):
        school_id = make_school(code=f"school-{code}", name=f"School {code.upper()}")
        for role in ("school_admin", "principal", "finance_officer", "registrar", "teacher"):
            add_member(make_user(email=f"{role}.{code}@example.com"), school_id, role)
        admin = _as(db_app, "school_admin", code)
        made[code] = {"admin": admin, **_set_up_school(db_app, admin, code)}
    return made


def _bill(school, name="Amani", code="a"):
    return school[code]["bills"][name]


def _pay(client, bill_id, **overrides):
    body = {
        "amount_kes": 10_000,
        "method": "mpesa",
        "reference": "SJK3ABCD12",
        "paid_on": "2027-02-09",
        "paid_by": "Otieno Parent",
        **overrides,
    }
    return client.post(f"{API}/fees/bills/{bill_id}/payments", json=body)


def _cancel(client, payment_id, reason="Entered twice by mistake"):
    return client.post(f"{API}/fees/payments/{payment_id}/cancellation", json={"reason": reason})


def _get_bill(client, bill_id):
    return _ok(client.get(f"{API}/fees/bills/{bill_id}"))


def _receipt(client, payment_id):
    return _ok(client.get(f"{API}/fees/payments/{payment_id}"))


def _day(client, day=None):
    return _ok(client.get(f"{API}/fees/payments", query_string={"date": day or _recorded_today()}))


# Who may do what.


def _every_endpoint(bill_id, payment_id=NOT_FOUND_ID):
    return [
        ("post", f"{API}/fees/bills/{bill_id}/payments", {"amount_kes": 1, "method": "cash"}),
        ("get", f"{API}/fees/payments/{payment_id}", None),
        ("post", f"{API}/fees/payments/{payment_id}/cancellation", {"reason": "x"}),
        ("get", f"{API}/fees/payments", None),
    ]


@pytest.mark.parametrize("role", ["teacher", "registrar"])
def test_teachers_and_registrars_see_no_payments(db_app, school, role):
    payment = _ok(_pay(school["a"]["admin"], _bill(school)), 201)["payment"]
    client = _as(db_app, role)
    for method, path, body in _every_endpoint(_bill(school), payment["id"]):
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 403, (method, path)
    assert ("denied", None, "None") in _events(db_app, "payments.record")
    assert ("denied", None, "None") in _events(db_app, "payments.cancel")
    assert ("denied", None, "None") in _events(db_app, "fees.read")


def test_a_principal_sees_payments_but_records_and_cancels_nothing(db_app, school):
    payment = _ok(_pay(school["a"]["admin"], _bill(school)), 201)["payment"]
    principal = _as(db_app, "principal")

    bill = _get_bill(principal, _bill(school))
    assert (bill["can_record_payments"], bill["can_cancel_payments"]) == (False, False)
    assert [p["receipt_number"] for p in bill["payments"]] == [1]
    assert _receipt(principal, payment["id"])["payment"]["receipt_number"] == 1
    assert [p["receipt_number"] for p in _day(principal)["payments"]] == [1]

    assert _pay(principal, _bill(school), reference="TKL9XYZW01").status_code == 403
    assert _cancel(principal, payment["id"]).status_code == 403
    assert len(_get_bill(principal, _bill(school))["payments"]) == 1


def test_a_finance_officer_records_payments_but_cannot_cancel_them(db_app, school):
    bursar = _as(db_app, "finance_officer")
    bill = _get_bill(bursar, _bill(school))
    assert (bill["can_record_payments"], bill["can_cancel_payments"]) == (True, False)

    payment = _ok(_pay(bursar, _bill(school)), 201)["payment"]
    assert _error(_cancel(bursar, payment["id"]), 403)["code"] == "forbidden"
    assert _get_bill(bursar, _bill(school))["payments"][0]["cancelled"] is None
    assert ("denied", None, "None") in _events(db_app, "payments.cancel")


def test_an_administrator_records_and_cancels(db_app, school):
    admin = school["a"]["admin"]
    bill = _get_bill(admin, _bill(school))
    assert (bill["can_record_payments"], bill["can_cancel_payments"]) == (True, True)
    payment = _ok(_pay(admin, _bill(school)), 201)["payment"]
    assert _cancel(admin, payment["id"]).status_code == 201


def test_another_schools_bills_and_payments_are_not_found(db_app, school):
    payment = _ok(_pay(school["a"]["admin"], _bill(school)), 201)["payment"]
    other = school["b"]["admin"]

    assert _error(_pay(other, _bill(school)), 404)["message"] == "Bill not found."
    assert _error(other.get(f"{API}/fees/payments/{payment['id']}"), 404)["message"] == (
        "Payment not found."
    )
    assert _error(_cancel(other, payment["id"]), 404)["message"] == "Payment not found."
    assert _day(other)["payments"] == []
    assert ("denied", "bill", _bill(school)) in _events(db_app, "payment.recorded")
    assert ("denied", "payment", payment["id"]) in _events(db_app, "payment.cancelled")
    assert ("denied", "payment", payment["id"]) in _events(db_app, "fees.read")
    # And nothing changed in School A.
    assert _get_bill(school["a"]["admin"], _bill(school))["payments"][0]["cancelled"] is None


def test_payments_that_do_not_exist_are_not_found(db_app, school):
    admin = school["a"]["admin"]
    assert _pay(admin, NOT_FOUND_ID).status_code == 404
    assert admin.get(f"{API}/fees/payments/{NOT_FOUND_ID}").status_code == 404
    assert _cancel(admin, NOT_FOUND_ID).status_code == 404


# Recording a payment.


def test_a_payment_is_recorded_with_the_next_receipt_number(db_app, school):
    bursar = _as(db_app, "finance_officer")

    body = _ok(_pay(bursar, _bill(school), reference="sjk3abcd12"), 201)

    payment = body["payment"]
    assert payment["receipt_number"] == 1
    assert {k: payment[k] for k in ("amount_kes", "method", "reference", "paid_on", "paid_by")} == {
        "amount_kes": 10_000,
        "method": "mpesa",
        "reference": "SJK3ABCD12",  # Stored in capitals, as on the M-Pesa message.
        "paid_on": "2027-02-09",
        "paid_by": "Otieno Parent",
    }
    assert payment["recorded_by"] == "Ada Example"
    assert payment["cancelled"] is None
    bill = body["bill"]
    assert (bill["total_kes"], bill["paid_kes"], bill["balance_kes"]) == (17_000, 10_000, 7_000)
    assert _events(db_app, "payment.recorded") == [("success", "payment", payment["id"])]


def test_receipt_numbers_follow_on_across_bills_and_start_at_1_in_each_school(db_app, school):
    admin = school["a"]["admin"]
    numbers = [
        _ok(_pay(admin, _bill(school, name), method="cash", reference=None), 201)["payment"][
            "receipt_number"
        ]
        for name in ("Amani", "Baraka", "Amani")
    ]
    assert numbers == [1, 2, 3]
    other = _ok(_pay(school["b"]["admin"], _bill(school, code="b")), 201)["payment"]
    assert other["receipt_number"] == 1


def test_several_payments_add_up_and_overpaying_leaves_a_credit(db_app, school):
    admin = school["a"]["admin"]
    _ok(_pay(admin, _bill(school), amount_kes=10_000), 201)
    _ok(_pay(admin, _bill(school), amount_kes=7_000, method="cash", reference=None), 201)
    bill = _get_bill(admin, _bill(school))
    assert (bill["paid_kes"], bill["balance_kes"]) == (17_000, 0)

    _ok(_pay(admin, _bill(school), amount_kes=500, method="bank", reference="FT27/1"), 201)
    bill = _get_bill(admin, _bill(school))
    assert (bill["paid_kes"], bill["balance_kes"]) == (17_500, -500)
    assert [p["method"] for p in bill["payments"]] == ["mpesa", "cash", "bank"]


@pytest.mark.parametrize(
    ("method", "reference", "stored"),
    [
        ("cash", None, None),
        ("cash", "   ", None),  # A blank reference is no reference.
        ("mpesa", "  tkl9xyzw01 ", "TKL9XYZW01"),
        ("bank", "  FT 2027/0042 KCB ", "FT 2027/0042 KCB"),
        ("cheque", "000123", "000123"),
    ],
)
def test_each_method_takes_its_kind_of_reference(db_app, school, method, reference, stored):
    payment = _ok(
        _pay(school["a"]["admin"], _bill(school), method=method, reference=reference), 201
    )
    assert payment["payment"]["reference"] == stored


@pytest.mark.parametrize("paid_by", [None, "", "   "])
def test_paid_by_is_optional(db_app, school, paid_by):
    payment = _ok(_pay(school["a"]["admin"], _bill(school), paid_by=paid_by), 201)["payment"]
    assert payment["paid_by"] is None


@pytest.mark.parametrize("days_ago", [0, 365])
def test_the_date_paid_can_be_today_or_up_to_a_year_back(db_app, school, days_ago):
    day = date.fromordinal(date.fromisoformat(TODAY).toordinal() - days_ago).isoformat()
    payment = _ok(_pay(school["a"]["admin"], _bill(school), paid_on=day), 201)["payment"]
    assert payment["paid_on"] == day


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"amount_kes": 0}, "nothing paid"),
        ({"amount_kes": -1}, "below 0"),
        ({"amount_kes": 1_000_001}, "above a million"),
        ({"amount_kes": "1500"}, "an amount sent as text"),
        ({"amount_kes": 1500.5}, "cents"),
        ({"amount_kes": True}, "true is not an amount"),
        ({"method": "card"}, "an unknown method"),
        ({"method": "mpesa", "reference": None}, "M-Pesa without its code"),
        ({"method": "mpesa", "reference": "SJK3ABCD1"}, "an M-Pesa code of 9 characters"),
        ({"method": "mpesa", "reference": "SJK3-ABCD1"}, "an M-Pesa code with a dash"),
        ({"method": "bank", "reference": "  "}, "a bank payment without a reference"),
        ({"method": "cheque", "reference": None}, "a cheque without its number"),
        ({"method": "bank", "reference": "R" * 41}, "a reference over 40 characters"),
        ({"method": "bank", "reference": "FT\n27"}, "a reference over two lines"),
        ({"method": "cash", "reference": "R-12"}, "cash with a reference"),
        ({"paid_on": "2027-02-11"}, "a date in the future"),
        ({"paid_on": "2026-02-09"}, "366 days back"),
        ({"paid_on": "10/02/2027"}, "a date that is not a date"),
        ({"paid_on": None}, "no date"),
        ({"paid_by": "P" * 101}, "a payer name over 100 characters"),
        ({"paid_by": "Otieno\tParent"}, "a payer name with a tab"),
        ({"note": "extra"}, "an unknown field"),
    ],
)
def test_wrong_payments_are_explained_and_change_nothing(db_app, school, overrides, why):
    admin = school["a"]["admin"]
    error = _error(_pay(admin, _bill(school), **overrides), 422)
    assert error["code"] == "invalid_request"
    assert error["details"], why
    assert _get_bill(admin, _bill(school))["payments"] == []
    # The refused attempt used no receipt number.
    assert _ok(_pay(admin, _bill(school)), 201)["payment"]["receipt_number"] == 1


def test_messages_name_the_problem_without_repeating_what_was_typed(db_app, school):
    admin = school["a"]["admin"]
    error = _error(_pay(admin, _bill(school), reference="SECRET-CODE"), 422)
    messages = " ".join(d["message"] for d in error["details"])
    assert "M-Pesa transaction code" in messages
    assert "SECRET" not in str(error)
    future = _error(_pay(admin, _bill(school), paid_on="2027-03-01"), 422)
    assert future["details"][0]["message"] == "The date paid cannot be in the future."


def test_a_payment_body_must_be_json(db_app, school):
    response = school["a"]["admin"].post(
        f"{API}/fees/bills/{_bill(school)}/payments", data="amount=1"
    )
    assert _error(response, 415)["code"] == "unsupported_media_type"


# Never the same payment twice.


@pytest.mark.parametrize(
    ("method", "first", "second", "what"),
    [
        ("mpesa", "SJK3ABCD12", "sjk3abcd12", "This M-Pesa code"),
        ("bank", "ft2027/0042", "FT2027/0042", "This bank reference"),
        ("cheque", "00123a", " 00123A ", "This cheque number"),
    ],
)
def test_the_same_reference_is_refused_on_any_bill(db_app, school, method, first, second, what):
    admin = school["a"]["admin"]
    _ok(_pay(admin, _bill(school), method=method, reference=first), 201)

    error = _error(_pay(admin, _bill(school, "Baraka"), method=method, reference=second), 409)

    assert error["code"] == "duplicate_reference"
    assert error["message"].startswith(f"{what} has already been recorded")
    assert _get_bill(admin, _bill(school, "Baraka"))["payments"] == []
    # No receipt number was used up.
    assert (
        _ok(_pay(admin, _bill(school), method="cash", reference=None), 201)["payment"][
            "receipt_number"
        ]
        == 2
    )


def test_a_reference_may_repeat_for_another_method_or_school(db_app, school):
    _ok(_pay(school["a"]["admin"], _bill(school), reference="SJK3ABCD12"), 201)
    _ok(_pay(school["a"]["admin"], _bill(school), method="bank", reference="SJK3ABCD12"), 201)
    _ok(_pay(school["b"]["admin"], _bill(school, code="b"), reference="SJK3ABCD12"), 201)


def test_a_cancelled_payments_reference_still_cannot_be_used_again(db_app, school):
    """A cancelled payment stays on record: recording the same M-Pesa code
    again would look like the same money twice. Cancel, then record the
    corrected payment under its own code (or as cash)."""
    admin = school["a"]["admin"]
    payment = _ok(_pay(admin, _bill(school)), 201)["payment"]
    _ok(_cancel(admin, payment["id"]), 201)
    assert _error(_pay(admin, _bill(school)), 409)["code"] == "duplicate_reference"


# Cancelling.


def test_a_cancelled_payment_stays_listed_but_no_longer_counts(db_app, school):
    admin = school["a"]["admin"]
    first = _ok(_pay(admin, _bill(school), amount_kes=10_000), 201)["payment"]
    _ok(_pay(admin, _bill(school), amount_kes=2_000, method="cash", reference=None), 201)

    bill = _ok(_cancel(admin, first["id"], "  Entered twice by mistake  "), 201)

    assert (bill["paid_kes"], bill["balance_kes"]) == (2_000, 15_000)
    cancelled = bill["payments"][0]
    assert cancelled["receipt_number"] == 1
    assert cancelled["cancelled"]["reason"] == "Entered twice by mistake"
    assert cancelled["cancelled"]["cancelled_by"] == "Ada Example"
    assert bill["payments"][1]["cancelled"] is None
    assert _events(db_app, "payment.cancelled") == [("success", "payment", first["id"])]
    # Its number is never used again.
    assert (
        _ok(_pay(admin, _bill(school), method="cash", reference=None), 201)["payment"][
            "receipt_number"
        ]
        == 3
    )


def test_a_payment_is_cancelled_only_once(db_app, school):
    admin = school["a"]["admin"]
    payment = _ok(_pay(admin, _bill(school)), 201)["payment"]
    _ok(_cancel(admin, payment["id"]), 201)
    error = _error(_cancel(admin, payment["id"], "Again"), 409)
    assert error["message"] == "This payment has already been cancelled."
    bill = _get_bill(admin, _bill(school))
    assert bill["payments"][0]["cancelled"]["reason"] == "Entered twice by mistake"


@pytest.mark.parametrize("reason", ["", "   ", "R" * 201, "Two\nlines", None, 5])
def test_a_cancellation_needs_a_one_line_reason(db_app, school, reason):
    admin = school["a"]["admin"]
    payment = _ok(_pay(admin, _bill(school)), 201)["payment"]
    response = admin.post(
        f"{API}/fees/payments/{payment['id']}/cancellation", json={"reason": reason}
    )
    assert _error(response, 422)["code"] == "invalid_request"
    assert _get_bill(admin, _bill(school))["payments"][0]["cancelled"] is None


# Receipts.


def test_a_receipt_shows_the_school_student_term_and_payment(db_app, school):
    admin = school["a"]["admin"]
    payment = _ok(_pay(admin, _bill(school)), 201)["payment"]

    receipt = _receipt(_as(db_app, "finance_officer"), payment["id"])

    assert receipt["school"] == {"name": "School A"}
    assert receipt["payment"]["receipt_number"] == 1
    assert receipt["payment"]["amount_kes"] == 10_000
    bill = receipt["bill"]
    assert bill["id"] == _bill(school)
    assert bill["student"]["full_name"] == "Amani Pupil"
    assert bill["student"]["admission_number"] == "A-1"
    assert bill["class_name"] == "Grade 4 East"
    assert bill["grade"] == {"code": "grade_4", "name": "Grade 4"}
    assert (bill["term"]["number"], bill["year"]["name"]) == (1, "2027")
    assert receipt["balance_after_kes"] == 7_000


def test_a_receipt_keeps_the_balance_of_its_own_moment(db_app, school):
    """Printed again later, a receipt shows the same figures: later payments,
    adjustments and cancellations do not change it."""
    admin = school["a"]["admin"]
    first = _ok(_pay(admin, _bill(school), amount_kes=10_000), 201)["payment"]
    second = _ok(_pay(admin, _bill(school), amount_kes=3_000, method="cash", reference=None), 201)
    adjustment = {"amount_kes": -1_000, "reason": "Bursary from the county"}
    _ok(admin.post(f"{API}/fees/bills/{_bill(school)}/adjustments", json=adjustment), 201)
    _ok(_cancel(admin, first["id"]), 201)

    assert _receipt(admin, first["id"])["balance_after_kes"] == 7_000
    assert _receipt(admin, second["payment"]["id"])["balance_after_kes"] == 4_000
    assert _receipt(admin, first["id"])["payment"]["cancelled"]["reason"] == (
        "Entered twice by mistake"
    )
    assert _get_bill(admin, _bill(school))["balance_kes"] == 13_000


# Payments on a day.


def test_payments_on_a_day_add_up_by_method_leaving_out_cancelled_ones(db_app, school):
    admin = school["a"]["admin"]
    _ok(_pay(admin, _bill(school), amount_kes=10_000), 201)
    cash = _ok(_pay(admin, _bill(school, "Baraka"), method="cash", reference=None), 201)
    _ok(_pay(admin, _bill(school), amount_kes=4_000, method="cash", reference=None), 201)
    _ok(_cancel(admin, cash["payment"]["id"]), 201)

    day = _day(_as(db_app, "finance_officer"))

    assert day["date"] == _recorded_today()
    assert [(p["receipt_number"], p["student"]["full_name"]) for p in day["payments"]] == [
        (1, "Amani Pupil"),
        (2, "Baraka Pupil"),
        (3, "Amani Pupil"),
    ]
    assert day["payments"][1]["cancelled"]["reason"] == "Entered twice by mistake"
    assert day["payments"][0]["class_name"] == "Grade 4 East"
    assert {t["method"]: t["amount_kes"] for t in day["totals"]} == {
        "cash": 4_000,
        "mpesa": 10_000,
        "bank": 0,
        "cheque": 0,
    }
    assert [t["name"] for t in day["totals"]] == ["Cash", "M-Pesa", "Bank", "Cheque"]
    assert (day["total_kes"], day["cancelled"]) == (14_000, 1)


def test_payments_on_a_day_go_by_when_they_were_recorded(db_app, school):
    _ok(_pay(school["a"]["admin"], _bill(school), paid_on="2027-01-05"), 201)
    assert len(_day(school["a"]["admin"])["payments"]) == 1
    assert _day(school["a"]["admin"], "2027-01-05")["payments"] == []


def test_payments_on_a_day_default_to_today(db_app, school):
    body = _ok(school["a"]["admin"].get(f"{API}/fees/payments"))
    assert body["date"] == TODAY
    assert (body["payments"], body["total_kes"], body["cancelled"]) == ([], 0, 0)


@pytest.mark.parametrize("query", ["date=2027-13-01", "date=yesterday", "date=1&date=2", "x=1"])
def test_a_wrong_day_is_explained(db_app, school, query):
    response = school["a"]["admin"].get(f"{API}/fees/payments?{query}")
    assert _error(response, 422)["code"] == "invalid_request"


# Paid and owed elsewhere.


def test_the_term_overview_shows_billed_paid_and_outstanding(db_app, school):
    """An overpaid bill's credit does not lower what another family owes."""
    admin = school["a"]["admin"]
    _ok(_pay(admin, _bill(school), amount_kes=20_000), 201)  # 3,000 over.
    cancelled = _ok(_pay(admin, _bill(school, "Baraka"), method="cash", reference=None), 201)
    _ok(_cancel(admin, cancelled["payment"]["id"]), 201)
    _ok(_pay(admin, _bill(school, "Baraka"), amount_kes=5_000, method="cash", reference=None), 201)

    grade = _ok(admin.get(f"{API}/fees/{school['a']['term']}"))["grades"][0]

    assert (grade["billed_kes"], grade["paid_kes"], grade["outstanding_kes"]) == (
        34_000,
        25_000,
        12_000,
    )


def test_grade_and_student_pages_show_paid_and_balance(db_app, school):
    admin = school["a"]["admin"]
    _ok(_pay(admin, _bill(school), amount_kes=4_000), 201)

    grade = _ok(admin.get(f"{API}/fees/{school['a']['term']}/grades/grade_4"))
    money = {
        b["student"]["full_name"]: (b["total_kes"], b["paid_kes"], b["balance_kes"])
        for b in grade["bills"]
    }
    assert money == {"Amani Pupil": (17_000, 4_000, 13_000), "Baraka Pupil": (17_000, 0, 17_000)}

    student = _ok(admin.get(f"{API}/students/{grade['bills'][0]['student']['id']}/bills"))
    bill = student["bills"][0]
    assert (bill["total_kes"], bill["paid_kes"], bill["balance_kes"]) == (17_000, 4_000, 13_000)


# Logs.


def test_payments_never_reach_the_logs(db_app, school, caplog):
    caplog.set_level(logging.DEBUG)
    admin = school["a"]["admin"]
    payment = _ok(_pay(admin, _bill(school), amount_kes=12_345, reference="QWE9RTY8UI"), 201)
    _ok(_cancel(admin, payment["payment"]["id"], "Secret reason here"), 201)

    logged = caplog.text
    assert payment["payment"]["id"] in logged
    for private in ("12345", "12,345", "QWE9RTY8UI", "Otieno", "Secret reason", "Amani"):
        assert private not in logged
