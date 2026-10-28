"""The guardians API: parents and other contacts of students (D2).

All names, phone numbers and emails here are made up.
"""

import logging

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AuditEvent

STUDENTS = "/api/v1/school/students"
GUARDIANS = "/api/v1/school/guardians"
LOOKUP = "/api/v1/school/guardians/lookup"
PASSWORD = "correct horse battery"
ROLES = ("school_admin", "principal", "registrar", "teacher", "finance_officer", "guardian")
NIL = "00000000-0000-0000-0000-000000000000"
PHONE = "+254700000101"


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _events(app, action):
    with app.app_context():
        rows = db.session.execute(
            select(AuditEvent.outcome, AuditEvent.target_type).where(AuditEvent.action == action)
        )
        return [tuple(row) for row in rows]


def _student(client, number, name):
    response = client.post(STUDENTS, json={"admission_number": number, "full_name": name})
    assert response.status_code == 201
    return response.get_json()["student"]["id"]


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A: one person per role; students Amani and Baraka (siblings)
    and Chausiku. School B: a student and a guardian with PHONE."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    for role in ROLES:
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    admin_b = _client_for(db_app, "admin.b@example.com")
    student_b = _student(admin_b, "B-1", "Other School Pupil")
    added = admin_b.post(
        f"{STUDENTS}/{student_b}/guardians",
        json={"full_name": "Other Parent", "phone": PHONE, "relationship": "mother"},
    )
    assert added.status_code == 201

    admin = _client_for(db_app, "school_admin@example.com")
    return {
        "admin": admin,
        "amani": _student(admin, "ADM-1", "Amani Pupil"),
        "baraka": _student(admin, "ADM-2", "Baraka Pupil"),
        "chausiku": _student(admin, "ADM-3", "Chausiku Pupil"),
        "student_b": student_b,
        "guardian_b": added.get_json()["guardians"][0]["id"],
    }


def _add(client, student, name="Wanjiru Parent", phone=PHONE, relationship="mother", **more):
    body = {"full_name": name, "phone": phone, "relationship": relationship, **more}
    return client.post(f"{STUDENTS}/{student}/guardians", json=body)


def _list(client, student):
    return client.get(f"{STUDENTS}/{student}/guardians")


def _summary(response):
    return [
        (g["full_name"], g["relationship"], g["is_primary"])
        for g in response.get_json()["guardians"]
    ]


# Who may see and change guardians.


def test_reading_needs_a_login(db_app, school):
    assert _list(db_app.test_client(), school["amani"]).status_code == 401


@pytest.mark.parametrize("role", ["teacher", "finance_officer", "guardian"])
def test_teachers_and_other_roles_get_no_guardian_data(db_app, school, role):
    client = _client_for(db_app, f"{role}@example.com")

    assert _list(client, school["amani"]).status_code == 403
    assert client.post(LOOKUP, json={"phone": PHONE}).status_code == 403
    assert _add(client, school["amani"]).status_code == 403
    assert _events(db_app, "guardians.read") == [("denied", None)] * 2
    assert _events(db_app, "guardians.manage") == [("denied", None)]


def test_a_principal_reads_but_does_not_change(db_app, school):
    assert _add(school["admin"], school["amani"]).status_code == 201
    principal = _client_for(db_app, "principal@example.com")

    assert _summary(_list(principal, school["amani"])) == [("Wanjiru Parent", "mother", True)]
    assert principal.post(LOOKUP, json={"phone": PHONE}).status_code == 200
    assert _add(principal, school["baraka"], phone="+254700000102").status_code == 403
    guardian = _list(principal, school["amani"]).get_json()["guardians"][0]["id"]
    assert principal.patch(f"{GUARDIANS}/{guardian}", json={"full_name": "X"}).status_code == 403
    assert principal.delete(f"{STUDENTS}/{school['amani']}/guardians/{guardian}").status_code == 403


# Adding guardians.


def test_a_registrar_adds_a_guardian_in_standard_form(db_app, school):
    registrar = _client_for(db_app, "registrar@example.com")

    response = _add(
        registrar, school["amani"], phone="0700 000 101", email=" Wanjiru@Example.COM ",
        is_primary=False,
    )  # fmt: skip

    assert response.status_code == 201
    body = response.get_json()
    assert body["student"]["full_name"] == "Amani Pupil"
    guardian = body["guardians"][0]
    assert (guardian["phone"], guardian["email"]) == (PHONE, "wanjiru@example.com")
    # The first guardian is the primary one, even when not asked for.
    assert guardian["is_primary"] is True
    assert _events(db_app, "guardian.created") == [("success", "guardian")] * 2  # B and A
    assert _events(db_app, "guardian.linked") == [("success", "student")] * 2


