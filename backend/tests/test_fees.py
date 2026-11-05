"""School fees: structures, issuing bills, optional items and adjustments
(E1). All names, phone numbers and amounts are made up."""

import logging
from datetime import date

import pytest
from sqlalchemy import select, update

from app.api.v1 import academic_years as years_api
from app.extensions import db
from app.models import AuditEvent, User

PASSWORD = "correct horse battery"
API = "/api/v1/school"
TODAY = "2027-02-10"  # In Term 1.
YEAR = {
    "name": "2027",
    "starts_on": "2027-01-04",
    "ends_on": "2027-11-26",
    "terms": [
        {"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"},
        {"number": 2, "starts_on": "2027-05-03", "ends_on": "2027-08-06"},
    ],
}
ITEMS = [
    {"name": "Tuition", "amount_kes": 15_000},
    {"name": "Activity", "amount_kes": 2_000},
    {"name": "Boarding", "amount_kes": 30_000, "is_optional": True},
    {"name": "Transport", "amount_kes": 6_500, "is_optional": True},
]


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(years_api, "school_today", lambda: date.fromisoformat(TODAY))


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


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A, 2027 (Terms 1 and 2). Grade 4 East has Amani and Baraka,
    Grade 4 West has Chausiku, Grade 5 has Dalila; Eshe (Grade 4 East) has
    left (inactive). Amani's mother is her primary guardian, her father the
    other. One user per role; School B has its own administrator."""
    school_a = make_school(code="school-a", name="School A")
    for role in ("school_admin", "principal", "finance_officer", "registrar", "teacher"):
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    add_member(make_user(email="admin.b@example.com"), make_school(code="school-b"), "school_admin")
    with db_app.app_context():
        statement = update(User).where(User.email == "finance_officer@example.com")
        db.session.execute(statement.values(full_name="Fiona Bursar"))
        db.session.commit()

    admin = _client_for(db_app, "school_admin@example.com")
    year = _ok(admin.post(f"{API}/academic-years", json=YEAR), 201)["academic_year"]
    made = {
        "admin": admin,
        "year": year["id"],
        "term1": f"years/{year['id']}/terms/1",
        "term2": f"years/{year['id']}/terms/2",
        "classes": {},
        "students": {},
    }
    for key, grade, stream in (
        ("4E", "grade_4", "East"),
        ("4W", "grade_4", "West"),
        ("5", "grade_5", None),
    ):
        body = {"academic_year_id": year["id"], "grade": grade, "stream": stream}
        made["classes"][key] = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    for n, (name, key) in enumerate(
        (("Amani", "4E"), ("Baraka", "4E"), ("Chausiku", "4W"), ("Dalila", "5"), ("Eshe", "4E"))
    ):
        body = {"admission_number": f"ADM-{n + 1}", "full_name": f"{name} Pupil"}
        student = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
        made["students"][name] = student
        path = f"{API}/classes/{made['classes'][key]}/students"
        _ok(admin.post(path, json={"student_ids": [student]}), 201)
    _ok(admin.post(f"{API}/students/{made['students']['Eshe']}/deactivate"))
    amani = made["students"]["Amani"]
    for name, phone, relationship in (
        ("Wanjiru Parent", "+254700000101", "mother"),
        ("Otieno Parent", "+254700000102", "father"),
    ):
        body = {"full_name": name, "phone": phone, "relationship": relationship}
        _ok(admin.post(f"{API}/students/{amani}/guardians", json=body), 201)
    return made


def _as(db_app, role):
    return _client_for(db_app, f"{role}@example.com")


def _grade_path(school, grade="grade_4", term="term1"):
    return f"{API}/fees/{school[term]}/grades/{grade}"


def _save(client, school, items=ITEMS, grade="grade_4", term="term1"):
    return client.put(_grade_path(school, grade, term), json={"items": items})


def _issue(client, school, grade="grade_4", term="term1"):
    return client.post(f"{_grade_path(school, grade, term)}/issue")


def _issued(school, grade="grade_4"):
    """Grade 4's structure saved and bills issued; the bills by first name."""
    _ok(_save(school["admin"], school, grade=grade))
    body = _ok(_issue(school["admin"], school, grade=grade))
    return {bill["student"]["full_name"].split()[0]: bill for bill in body["bills"]}


