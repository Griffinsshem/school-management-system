"""The class lists API: enrolling, moving and removing students (C3)."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AuditEvent

YEARS = "/api/v1/school/academic-years"
CLASSES = "/api/v1/school/classes"
STUDENTS = "/api/v1/school/students"
PASSWORD = "correct horse battery"
ROLES = ("school_admin", "principal", "registrar", "teacher", "finance_officer", "guardian")
NIL = "00000000-0000-0000-0000-000000000000"


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


def _id(response, key):
    assert response.status_code == 201, response.get_json()
    return response.get_json()[key]["id"]


def _year(client, name, starts_on, ends_on):
    body = {"name": name, "starts_on": starts_on, "ends_on": ends_on}
    return _id(client.post(YEARS, json=body), "academic_year")


def _class(client, year, grade, stream=None):
    body = {"academic_year_id": year, "grade": grade, "stream": stream}
    return _id(client.post(CLASSES, json=body), "class")


def _student(client, number, name):
    body = {"admission_number": number, "full_name": name}
    return _id(client.post(STUDENTS, json=body), "student")


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A: one person per role and a second teacher; a year 2027 with
    Grade 4 East and Grade 5, a year 2028 with Grade 5; students ADM-1 to
    ADM-4 and an inactive ADM-9. School B: a year, a class and a student."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    members = {
        role: add_member(make_user(email=f"{role}@example.com"), school_a, role) for role in ROLES
    }
    members["teacher2"] = add_member(make_user(email="teacher2@example.com"), school_a, "teacher")
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    admin_b = _client_for(db_app, "admin.b@example.com")
    year_b = _year(admin_b, "2027", "2027-01-04", "2027-11-26")
    class_b = _class(admin_b, year_b, "grade_4")
    student_b = _student(admin_b, "B-1", "Other School Pupil")

    admin = _client_for(db_app, "school_admin@example.com")
    y2027 = _year(admin, "2027", "2027-01-04", "2027-11-26")
    y2028 = _year(admin, "2028", "2028-01-10", "2028-11-24")
    students = {
        n: _student(admin, f"ADM-{n}", name)
        for n, name in [(1, "Amani Pupil"), (2, "Baraka Pupil"), (3, "Chausiku Pupil"),
                        (4, "Dalila Pupil"), (9, "Former Pupil")]
    }  # fmt: skip
    assert admin.post(f"{STUDENTS}/{students[9]}/deactivate").status_code == 200
    return {
        "admin": admin,
        "members": {key: str(value) for key, value in members.items()},
        "y2027": y2027,
        "y2028": y2028,
        "g4": _class(admin, y2027, "grade_4", "East"),
        "g5": _class(admin, y2027, "grade_5"),
        "g5_2028": _class(admin, y2028, "grade_5"),
        "students": students,
        "year_b": year_b,
        "class_b": class_b,
        "student_b": student_b,
    }


def _enrol(client, class_id, *student_ids):
    return client.post(f"{CLASSES}/{class_id}/students", json={"student_ids": list(student_ids)})


def _names(response):
    return [s["full_name"] for s in response.get_json()["students"]]


@pytest.fixture
def g4_with_two(school):
    """Grade 4 East with Amani and Baraka."""
    s = school["students"]
    assert _enrol(school["admin"], school["g4"], s[2], s[1]).status_code == 201
    return school


def _list(client, class_id):
    return client.get(f"{CLASSES}/{class_id}/students")


# Reading class lists.


def test_reading_needs_a_login(db_app, school):
    assert _list(db_app.test_client(), school["g4"]).status_code == 401


@pytest.mark.parametrize("role", ["school_admin", "principal", "registrar"])
def test_these_roles_read_every_class_list(db_app, g4_with_two, role):
    response = _list(_client_for(db_app, f"{role}@example.com"), g4_with_two["g4"])

    assert response.status_code == 200
    assert response.get_json()["class"]["name"] == "Grade 4 East"
    assert _names(response) == ["Amani Pupil", "Baraka Pupil"]
    # Staff who may read student records also see whether each is active.
    assert set(response.get_json()["students"][0]) == {
        "id", "admission_number", "full_name", "is_active",
    }  # fmt: skip


@pytest.mark.parametrize("role", ["finance_officer", "guardian"])
def test_other_roles_read_no_class_lists(db_app, school, role):
    response = _list(_client_for(db_app, f"{role}@example.com"), school["g4"])

    assert response.status_code == 403


def test_a_teacher_reads_only_their_classes_with_names_and_numbers_only(db_app, g4_with_two):
    school = g4_with_two
    admin, teacher_id = school["admin"], school["members"]["teacher"]
    teacher = _client_for(db_app, "teacher@example.com")

    # Not their class: exactly like a class that does not exist.
    refused = _list(teacher, school["g4"])
    assert (refused.status_code, refused.get_json()["error"]["message"]) == (
        404,
        "Class not found.",
    )
    assert _events(db_app, "class.students_read") == [("denied", "class")]

    assert (
        admin.post(
            f"{CLASSES}/{school['g4']}/teachers", json={"membership_id": teacher_id}
        ).status_code
        == 201
    )
    response = _list(teacher, school["g4"])

    assert response.status_code == 200
    assert response.get_json()["students"][0] == {
        "id": school["students"][1],
        "admission_number": "ADM-1",
        "full_name": "Amani Pupil",
    }
    # Still not the other classes.
    assert _list(teacher, school["g5"]).status_code == 404


def test_another_schools_class_lists_are_invisible(db_app, school):
    assert _list(school["admin"], school["class_b"]).status_code == 404


# Who may change class lists.


@pytest.mark.parametrize("role", ["principal", "teacher", "finance_officer"])
def test_only_admins_and_registrars_change_class_lists(db_app, g4_with_two, role):
    client = _client_for(db_app, f"{role}@example.com")
    s, g4 = g4_with_two["students"], g4_with_two["g4"]

    assert _enrol(client, g4, s[3]).status_code == 403
    assert (
        client.patch(
            f"{CLASSES}/{g4}/students/{s[1]}", json={"class_id": g4_with_two["g5"]}
        ).status_code
        == 403
    )
    assert client.delete(f"{CLASSES}/{g4}/students/{s[1]}").status_code == 403
    assert _events(db_app, "enrolments.manage") == [("denied", None)] * 3


# Enrolling.


def test_a_registrar_enrols_several_students_at_once(db_app, school):
    registrar = _client_for(db_app, "registrar@example.com")
    s = school["students"]

    response = _enrol(registrar, school["g4"], s[3], s[1])

    assert response.status_code == 201
    assert _names(response) == ["Amani Pupil", "Chausiku Pupil"]
    assert _events(db_app, "enrolment.added") == [("success", "student")] * 2


@pytest.mark.parametrize("who", [9, "other school", "unknown"])
def test_only_active_students_of_the_school_can_be_enrolled(school, who):
    s = school["students"]
    student = {9: s[9], "other school": school["student_b"], "unknown": NIL}[who]

    response = _enrol(school["admin"], school["g4"], s[1], student)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "1 of the chosen students cannot be enrolled: only active students of this school can be."
    )
    # All or nothing: Amani was not enrolled either.
    assert _names(_list(school["admin"], school["g4"])) == []


@pytest.mark.parametrize("into", ["g4", "g5"])
def test_a_student_is_in_one_class_per_year(g4_with_two, into):
    school = g4_with_two
    s = school["students"]

    response = _enrol(school["admin"], school[into], s[3], s[1])

    assert response.status_code == 409
    assert response.get_json()["error"] == {
        "code": "already_enrolled",
        "message": "Already in a class this school year: Amani Pupil (ADM-1) in Grade 4 East. "
        "Move them instead.",
        "request_id": response.get_json()["error"]["request_id"],
    }
    # All or nothing: Chausiku was not enrolled.
    assert "Chausiku Pupil" not in _names(_list(school["admin"], school[into]))


def test_a_long_refusal_names_five_and_counts_the_rest(db_app, school):
    admin = school["admin"]
    many = [_student(admin, f"M-{n}", f"Many Pupil {n}") for n in range(1, 8)]
    assert _enrol(admin, school["g4"], *many).status_code == 201

    response = _enrol(admin, school["g5"], *many)

    message = response.get_json()["error"]["message"]
    assert "Many Pupil 5 (M-5) and 2 more in Grade 4 East" in message
    assert "Many Pupil 6" not in message


def test_a_student_has_a_class_in_each_year(g4_with_two):
    school = g4_with_two

    response = _enrol(school["admin"], school["g5_2028"], school["students"][1])

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("body", "text"),
    [
        ({"student_ids": []}, "at least 1 item"),
        ({"student_ids": [NIL] * 2}, "only once"),
        ({"student_ids": ["nope"]}, "valid UUID"),
        ({"student_ids": [NIL], "colour": "blue"}, "Extra inputs"),
    ],
)
def test_impossible_requests_are_refused(school, body, text):
    response = school["admin"].post(f"{CLASSES}/{school['g4']}/students", json=body)

    assert response.status_code == 422
    assert text in " ".join(d["message"] for d in response.get_json()["error"]["details"])


def test_at_most_100_students_at_once(school):
    ids = [f"00000000-0000-0000-0000-{n:012d}" for n in range(101)]

    response = school["admin"].post(f"{CLASSES}/{school['g4']}/students", json={"student_ids": ids})

    assert response.status_code == 422


def test_another_schools_class_cannot_be_used(db_app, school):
    response = _enrol(school["admin"], school["class_b"], school["students"][1])

    assert response.status_code == 404
    assert _events(db_app, "enrolment.added") == [("denied", "class")]


# Moving and removing.


def test_a_student_moves_to_another_class_of_the_year(db_app, g4_with_two):
    school = g4_with_two
    admin, s = school["admin"], school["students"]

    response = admin.patch(
        f"{CLASSES}/{school['g4']}/students/{s[1]}", json={"class_id": school["g5"]}
    )

    assert response.status_code == 200
    # The list being looked at, now without Amani.
    assert _names(response) == ["Baraka Pupil"]
    assert _names(_list(admin, school["g5"])) == ["Amani Pupil"]
    assert _events(db_app, "enrolment.moved") == [("success", "student")]


@pytest.mark.parametrize("to", ["g5_2028", "class_b", "unknown"])
def test_a_student_cannot_move_out_of_the_year_or_school(g4_with_two, to):
    school = g4_with_two
    target = NIL if to == "unknown" else school[to]

    response = school["admin"].patch(
        f"{CLASSES}/{school['g4']}/students/{school['students'][1]}", json={"class_id": target}
    )

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "Choose another class of the same school year."
    )


def test_moving_to_the_same_class_changes_nothing(db_app, g4_with_two):
    school = g4_with_two

    response = school["admin"].patch(
        f"{CLASSES}/{school['g4']}/students/{school['students'][1]}",
        json={"class_id": school["g4"]},
    )

    assert response.status_code == 200
    assert _events(db_app, "enrolment.moved") == []


def test_a_student_is_removed_from_a_class(db_app, g4_with_two):
    school = g4_with_two
    path = f"{CLASSES}/{school['g4']}/students/{school['students'][1]}"

    removed = school["admin"].delete(path)
    again = school["admin"].delete(path)

    assert removed.status_code == 200
    assert _names(removed) == ["Baraka Pupil"]
    assert (again.status_code, again.get_json()["error"]["message"]) == (
        404,
        "That student is not in this class.",
    )
    assert _events(db_app, "enrolment.removed") == [("success", "student")]


def test_only_students_of_the_class_can_be_moved(g4_with_two):
    school = g4_with_two
    path = f"{CLASSES}/{school['g4']}/students/{school['students'][3]}"

    assert school["admin"].patch(path, json={"class_id": school["g5"]}).status_code == 404


# Finding students who still need a class.


def test_the_student_search_finds_active_students_without_a_class(g4_with_two):
    school = g4_with_two
    query = {"not_enrolled_in": school["y2027"]}

    response = school["admin"].get(STUDENTS, query_string=query)

    # Not Amani or Baraka (in Grade 4 East), not Former (inactive).
    assert _names(response) == ["Chausiku Pupil", "Dalila Pupil"]
    assert response.get_json()["total"] == 2
    # Searching still works on top.
    query["q"] = "dal"
    assert _names(school["admin"].get(STUDENTS, query_string=query)) == ["Dalila Pupil"]
    # In 2028 nobody has a class yet.
    other_year = school["admin"].get(STUDENTS, query_string={"not_enrolled_in": school["y2028"]})
    assert other_year.get_json()["total"] == 4


@pytest.mark.parametrize(("year", "status"), [("year_b", 404), ("nope", 422)])
def test_the_filter_needs_a_school_year_of_this_school(school, year, status):
    value = school.get(year, year)

    response = school["admin"].get(STUDENTS, query_string={"not_enrolled_in": value})

    assert response.status_code == status