def test_choosing_another_primary_guardian_moves_it(school):
    admin, amani = school["admin"], school["amani"]
    assert _add(admin, amani).status_code == 201

    response = _add(admin, amani, "Otieno Parent", "+254700000102", "father", is_primary=True)

    # The primary first, then by name.
    assert _summary(response) == [
        ("Otieno Parent", "father", True),
        ("Wanjiru Parent", "mother", False),
    ]


@pytest.mark.parametrize(
    ("change", "text"),
    [
        ({"phone": "0812345678"}, "Enter a Kenyan mobile number, such as 0712 345 678."),
        ({"phone": "+1 202 555 0100"}, "Enter a Kenyan mobile number"),
        ({"relationship": "uncle"}, "Input should be"),
        ({"full_name": "   "}, "Must not be blank."),
        ({"email": "not-an-email"}, "Enter a valid email address."),
        ({"national_id": "12345678"}, "Extra inputs"),
    ],
)
def test_mistakes_are_explained_without_repeating_the_input(school, change, text):
    body = {"full_name": "Wanjiru Parent", "phone": PHONE, "relationship": "mother", **change}

    response = school["admin"].post(f"{STUDENTS}/{school['amani']}/guardians", json=body)

    assert response.status_code == 422
    assert text in " ".join(d["message"] for d in response.get_json()["error"]["details"])
    for value in change.values():
        if value.strip():
            assert value not in response.get_data(as_text=True)


def test_a_student_has_at_most_four_guardians(db_app, school):
    admin, amani = school["admin"], school["amani"]
    for n in range(4):
        assert _add(admin, amani, f"Parent {n}", f"+25470000020{n}").status_code == 201

    fifth = _add(admin, amani, "Parent 5", "+254700000205")
    assert _add(admin, school["baraka"], "Shared", "+254700000206").status_code == 201
    shared = _list(admin, school["baraka"]).get_json()["guardians"][0]["id"]
    linked = admin.post(
        f"{STUDENTS}/{amani}/guardians/link",
        json={"guardian_id": shared, "relationship": "guardian"},
    )

    for response in (fifth, linked):
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "too_many_guardians"
    # Nothing was half-saved.
    assert len(_list(admin, amani).get_json()["guardians"]) == 4
    assert admin.post(LOOKUP, json={"phone": "+254700000205"}).status_code == 404


# Siblings share one guardian.


def test_a_siblings_guardian_is_found_and_linked_not_duplicated(db_app, school):
    admin, amani, baraka = school["admin"], school["amani"], school["baraka"]
    assert _add(admin, amani, phone="+254700000301").status_code == 201

    again = _add(admin, baraka, phone="0700 000 301")
    assert (again.status_code, again.get_json()["error"]["code"]) == (409, "guardian_exists")
    assert "Wanjiru Parent is already recorded" in again.get_json()["error"]["message"]

    # The number may be written any usual way.
    found = admin.post(LOOKUP, json={"phone": "254 700 000 301"})
    assert found.status_code == 200
    guardian = found.get_json()["guardian"]
    assert [s["full_name"] for s in guardian["students"]] == ["Amani Pupil"]

    linked = admin.post(
        f"{STUDENTS}/{baraka}/guardians/link",
        json={"guardian_id": guardian["id"], "relationship": "mother"},
    )
    assert linked.status_code == 201
    assert _summary(linked) == [("Wanjiru Parent", "mother", True)]
    both = admin.post(LOOKUP, json={"phone": "+254700000301"}).get_json()["guardian"]
    assert [s["full_name"] for s in both["students"]] == ["Amani Pupil", "Baraka Pupil"]

    twice = admin.post(
        f"{STUDENTS}/{baraka}/guardians/link",
        json={"guardian_id": guardian["id"], "relationship": "mother"},
    )
    assert (twice.status_code, twice.get_json()["error"]["code"]) == (409, "already_linked")


def test_an_unknown_number_is_not_found(school):
    response = school["admin"].post(LOOKUP, json={"phone": "+254700000999"})

    assert response.status_code == 404


# Changing and removing.


def test_a_link_changes_relationship_and_primary(school):
    admin, amani = school["admin"], school["amani"]
    assert _add(admin, amani).status_code == 201
    other = _add(admin, amani, "Otieno Parent", "+254700000102", "father")
    otieno = next(
        g["id"] for g in other.get_json()["guardians"] if g["full_name"] == "Otieno Parent"
    )
    path = f"{STUDENTS}/{amani}/guardians/{otieno}"

    changed = admin.patch(path, json={"relationship": "guardian", "is_primary": True})

    assert changed.status_code == 200
    assert _summary(changed) == [
        ("Otieno Parent", "guardian", True),
        ("Wanjiru Parent", "mother", False),
    ]
    # A student always keeps one primary guardian: choose another instead.
    assert admin.patch(path, json={"is_primary": False}).status_code == 422
    assert admin.patch(path, json={}).status_code == 422
    not_linked = admin.patch(f"{STUDENTS}/{school['baraka']}/guardians/{otieno}", json={
        "relationship": "father"})  # fmt: skip
    assert not_linked.status_code == 404