def _bill_path(bill_id):
    return f"{API}/fees/bills/{bill_id}"


def _adjust(client, bill_id, amount, reason="Bursary from the county"):
    return client.post(
        f"{_bill_path(bill_id)}/adjustments", json={"amount_kes": amount, "reason": reason}
    )


def _add_item(client, bill_id, item_id):
    return client.post(f"{_bill_path(bill_id)}/items", json={"fee_item_id": item_id})


def _item_id(view, name):
    return next(i["id"] for i in view["structure"]["items"] if i["name"] == name)


# Who may do what.


def _every_endpoint(school, bill_id="00000000-0000-0000-0000-000000000000"):
    return [
        ("get", f"{API}/fees/{school['term1']}", None),
        ("get", _grade_path(school), None),
        ("put", _grade_path(school), {"items": ITEMS}),
        ("post", f"{_grade_path(school)}/issue", None),
        ("get", _bill_path(bill_id), None),
        ("post", f"{_bill_path(bill_id)}/items", {"fee_item_id": bill_id}),
        ("post", f"{_bill_path(bill_id)}/adjustments", {"amount_kes": -1, "reason": "x"}),
        ("get", f"{API}/students/{school['students']['Amani']}/bills", None),
    ]


@pytest.mark.parametrize("role", ["teacher", "registrar"])
def test_teachers_and_registrars_have_no_fee_access(db_app, school, role):
    bills = _issued(school)
    client = _as(db_app, role)
    for method, path, body in _every_endpoint(school, bills["Amani"]["id"]):
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 403, (method, path)
    assert ("denied", None, "None") in _events(db_app, "fees.read")
    assert ("denied", None, "None") in _events(db_app, "fees.manage")


def test_a_principal_reads_fees_but_changes_nothing(db_app, school):
    bills = _issued(school)
    principal = _as(db_app, "principal")
    bill_id = bills["Amani"]["id"]

    overview = _ok(principal.get(f"{API}/fees/{school['term1']}"))
    assert overview["can_manage"] is False
    assert _ok(principal.get(_grade_path(school)))["can_manage"] is False
    bill = _ok(principal.get(_bill_path(bill_id)))
    assert bill["can_manage"] is False
    assert [g["full_name"] for g in bill["guardians"]] == ["Wanjiru Parent", "Otieno Parent"]
    student_bills = principal.get(f"{API}/students/{school['students']['Amani']}/bills")
    assert len(_ok(student_bills)["bills"]) == 1

    assert _save(principal, school, grade="grade_5").status_code == 403
    assert _issue(principal, school).status_code == 403
    assert _adjust(principal, bill_id, -1_000).status_code == 403
    item = _item_id(_ok(principal.get(_grade_path(school))), "Boarding")
    assert _add_item(principal, bill_id, item).status_code == 403


def test_a_finance_officer_manages_fees(db_app, school):
    finance = _as(db_app, "finance_officer")

    view = _ok(_save(finance, school))
    assert view["can_manage"] is True
    assert view["structure"]["updated_by"] == "Fiona Bursar"
    body = _ok(_issue(finance, school))
    assert body["billed"] == 3
    amani = next(b for b in body["bills"] if b["student"]["full_name"] == "Amani Pupil")
    _ok(_adjust(finance, amani["id"], -5_000), 201)
    _ok(_add_item(finance, amani["id"], _item_id(view, "Boarding")), 201)


def test_a_finance_officer_sees_guardians_only_on_bills(db_app, school):
    bills = _issued(school)
    finance = _as(db_app, "finance_officer")
    amani = school["students"]["Amani"]

    bill = _ok(finance.get(_bill_path(bills["Amani"]["id"])))
    assert bill["guardians"] == [
        {
            "full_name": "Wanjiru Parent",
            "relationship": "mother",
            "is_primary": True,
            "phone": "+254700000101",
            "email": None,
        },
        {
            "full_name": "Otieno Parent",
            "relationship": "father",
            "is_primary": False,
            "phone": "+254700000102",
            "email": None,
        },
    ]
    # Not the guardian pages, the search by phone, or the student pages.
    assert finance.get(f"{API}/students/{amani}/guardians").status_code == 403
    lookup = finance.post(f"{API}/guardians/lookup", json={"phone": "+254700000101"})
    assert lookup.status_code == 403
    assert finance.get(f"{API}/students").status_code == 403
    assert finance.get(f"{API}/students/{amani}").status_code == 403


