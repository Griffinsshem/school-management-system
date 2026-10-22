import uuid

import pytest
from sqlalchemy import select

from app import create_app
from app.extensions import db
from app.models import AuditEvent

STUDENTS = "/api/v1/school/students"
PASSWORD = "correct horse battery"
NEW_STUDENT = {"admission_number": "ADM-100", "full_name": "Demo Student One"}


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _events(app, action):
    with app.app_context():
        rows = db.session.execute(
            select(AuditEvent.outcome, AuditEvent.target_id)
            .where(AuditEvent.action == action)
            .order_by(AuditEvent.occurred_at)
        )
        return [tuple(row) for row in rows]


@pytest.fixture
def school(db_app, make_user, make_school, add_member, make_student):
    """School A with staff of each kind and two students; School B with one student."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    for role in ("school_admin", "principal", "registrar", "teacher"):
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    students = {
        "amani": make_student(school_a, "A-001", "Amani Demo"),
        "baraka": make_student(school_a, "A-002", "Baraka Demo"),
        "other_school": make_student(school_b, "B-001", "Other School Demo"),
    }
    return school_a, school_b, students


def _url(student_id, suffix="") -> str:
    return f"{STUDENTS}/{student_id}{suffix}"


# Access rules for every endpoint.

ENDPOINTS = [
    ("get", lambda s: STUDENTS, None, "students.read"),
    ("get", lambda s: _url(s["amani"]), None, "students.read"),
    ("post", lambda s: STUDENTS, NEW_STUDENT, "students.manage"),
    ("patch", lambda s: _url(s["amani"]), {"full_name": "Changed Name"}, "students.manage"),
    ("post", lambda s: _url(s["amani"], "/deactivate"), None, "students.manage"),
]


@pytest.mark.parametrize(("method", "url", "body", "_permission"), ENDPOINTS)
def test_endpoints_need_a_login(db_app, school, method, url, body, _permission):
    response = getattr(db_app.test_client(), method)(url(school[2]), json=body)

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "url", "body", "_permission"), ENDPOINTS)
def test_endpoints_need_an_active_school(db_app, school, make_user, method, url, body, _permission):
    make_user(email="nobody@example.com")
    client = _client_for(db_app, "nobody@example.com")

    response = getattr(client, method)(url(school[2]), json=body)

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "no_active_school"


@pytest.mark.parametrize(("method", "url", "body", "permission"), ENDPOINTS)
def test_teachers_are_refused_and_recorded(db_app, school, method, url, body, permission):
    client = _client_for(db_app, "teacher@example.com")

    response = getattr(client, method)(url(school[2]), json=body)

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"
    assert _events(db_app, permission) == [("denied", None)]


def test_principals_can_read_but_not_change(db_app, school):
    _a, _b, students = school
    client = _client_for(db_app, "principal@example.com")

    assert client.get(STUDENTS).status_code == 200
    assert client.get(_url(students["amani"])).status_code == 200
    assert client.post(STUDENTS, json=NEW_STUDENT).status_code == 403
    assert client.patch(_url(students["amani"]), json={"full_name": "X Y"}).status_code == 403


@pytest.mark.parametrize("email", ["registrar@example.com", "school_admin@example.com"])
def test_registrars_and_school_admins_can_manage(db_app, school, email):
    response = _client_for(db_app, email).post(STUDENTS, json=NEW_STUDENT)

    assert response.status_code == 201


# Creating.


def test_creating_a_student(db_app, school):
    body = {
        "admission_number": " ADM-100 ",
        "full_name": " Demo Student One ",
        "date_of_birth": "2015-03-01",
    }

    response = _client_for(db_app, "registrar@example.com").post(STUDENTS, json=body)
    student = response.get_json()["student"]

    assert response.status_code == 201
    assert student == {
        "id": student["id"],
        "admission_number": "ADM-100",
        "full_name": "Demo Student One",
        "date_of_birth": "2015-03-01",
        "is_active": True,
    }
    assert _events(db_app, "student.created") == [("success", uuid.UUID(student["id"]))]


def test_admission_numbers_are_unique_within_the_school(db_app, school):
    client = _client_for(db_app, "registrar@example.com")

    duplicate = client.post(STUDENTS, json={"admission_number": "A-001", "full_name": "Copy Demo"})
    from_other_school = client.post(
        STUDENTS, json={"admission_number": "B-001", "full_name": "Same Number Demo"}
    )

    assert duplicate.status_code == 409
    assert duplicate.get_json()["error"]["code"] == "admission_number_taken"
    # School B already uses B-001; School A may use it too.
    assert from_other_school.status_code == 201


@pytest.mark.parametrize(
    "changes",
    [
        {"admission_number": "   "},
        {"admission_number": "x" * 31},
        {"full_name": ""},
        {"full_name": "x" * 201},
        {"date_of_birth": "2999-01-01"},
        {"date_of_birth": "1950-01-01"},
        {"date_of_birth": "01/03/2015"},
        {"school_id": str(uuid.uuid4())},
        {"is_active": False},
    ],
)
def test_invalid_students_are_rejected(db_app, school, changes):
    response = _client_for(db_app, "registrar@example.com").post(
        STUDENTS, json=NEW_STUDENT | changes
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["details"]


def test_validation_errors_never_echo_the_childs_details(db_app, school):
    name = "Secret Child Name " + "x" * 200

    response = _client_for(db_app, "registrar@example.com").post(
        STUDENTS, json={"admission_number": "ADM-9", "full_name": name}
    )

    assert response.status_code == 422
    assert "Secret Child Name" not in response.get_data(as_text=True)


def test_creating_logs_ids_but_no_names(migrated_database, school, capsys):
    client = _client_for(create_app("testing"), "registrar@example.com")
    capsys.readouterr()

    response = client.post(STUDENTS, json=NEW_STUDENT)
    output = capsys.readouterr().out

    assert f"Student created: student_id={response.get_json()['student']['id']}" in output
    assert "Demo Student One" not in output
    assert "ADM-100" not in output


# Listing and viewing.


def test_list_shows_only_the_current_school(db_app, school):
    body = _client_for(db_app, "principal@example.com").get(STUDENTS).get_json()

    assert [s["full_name"] for s in body["students"]] == ["Amani Demo", "Baraka Demo"]
    assert (body["page"], body["per_page"], body["total"]) == (1, 50, 2)


def test_list_is_paginated(db_app, school):
    client = _client_for(db_app, "principal@example.com")

    page_two = client.get(f"{STUDENTS}?per_page=1&page=2").get_json()

    assert [s["full_name"] for s in page_two["students"]] == ["Baraka Demo"]
    assert page_two["total"] == 2


@pytest.mark.parametrize(
    ("search", "expected"),
    [
        ("amani", ["Amani Demo"]),
        ("A-002", ["Baraka Demo"]),
        ("demo", ["Amani Demo", "Baraka Demo"]),
        ("Other School", []),
        ("%", []),
        ("_", []),
    ],
)
def test_search_by_name_or_admission_number(db_app, school, search, expected):
    response = _client_for(db_app, "principal@example.com").get(
        STUDENTS, query_string={"q": search}
    )

    assert [s["full_name"] for s in response.get_json()["students"]] == expected


@pytest.mark.parametrize(
    "query",
    ["per_page=101", "per_page=0", "page=0", "page=abc", "q=", "sort=name", "page=1&page=2"],
)
def test_invalid_list_queries_are_rejected(db_app, school, query):
    response = _client_for(db_app, "principal@example.com").get(f"{STUDENTS}?{query}")

    assert response.status_code == 422


def test_viewing_a_student(db_app, school):
    _a, _b, students = school

    response = _client_for(db_app, "principal@example.com").get(_url(students["amani"]))

    assert response.status_code == 200
    assert response.get_json()["student"]["admission_number"] == "A-001"


@pytest.mark.parametrize("target", ["other_school", "made_up", "malformed"])
def test_students_outside_the_school_look_missing(db_app, school, target):
    _a, _b, students = school
    student_id = {"other_school": students["other_school"], "made_up": uuid.uuid4()}.get(
        target, "not-a-uuid"
    )

    response = _client_for(db_app, "principal@example.com").get(_url(student_id))

    assert response.status_code == 404
    assert "Other School Demo" not in response.get_data(as_text=True)


# Updating.


def test_updating_changes_only_the_fields_sent(db_app, school, make_student):
    school_a, _b, _students = school
    student_id = make_student(school_a, "A-003", "Chausiku Demo", date_of_birth=None)
    client = _client_for(db_app, "registrar@example.com")

    renamed = client.patch(_url(student_id), json={"full_name": " Chausiku Renamed "})
    dated = client.patch(_url(student_id), json={"date_of_birth": "2016-07-15"})
    cleared = client.patch(_url(student_id), json={"date_of_birth": None})

    assert renamed.get_json()["student"]["full_name"] == "Chausiku Renamed"
    assert renamed.get_json()["student"]["admission_number"] == "A-003"
    assert dated.get_json()["student"]["date_of_birth"] == "2016-07-15"
    assert cleared.get_json()["student"]["date_of_birth"] is None
    assert [outcome for outcome, _ in _events(db_app, "student.updated")] == ["success"] * 3


@pytest.mark.parametrize(
    "body",
    [{}, {"full_name": None}, {"admission_number": None}, {"school_id": str(uuid.uuid4())}],
)
def test_invalid_updates_are_rejected(db_app, school, body):
    _a, _b, students = school

    response = _client_for(db_app, "registrar@example.com").patch(
        _url(students["amani"]), json=body
    )

    assert response.status_code == 422


def test_updating_to_a_taken_admission_number_is_refused(db_app, school):
    _a, _b, students = school

    response = _client_for(db_app, "registrar@example.com").patch(
        _url(students["amani"]), json={"admission_number": "A-002"}
    )

    assert response.status_code == 409
    assert _events(db_app, "student.updated") == []


@pytest.mark.parametrize(
    ("method", "suffix", "body", "action"),
    [
        ("patch", "", {"full_name": "Hijacked Name"}, "student.updated"),
        ("post", "/deactivate", None, "student.deactivated"),
    ],
)
def test_another_schools_student_cannot_be_changed(
    db_app, school, schema_owner_engine, method, suffix, body, action
):
    _a, _b, students = school
    target = students["other_school"]

    response = getattr(_client_for(db_app, "registrar@example.com"), method)(
        _url(target, suffix), json=body
    )

    assert response.status_code == 404
    assert _events(db_app, action) == [("denied", target)]
    with schema_owner_engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT full_name, is_active FROM students WHERE id = %s", (target,)
        ).one()
    assert tuple(row) == ("Other School Demo", True)


# Deactivating.


def test_deactivating_a_student(db_app, school):
    _a, _b, students = school
    client = _client_for(db_app, "registrar@example.com")

    first = client.post(_url(students["amani"], "/deactivate"))
    second = client.post(_url(students["amani"], "/deactivate"))

    assert first.status_code == second.status_code == 200
    assert first.get_json()["student"]["is_active"] is False
    assert _events(db_app, "student.deactivated") == [("success", students["amani"])]
    # Deactivated students stay on the list, marked inactive.
    listed = client.get(STUDENTS).get_json()["students"]
    assert [s["is_active"] for s in listed] == [False, True]