def test_removing_the_primary_passes_it_on_and_keeps_the_record(db_app, school):
    admin, amani = school["admin"], school["amani"]
    first = _add(admin, amani).get_json()["guardians"][0]["id"]
    assert _add(admin, amani, "Otieno Parent", "+254700000102", "father").status_code == 201
    assert _add(admin, amani, "Bibi Parent", "+254700000103", "grandparent").status_code == 201
    path = f"{STUDENTS}/{amani}/guardians/{first}"

    removed = admin.delete(path)

    assert removed.status_code == 200
    # Otieno was linked longest ago of those left.
    assert _summary(removed) == [
        ("Otieno Parent", "father", True),
        ("Bibi Parent", "grandparent", False),
    ]
    assert admin.delete(path).status_code == 404
    # The guardian record stays, for other children and history.
    assert admin.post(LOOKUP, json={"phone": PHONE}).get_json()["guardian"]["students"] == []
    assert _events(db_app, "guardian.unlinked") == [("success", "student")]


def test_a_guardians_details_are_corrected(db_app, school):
    admin = school["admin"]
    first = _add(admin, school["amani"], email="w@example.com").get_json()["guardians"][0]["id"]
    _add(admin, school["baraka"], "Otieno Parent", "+254700000102", "father")

    taken = admin.patch(f"{GUARDIANS}/{first}", json={"phone": "0700000102"})
    assert (taken.status_code, taken.get_json()["error"]["code"]) == (409, "phone_taken")

    changed = admin.patch(
        f"{GUARDIANS}/{first}", json={"full_name": "Wanjiru Kamau", "phone": "0700000109",
                                      "email": None}
    )  # fmt: skip
    assert changed.status_code == 200
    assert changed.get_json()["guardian"] == {
        "id": first, "full_name": "Wanjiru Kamau", "phone": "+254700000109", "email": None,
    }  # fmt: skip
    assert _events(db_app, "guardian.updated") == [("success", "guardian")]
    for body in ({}, {"phone": None}, {"full_name": None}):
        assert admin.patch(f"{GUARDIANS}/{first}", json=body).status_code == 422


# Keeping schools apart.


def test_another_schools_students_and_guardians_are_invisible(db_app, school):
    admin = school["admin"]

    assert _list(admin, school["student_b"]).status_code == 404
    assert _add(admin, school["student_b"], phone="+254700000401").status_code == 404
    linked = admin.post(
        f"{STUDENTS}/{school['amani']}/guardians/link",
        json={"guardian_id": school["guardian_b"], "relationship": "mother"},
    )
    assert linked.status_code == 404
    assert (
        admin.patch(f"{GUARDIANS}/{school['guardian_b']}", json={"full_name": "X"}).status_code
        == 404
    )
    # School B's number is not found from School A, and may be used here too.
    assert admin.post(LOOKUP, json={"phone": PHONE}).status_code == 404
    assert _add(admin, school["amani"]).status_code == 201
    assert _events(db_app, "guardians.read") == [("denied", "student")]
    assert ("denied", "guardian") in _events(db_app, "guardian.linked")


def test_unknown_ids_are_not_found(school):
    admin = school["admin"]

    assert _list(admin, NIL).status_code == 404
    assert admin.delete(f"{STUDENTS}/{school['amani']}/guardians/{NIL}").status_code == 404


# Privacy.


def test_phone_numbers_and_emails_never_reach_the_logs(db_app, school, caplog):
    admin = school["admin"]
    caplog.set_level(logging.DEBUG)

    first = _add(admin, school["amani"], phone="0711 222 333", email="private@example.com")
    guardian = first.get_json()["guardians"][0]["id"]
    admin.post(LOOKUP, json={"phone": "0711222333"})
    admin.patch(
        f"{GUARDIANS}/{guardian}", json={"phone": "0711222444", "email": "other@example.com"}
    )
    refused = {"full_name": "X", "phone": "0811222333", "relationship": "mother"}
    admin.post(f"{STUDENTS}/{school['amani']}/guardians", json=refused)

    logged = caplog.text
    assert "Guardian added" in logged  # The log lines are there, with IDs.
    for secret in ("711222333", "711222444", "811222333", "private@", "other@"):
        assert secret not in logged