def test_another_schools_fees_are_not_found(db_app, school):
    bills = _issued(school)
    other = _client_for(db_app, "admin.b@example.com")
    bill_id = bills["Amani"]["id"]
    for method, path, body in _every_endpoint(school, bill_id):
        response = getattr(other, method)(path, json=body)
        assert response.status_code == 404, (method, path)
    # Nothing changed.
    assert _ok(school["admin"].get(_bill_path(bill_id)))["total_kes"] == 17_000


# Fee structures.


def test_a_fee_structure_is_saved_in_order(db_app, school):
    view = _ok(_save(school["admin"], school))

    assert view["grade"] == {"code": "grade_4", "name": "Grade 4"}
    assert view["term"]["number"] == 1
    assert view["year"]["name"] == "2027"
    structure = view["structure"]
    assert [(i["name"], i["amount_kes"], i["is_optional"]) for i in structure["items"]] == [
        ("Tuition", 15_000, False),
        ("Activity", 2_000, False),
        ("Boarding", 30_000, True),
        ("Transport", 6_500, True),
    ]
    assert structure["compulsory_total_kes"] == 17_000
    assert structure["issued_at"] is None
    assert view["bills"] == []
    assert [s["student"]["full_name"] for s in view["not_billed"]] == [
        "Amani Pupil",
        "Baraka Pupil",
        "Chausiku Pupil",
    ]
    assert [s["class_name"] for s in view["not_billed"]] == ["Grade 4 East"] * 2 + ["Grade 4 West"]
    events = _events(db_app, "fee_structure.saved")
    assert events == [("success", "fee_structure", structure["id"])]


def test_saving_again_replaces_the_items(db_app, school):
    _ok(_save(school["admin"], school))
    items = [{"name": "tuition", "amount_kes": 16_000}, {"name": "Lunch", "amount_kes": 4_000}]

    view = _ok(_save(school["admin"], school, items))

    assert [i["name"] for i in view["structure"]["items"]] == ["tuition", "Lunch"]
    assert view["structure"]["compulsory_total_kes"] == 20_000
    assert len(_events(db_app, "fee_structure.saved")) == 2


def test_names_are_trimmed_and_a_structure_can_be_emptied(db_app, school):
    view = _ok(_save(school["admin"], school, [{"name": "  Tuition  ", "amount_kes": 1}]))
    assert view["structure"]["items"][0]["name"] == "Tuition"
    view = _ok(_save(school["admin"], school, []))
    assert view["structure"]["items"] == []


@pytest.mark.parametrize(
    ("items", "why"),
    [
        ([{"name": "", "amount_kes": 100}], "an empty name"),
        ([{"name": "   ", "amount_kes": 100}], "a name of spaces"),
        ([{"name": "Tuition\nfees", "amount_kes": 100}], "two lines"),
        ([{"name": "x" * 61, "amount_kes": 100}], "a name too long"),
        ([{"name": "Tuition", "amount_kes": 0}], "nothing to pay"),
        ([{"name": "Tuition", "amount_kes": -100}], "a negative fee"),
        ([{"name": "Tuition", "amount_kes": 1_000_001}], "over a million"),
        ([{"name": "Tuition", "amount_kes": 1500.5}], "cents"),
        ([{"name": "Tuition", "amount_kes": "1500"}], "a string"),
        ([{"name": "Tuition", "amount_kes": True}], "a boolean"),
        ([{"name": "Tuition"}], "no amount"),
        ([{"name": "Tuition", "amount_kes": 1, "is_optional": "yes"}], "optional as text"),
        ([{"name": "Tuition", "amount_kes": 1, "discount": 5}], "an unknown field"),
        (
            [{"name": "Tuition", "amount_kes": 1}, {"name": "TUITION", "amount_kes": 2}],
            "the same name twice",
        ),
        ([{"name": f"Item {n}", "amount_kes": 1} for n in range(31)], "31 items"),
    ],
)
def test_wrong_fee_items_are_explained(db_app, school, items, why):
    error = _error(_save(school["admin"], school, items), 422)
    assert error["code"] == "invalid_request"
    assert error["details"]
    assert _ok(school["admin"].get(_grade_path(school)))["structure"] is None


