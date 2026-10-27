"""The classes and class teachers API (C2)."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AuditEvent

YEARS = "/api/v1/school/academic-years"
CLASSES = "/api/v1/school/classes"
PASSWORD = "correct horse battery"
ROLES = ("school_admin", "principal", "registrar", "teacher", "finance_officer", "guardian")
YEAR_2026 = {"name": "2026", "starts_on": "2026-01-05", "ends_on": "2026-11-27"}
YEAR_2028 = {"name": "2028", "starts_on": "2028-01-10", "ends_on": "2028-11-24"}


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _events(app, action):
    with app.app_context():
        rows = db.session.execute(
            select(AuditEvent.outcome, AuditEvent.target_type)
            .where(AuditEvent.action == action)
            .order_by(AuditEvent.occurred_at)
        )
        return [tuple(row) for row in rows]


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A: one person per role, a second teacher and a year 2026.
    School B: an administrator, a teacher, a year 2026 and a class."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    members = {}
    for role in ROLES:
        members[role] = add_member(make_user(email=f"{role}@example.com"), school_a, role)
    members["teacher2"] = add_member(make_user(email="teacher2@example.com"), school_a, "teacher")
    members["teacher_b"] = add_member(make_user(email="teacher.b@example.com"), school_b, "teacher")
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    # As strings, like the IDs in the API's JSON.
    members = {key: str(value) for key, value in members.items()}
    admin_b = _client_for(db_app, "admin.b@example.com")
    year_b = admin_b.post(YEARS, json=YEAR_2026).get_json()["academic_year"]["id"]
    class_b = admin_b.post(CLASSES, json={"academic_year_id": year_b, "grade": "grade_4"})
    admin = _client_for(db_app, "school_admin@example.com")
    year_a = admin.post(YEARS, json=YEAR_2026).get_json()["academic_year"]["id"]
    return {
        "admin": admin,
        "school_id": school_a,
        "year": year_a,
        "members": members,
        "year_b": year_b,
        "class_b": class_b.get_json()["class"]["id"],
    }


def _create(client, year, grade="grade_4", stream="East"):
    return client.post(CLASSES, json={"academic_year_id": year, "grade": grade, "stream": stream})


def _list(client, year):
    return client.get(CLASSES, query_string={"academic_year_id": year})


def _names(response):
    return [c["name"] for c in response.get_json()["classes"]]


def _assign(client, class_id, membership_id):
    return client.post(f"{CLASSES}/{class_id}/teachers", json={"membership_id": membership_id})


@pytest.fixture
def grade_4_east(school):
    response = _create(school["admin"], school["year"])
    assert response.status_code == 201
    return response.get_json()["class"]["id"]


# Access.


def test_reading_needs_a_login(db_app, school):
    assert _list(db_app.test_client(), school["year"]).status_code == 401


@pytest.mark.parametrize("role", ["school_admin", "principal", "registrar"])
def test_these_roles_see_every_class(db_app, school, grade_4_east, role):
    _create(school["admin"], school["year"], "grade_5", None)

    response = _list(_client_for(db_app, f"{role}@example.com"), school["year"])

    assert response.status_code == 200
    assert _names(response) == ["Grade 4 East", "Grade 5"]


@pytest.mark.parametrize("role", ["finance_officer", "guardian"])
def test_other_roles_see_no_classes(db_app, school, role):
    response = _list(_client_for(db_app, f"{role}@example.com"), school["year"])

    assert response.status_code == 403
    assert _events(db_app, "classes.read") == [("denied", None)]


@pytest.mark.parametrize("role", ["principal", "registrar", "teacher"])
def test_only_school_admins_change_classes(db_app, school, grade_4_east, role):
    client = _client_for(db_app, f"{role}@example.com")
    teacher = school["members"]["teacher"]

    assert _create(client, school["year"], "grade_6").status_code == 403
    assert client.patch(f"{CLASSES}/{grade_4_east}", json={"stream": "X"}).status_code == 403
    assert _assign(client, grade_4_east, teacher).status_code == 403
    assert client.delete(f"{CLASSES}/{grade_4_east}/teachers/{teacher}").status_code == 403
    assert _events(db_app, "classes.manage") == [("denied", None)] * 4


def test_another_schools_classes_are_invisible_and_unchangeable(db_app, school):
    admin, class_b = school["admin"], school["class_b"]
    teacher = school["members"]["teacher"]

    assert _list(admin, school["year_b"]).status_code == 404
    assert _create(admin, school["year_b"]).status_code == 422
    assert admin.patch(f"{CLASSES}/{class_b}", json={"stream": "Mine"}).status_code == 404
    assert _assign(admin, class_b, teacher).status_code == 404
    assert admin.delete(f"{CLASSES}/{class_b}/teachers/{teacher}").status_code == 404
    assert _events(db_app, "class.updated") == [("denied", "class")]
    assert _events(db_app, "class_teacher.added") == [("denied", "class")]
    assert _events(db_app, "class_teacher.removed") == [("denied", "class")]


@pytest.mark.parametrize("query", [{}, {"academic_year_id": "nope"}, {"other": "1"}])
def test_the_list_needs_a_school_year(school, query):
    assert school["admin"].get(CLASSES, query_string=query).status_code == 422


# Creating.


def test_an_admin_creates_a_class(db_app, school):
    response = _create(school["admin"], school["year"], "grade_4", "  East ")

    assert response.status_code == 201
    created = response.get_json()["class"]
    assert {k: created[k] for k in ("grade", "grade_name", "stream", "name", "teachers")} == {
        "grade": "grade_4",
        "grade_name": "Grade 4",
        "stream": "East",
        "name": "Grade 4 East",
        "teachers": [],
    }
    assert created["academic_year_id"] == school["year"]
    # One for School B in the fixture, one here.
    assert _events(db_app, "class.created") == [("success", "class")] * 2


@pytest.mark.parametrize("stream", [None, "", "   "])
def test_a_class_may_have_no_stream(school, stream):
    response = _create(school["admin"], school["year"], "pp1", stream)

    assert response.status_code == 201
    assert (response.get_json()["class"]["stream"], response.get_json()["class"]["name"]) == (
        None,
        "PP1",
    )


@pytest.mark.parametrize(
    ("year", "grade", "message"),
    [
        (YEAR_2026, "form_1", "There is no Form 1 in 2026: the last Form 1 class was in 2024."),
        (YEAR_2026, "form_2", "There is no Form 2 in 2026: the last Form 2 class was in 2025."),
        (
            YEAR_2026,
            "grade_11",
            "There is no Grade 11 in 2026: the first Grade 11 class is in 2027.",
        ),
        (YEAR_2028, "form_4", "There is no Form 4 in 2028: the last Form 4 class was in 2027."),
    ],
)
def test_grades_that_do_not_exist_in_the_year_are_refused(school, year, grade, message):
    year_id = school["year"]
    if year is YEAR_2028:
        year_id = school["admin"].post(YEARS, json=YEAR_2028).get_json()["academic_year"]["id"]

    response = _create(school["admin"], year_id, grade)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"] == [{"field": "", "message": message}]


@pytest.mark.parametrize("grade", ["form_3", "form_4", "grade_10", "grade_9", "pp2"])
def test_grades_that_exist_in_2026_are_accepted(school, grade):
    assert _create(school["admin"], school["year"], grade).status_code == 201


def test_the_list_offers_the_grades_of_the_year(school):
    grades = _list(school["admin"], school["year"]).get_json()["grades"]

    assert [g["name"] for g in grades] == (
        ["PP1", "PP2"] + [f"Grade {n}" for n in range(1, 11)] + ["Form 3", "Form 4"]
    )
    assert grades[0] == {"code": "pp1", "name": "PP1"}


@pytest.mark.parametrize(
    ("grade", "stream", "message"),
    [
        ("grade_4", "East", "This school year already has Grade 4 East."),
        ("grade_5", None, "This school year already has Grade 5."),
    ],
)
def test_a_class_exists_once_per_year(school, grade, stream, message):
    assert _create(school["admin"], school["year"], grade, stream).status_code == 201

    response = _create(school["admin"], school["year"], grade, stream)

    assert response.status_code == 409
    assert (response.get_json()["error"]["code"], response.get_json()["error"]["message"]) == (
        "class_exists",
        message,
    )


@pytest.mark.parametrize(
    "body",
    [
        {"grade": "grade_13"},
        {"grade": "Grade 4"},
        {"grade": "grade_4", "stream": "x" * 21},
        {"grade": "grade_4", "colour": "blue"},
        {"grade": "grade_4", "school_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_impossible_classes_are_refused(school, body):
    response = school["admin"].post(CLASSES, json={"academic_year_id": school["year"], **body})

    assert response.status_code == 422


def test_classes_are_listed_in_school_order(school):
    for grade, stream in [
        ("form_3", "B"),
        ("grade_10", None),
        ("grade_2", "West"),
        ("grade_2", "East"),
        ("grade_2", None),
        ("pp1", None),
    ]:
        assert _create(school["admin"], school["year"], grade, stream).status_code == 201

    assert _names(_list(school["admin"], school["year"])) == [
        "PP1",
        "Grade 2",
        "Grade 2 East",
        "Grade 2 West",
        "Grade 10",
        "Form 3 B",
    ]


# Changing.


def test_an_admin_changes_the_grade_and_stream(db_app, school, grade_4_east):
    admin = school["admin"]

    moved = admin.patch(f"{CLASSES}/{grade_4_east}", json={"grade": "grade_5", "stream": "Blue"})
    cleared = admin.patch(f"{CLASSES}/{grade_4_east}", json={"stream": None})

    assert moved.status_code == cleared.status_code == 200
    assert moved.get_json()["class"]["name"] == "Grade 5 Blue"
    assert cleared.get_json()["class"]["name"] == "Grade 5"
    assert _events(db_app, "class.updated") == [("success", "class")] * 2


@pytest.mark.parametrize(
    ("body", "status", "text"),
    [
        ({"grade": "form_1"}, 422, "There is no Form 1 in 2026"),
        ({"grade": None}, 422, "Must not be null"),
        ({}, 422, "Send at least one"),
        ({"academic_year_id": "00000000-0000-0000-0000-000000000000"}, 422, "Extra inputs"),
    ],
)
def test_impossible_changes_are_refused(school, grade_4_east, body, status, text):
    response = school["admin"].patch(f"{CLASSES}/{grade_4_east}", json=body)

    assert response.status_code == status
    assert text in " ".join(d["message"] for d in response.get_json()["error"]["details"])


def test_a_change_cannot_copy_another_class(school, grade_4_east):
    _create(school["admin"], school["year"], "grade_4", "West")

    response = school["admin"].patch(f"{CLASSES}/{grade_4_east}", json={"stream": "West"})

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == "This school year already has Grade 4 West."
    # Nothing was changed.
    assert "Grade 4 East" in _names(_list(school["admin"], school["year"]))


# Class teachers.


def test_an_admin_assigns_and_removes_class_teachers(db_app, school, grade_4_east):
    admin, members = school["admin"], school["members"]

    first = _assign(admin, grade_4_east, members["teacher"])
    second = _assign(admin, grade_4_east, members["teacher2"])

    assert first.status_code == second.status_code == 201
    teachers = second.get_json()["class"]["teachers"]
    assert {(t["membership_id"], t["full_name"], t["is_active"]) for t in teachers} == {
        (members["teacher"], "Ada Example", True),
        (members["teacher2"], "Ada Example", True),
    }

    removed = admin.delete(f"{CLASSES}/{grade_4_east}/teachers/{members['teacher']}")
    again = admin.delete(f"{CLASSES}/{grade_4_east}/teachers/{members['teacher']}")

    assert removed.status_code == 200
    assert [t["membership_id"] for t in removed.get_json()["class"]["teachers"]] == [
        members["teacher2"]
    ]
    assert again.status_code == 404
    assert _events(db_app, "class_teacher.added") == [("success", "class")] * 2
    assert _events(db_app, "class_teacher.removed") == [("success", "class")]


def test_a_teacher_is_assigned_to_a_class_once(school, grade_4_east):
    teacher = school["members"]["teacher"]
    assert _assign(school["admin"], grade_4_east, teacher).status_code == 201

    response = _assign(school["admin"], grade_4_east, teacher)

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "already_assigned"


@pytest.mark.parametrize("who", ["principal", "registrar", "teacher_b", "unknown"])
def test_only_active_teachers_of_the_school_can_be_assigned(school, grade_4_east, who):
    membership = school["members"].get(who, "00000000-0000-0000-0000-000000000000")

    response = _assign(school["admin"], grade_4_east, membership)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "Choose an active teacher of this school."
    )


def test_a_removed_teacher_cannot_be_assigned(school, grade_4_east):
    admin, teacher = school["admin"], school["members"]["teacher"]
    assert admin.post(f"/api/v1/school/members/{teacher}/deactivate").status_code == 200

    assert _assign(admin, grade_4_east, teacher).status_code == 422


# What a teacher sees.


def test_a_teacher_sees_only_their_own_classes(db_app, school, grade_4_east):
    admin, members = school["admin"], school["members"]
    other = _create(admin, school["year"], "grade_5").get_json()["class"]["id"]
    _assign(admin, other, members["teacher2"])
    teacher = _client_for(db_app, "teacher@example.com")

    assert _names(_list(teacher, school["year"])) == []

    _assign(admin, grade_4_east, members["teacher"])
    _assign(admin, grade_4_east, members["teacher2"])
    classes = _list(teacher, school["year"]).get_json()["classes"]

    assert [c["name"] for c in classes] == ["Grade 4 East"]
    # A class teacher sees who else teaches the class.
    assert len(classes[0]["teachers"]) == 2


def test_a_removed_teacher_loses_their_classes(db_app, school, grade_4_east):
    admin, members = school["admin"], school["members"]
    _assign(admin, grade_4_east, members["teacher"])
    _assign(admin, grade_4_east, members["teacher2"])
    teacher2 = _client_for(db_app, "teacher2@example.com")

    assert admin.post(f"/api/v1/school/members/{members['teacher']}/deactivate").status_code == 200

    # The administrator still sees the old assignment, marked inactive...
    teachers = _list(admin, school["year"]).get_json()["classes"][0]["teachers"]
    assert {(t["membership_id"], t["is_active"]) for t in teachers} == {
        (members["teacher"], False),
        (members["teacher2"], True),
    }
    # ...the other class teacher no longer sees them...
    teachers = _list(teacher2, school["year"]).get_json()["classes"][0]["teachers"]
    assert [t["membership_id"] for t in teachers] == [members["teacher2"]]
    # ...and the removed teacher has no access at all any more.
    assert _list(_client_for_any(db_app, "teacher@example.com"), school["year"]).status_code in (
        401,
        403,
    )


def _client_for_any(app, email):
    """Log in, whatever the outcome (a removed member may have no school)."""
    client = app.test_client()
    client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    return client


def test_a_teacher_who_is_also_principal_sees_every_class(
    db_app, school, grade_4_east, make_user, add_member
):
    user = make_user(email="both@example.com")
    for role in ("teacher", "principal"):
        add_member(user, school["school_id"], role)

    response = _list(_client_for(db_app, "both@example.com"), school["year"])

    assert _names(response) == ["Grade 4 East"]