def test_thirty_items_are_allowed(db_app, school):
    items = [{"name": f"Item {n}", "amount_kes": 1_000_000} for n in range(30)]
    view = _ok(_save(school["admin"], school, items))
    assert view["structure"]["compulsory_total_kes"] == 30_000_000


@pytest.mark.parametrize("grade", ["grade_9", "grade_13", "GRADE_4"])
def test_a_grade_without_classes_this_year_is_not_found(db_app, school, grade):
    assert _save(school["admin"], school, grade=grade).status_code == 404
    assert school["admin"].get(_grade_path(school, grade)).status_code == 404
    assert _issue(school["admin"], school, grade=grade).status_code == 404


def test_an_issued_structure_cannot_be_changed(db_app, school):
    _issued(school)

    error = _error(_save(school["admin"], school, [{"name": "Tuition", "amount_kes": 1}]), 409)

    assert error["code"] == "structure_issued"
    view = _ok(school["admin"].get(_grade_path(school)))
    assert view["structure"]["compulsory_total_kes"] == 17_000
    assert view["structure"]["issued_by"] is not None


# Issuing bills.


def test_bills_cannot_be_issued_without_fee_items(db_app, school):
    assert _error(_issue(school["admin"], school), 422)["code"] == "no_fee_items"
    _ok(_save(school["admin"], school, []))
    assert _error(_issue(school["admin"], school), 422)["code"] == "no_fee_items"
    assert _events(db_app, "fee_bills.issued") == []


def test_issuing_bills_every_active_student_of_the_grade_once(db_app, school):
    _ok(_save(school["admin"], school))

    body = _ok(_issue(school["admin"], school))

    assert body["billed"] == 3
    assert [
        (b["student"]["full_name"], b["class_name"], b["total_kes"]) for b in body["bills"]
    ] == [
        ("Amani Pupil", "Grade 4 East", 17_000),
        ("Baraka Pupil", "Grade 4 East", 17_000),
        ("Chausiku Pupil", "Grade 4 West", 17_000),
    ]
    assert body["not_billed"] == []
    assert body["structure"]["issued_at"] is not None
    structure_id = body["structure"]["id"]
    assert _events(db_app, "fee_bills.issued") == [("success", "fee_structure", structure_id)]

    # Again: nobody new, nothing billed twice.
    again = _ok(_issue(school["admin"], school))
    assert again["billed"] == 0
    assert len(again["bills"]) == 3
    assert len(_events(db_app, "fee_bills.issued")) == 1


def test_a_student_who_joins_later_is_billed_by_issuing_again(db_app, school):
    _issued(school)
    admin = school["admin"]
    body = {"admission_number": "ADM-9", "full_name": "Furaha Pupil"}
    furaha = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    path = f"{API}/classes/{school['classes']['4W']}/students"
    _ok(admin.post(path, json={"student_ids": [furaha]}), 201)

    view = _ok(admin.get(_grade_path(school)))
    assert [s["student"]["full_name"] for s in view["not_billed"]] == ["Furaha Pupil"]
    body = _ok(_issue(admin, school))
    assert body["billed"] == 1
    assert len(body["bills"]) == 4


def test_a_student_billed_in_another_grade_this_term_is_not_billed_again(db_app, school):
    _issued(school, grade="grade_5")
    admin = school["admin"]
    dalila = school["students"]["Dalila"]
    path = f"{API}/classes/{school['classes']['5']}/students/{dalila}"
    _ok(admin.patch(path, json={"class_id": school["classes"]["4E"]}))

    _ok(_save(admin, school))
    body = _ok(_issue(admin, school))

    assert body["billed"] == 3
    assert "Dalila Pupil" not in [s["student"]["full_name"] for s in body["not_billed"]]
    bills = _ok(admin.get(f"{API}/students/{dalila}/bills"))["bills"]
    assert [b["class_name"] for b in bills] == ["Grade 5"]


def test_each_term_has_its_own_bills(db_app, school):
    _issued(school)
    _ok(_save(school["admin"], school, [{"name": "Tuition", "amount_kes": 14_000}], term="term2"))
    assert _ok(_issue(school["admin"], school, term="term2"))["billed"] == 3

    bills = _ok(school["admin"].get(f"{API}/students/{school['students']['Amani']}/bills"))
    assert [(b["term"]["number"], b["total_kes"]) for b in bills["bills"]] == [
        (2, 14_000),
        (1, 17_000),
    ]


def test_the_term_overview_counts_each_grade(db_app, school):
    _issued(school)
    _ok(_save(school["admin"], school, [{"name": "Tuition", "amount_kes": 1}], grade="grade_5"))

    body = _ok(school["admin"].get(f"{API}/fees/{school['term1']}"))

    assert body["can_manage"] is True
    assert body["grades"] == [
        {
            "grade": "grade_4",
            "name": "Grade 4",
            "classes": 2,
            "students": 3,
            "billed": 3,
            "structure": {"items": 4, "compulsory_total_kes": 17_000, "issued": True},
        },
        {
            "grade": "grade_5",
            "name": "Grade 5",
            "classes": 1,
            "students": 1,
            "billed": 0,
            "structure": {"items": 1, "compulsory_total_kes": 1, "issued": False},
        },
    ]
    assert (
        _ok(school["admin"].get(f"{API}/fees/{school['term2']}"))["grades"][0]["structure"] is None
    )


def test_a_term_of_another_school_or_none_is_not_found(db_app, school):
    other = _client_for(db_app, "admin.b@example.com")
    assert other.get(f"{API}/fees/{school['term1']}").status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert school["admin"].get(f"{API}/fees/years/{missing}/terms/1").status_code == 404
    for number in ("3", "0", "x"):
        path = f"{API}/fees/years/{school['year']}/terms/{number}"
        assert school["admin"].get(path).status_code == 404


# Bills.


def test_a_bill_shows_its_lines_total_and_optional_items(db_app, school):
    bills = _issued(school)

    bill = _ok(school["admin"].get(_bill_path(bills["Amani"]["id"])))

    assert bill["student"]["full_name"] == "Amani Pupil"
    assert bill["class_name"] == "Grade 4 East"
    assert bill["grade"] == {"code": "grade_4", "name": "Grade 4"}
    assert bill["term"]["number"] == 1
    assert [(line["kind"], line["description"], line["amount_kes"]) for line in bill["lines"]] == [
        ("fee", "Tuition", 15_000),
        ("fee", "Activity", 2_000),
    ]
    assert bill["total_kes"] == 17_000
    assert [(i["name"], i["amount_kes"]) for i in bill["optional_items"]] == [
        ("Boarding", 30_000),
        ("Transport", 6_500),
    ]
    assert bill["can_manage"] is True


def test_an_optional_item_is_added_once(db_app, school):
    bills = _issued(school)
    view = _ok(school["admin"].get(_grade_path(school)))
    bill_id = bills["Amani"]["id"]

    bill = _ok(_add_item(school["admin"], bill_id, _item_id(view, "Boarding")), 201)

    assert bill["total_kes"] == 47_000
    assert bill["lines"][-1]["description"] == "Boarding"
    assert [i["name"] for i in bill["optional_items"]] == ["Transport"]
    error = _error(_add_item(school["admin"], bill_id, _item_id(view, "Boarding")), 409)
    assert error["code"] == "item_already_on_bill"
    assert _events(db_app, "bill.item_added") == [("success", "bill", bill_id)]
    # Other bills are unchanged.
    assert _ok(school["admin"].get(_bill_path(bills["Baraka"]["id"])))["total_kes"] == 17_000


def test_only_this_bills_optional_items_can_be_added(db_app, school):
    bills = _issued(school)
    _ok(_save(school["admin"], school, [{"name": "Lunch", "amount_kes": 1, "is_optional": True}],
             grade="grade_5"))  # fmt: skip
    grade_4 = _ok(school["admin"].get(_grade_path(school)))
    grade_5 = _ok(school["admin"].get(_grade_path(school, "grade_5")))
    bill_id = bills["Amani"]["id"]

    for item in (_item_id(grade_4, "Tuition"), _item_id(grade_5, "Lunch"), school["year"]):
        error = _error(_add_item(school["admin"], bill_id, item), 422)
        assert error["code"] == "not_an_optional_item"
    assert _ok(school["admin"].get(_bill_path(bill_id)))["total_kes"] == 17_000


def test_adjustments_change_the_total_with_a_reason(db_app, school):
    bills = _issued(school)
    bill_id = bills["Amani"]["id"]

    _ok(_adjust(school["admin"], bill_id, -5_000), 201)
    bill = _ok(_adjust(school["admin"], bill_id, 1_200, "  Replaced a lost textbook  "), 201)

    assert [(line["kind"], line["description"], line["amount_kes"]) for line in bill["lines"]] == [
        ("fee", "Tuition", 15_000),
        ("fee", "Activity", 2_000),
        ("adjustment", "Bursary from the county", -5_000),
        ("adjustment", "Replaced a lost textbook", 1_200),
    ]
    assert bill["total_kes"] == 13_200
    assert bill["lines"][-1]["created_by"] is not None
    assert len(_events(db_app, "bill.adjusted")) == 2


def test_a_bill_can_be_brought_to_zero_but_not_below(db_app, school):
    bills = _issued(school)
    bill_id = bills["Amani"]["id"]

    error = _error(_adjust(school["admin"], bill_id, -17_001, "Billed in error"), 422)
    assert error["code"] == "total_below_zero"
    assert "KES 17,000" in error["message"]

    bill = _ok(_adjust(school["admin"], bill_id, -17_000, "Billed in error"), 201)
    assert bill["total_kes"] == 0
    assert _error(_adjust(school["admin"], bill_id, -1), 422)["code"] == "total_below_zero"


@pytest.mark.parametrize(
    "body",
    [
        {"amount_kes": 0, "reason": "Nothing"},
        {"amount_kes": -500.5, "reason": "Cents"},
        {"amount_kes": "-500", "reason": "Text"},
        {"amount_kes": 1_000_001, "reason": "Too much"},
        {"amount_kes": -1_000_001, "reason": "Too much"},
        {"amount_kes": -500, "reason": ""},
        {"amount_kes": -500, "reason": "   "},
        {"amount_kes": -500, "reason": "Two\nlines"},
        {"amount_kes": -500, "reason": "x" * 201},
        {"amount_kes": -500},
        {"amount_kes": -500, "reason": "Bursary", "approved": True},
    ],
)
def test_wrong_adjustments_are_explained(db_app, school, body):
    bills = _issued(school)
    bill_id = bills["Amani"]["id"]
    response = school["admin"].post(f"{_bill_path(bill_id)}/adjustments", json=body)
    assert _error(response, 422)["code"] == "invalid_request"
    assert _ok(school["admin"].get(_bill_path(bill_id)))["total_kes"] == 17_000


def test_a_bill_that_does_not_exist_is_not_found(db_app, school):
    missing = "00000000-0000-0000-0000-000000000000"
    assert school["admin"].get(_bill_path(missing)).status_code == 404
    assert _adjust(school["admin"], missing, -1).status_code == 404
    assert ("denied", "bill", missing) in _events(db_app, "bill.adjusted")


def test_a_students_bills_list_is_empty_before_billing(db_app, school):
    body = _ok(school["admin"].get(f"{API}/students/{school['students']['Dalila']}/bills"))
    assert body["student"]["full_name"] == "Dalila Pupil"
    assert body["bills"] == []
    other = _client_for(db_app, "admin.b@example.com")
    assert other.get(f"{API}/students/{school['students']['Dalila']}/bills").status_code == 404


def test_fees_never_reach_the_logs(db_app, school, caplog):
    caplog.set_level(logging.DEBUG)
    bills = _issued(school)
    view = _ok(school["admin"].get(_grade_path(school)))
    _ok(_add_item(school["admin"], bills["Amani"]["id"], _item_id(view, "Transport")), 201)
    _ok(_adjust(school["admin"], bills["Amani"]["id"], -4_321, "Bursary from the county"), 201)

    logged = caplog.text
    assert "Fee bills issued" in logged
    for private in ("Amani", "Wanjiru", "Tuition", "Transport", "Bursary", "4321", "4,321"):
        assert private not in logged
