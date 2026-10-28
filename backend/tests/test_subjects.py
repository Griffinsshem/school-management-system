"""The subjects, class subjects and subject teachers API (D3)."""

import pytest
from sqlalchemy import select, update

from app.extensions import db
from app.models import AuditEvent, Membership, User

PASSWORD = "correct horse battery"
SUBJECTS = "/api/v1/school/subjects"
CLASSES = "/api/v1/school/classes"
YEARS = "/api/v1/school/academic-years"
STUDENTS = "/api/v1/school/students"
ROLES = ("school_admin", "principal", "registrar", "teacher", "finance_officer", "guardian")


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


def _id(response, key):
    assert response.status_code == 201, response.get_json()
    return response.get_json()[key]["id"]


def _subject(client, name, code=None):
    return client.post(SUBJECTS, json={"name": name, "code": code})


def _add(client, class_id, subject_id):
    return client.post(f"{CLASSES}/{class_id}/subjects", json={"subject_id": subject_id})


def _assign(client, class_id, subject_id, membership_id):
    return client.post(
        f"{CLASSES}/{class_id}/subjects/{subject_id}/teachers",
        json={"membership_id": membership_id},
    )


def _summary(response):
    """{"Mathematics": ["Teacher Name", ...], ...} from a class's subjects."""
    return {
        s["subject"]["name"]: [t["full_name"] for t in s["teachers"]]
        for s in response.get_json()["subjects"]
    }


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A: one person per role and a second teacher, a year 2027 with
    Grade 4 East (students Amani and Baraka) and Grade 5, and the subjects
    Mathematics (MAT) and English (ENG). School B: an administrator, a
    teacher, a class and a subject."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    members = {}
    for role in ROLES:
        members[role] = add_member(make_user(email=f"{role}@example.com"), school_a, role)
    members["teacher2"] = add_member(make_user(email="teacher2@example.com"), school_a, "teacher")
    with db_app.app_context():
        for email, name in [
            ("teacher@example.com", "Teacher Person"),
            ("teacher2@example.com", "Second Teacher"),
        ]:
            db.session.execute(update(User).where(User.email == email).values(full_name=name))
        db.session.commit()
    members["teacher_b"] = add_member(make_user(email="teacher.b@example.com"), school_b)
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    admin_b = _client_for(db_app, "admin.b@example.com")
    year = {"name": "2027", "starts_on": "2027-01-04", "ends_on": "2027-11-26"}
    year_b = _id(admin_b.post(YEARS, json=year), "academic_year")
    class_b = _id(
        admin_b.post(CLASSES, json={"academic_year_id": year_b, "grade": "grade_4"}), "class"
    )
    subject_b = _id(_subject(admin_b, "Mathematics", "MAT"), "subject")

    admin = _client_for(db_app, "school_admin@example.com")
    year_a = _id(admin.post(YEARS, json=year), "academic_year")
    g4 = _id(
        admin.post(
            CLASSES, json={"academic_year_id": year_a, "grade": "grade_4", "stream": "East"}
        ),
        "class",
    )
    g5 = _id(admin.post(CLASSES, json={"academic_year_id": year_a, "grade": "grade_5"}), "class")
    students = [
        _id(admin.post(STUDENTS, json={"admission_number": number, "full_name": name}), "student")
        for number, name in [("ADM-1", "Amani Pupil"), ("ADM-2", "Baraka Pupil")]
    ]
    enrolled = admin.post(f"{CLASSES}/{g4}/students", json={"student_ids": students})
    assert enrolled.status_code == 201
    return {
        "admin": admin,
        "members": {key: str(value) for key, value in members.items()},
        "year": year_a,
        "g4": g4,
        "g5": g5,
        "maths": _id(_subject(admin, "Mathematics", "MAT"), "subject"),
        "english": _id(_subject(admin, "English", "ENG"), "subject"),
        "class_b": class_b,
        "subject_b": subject_b,
    }


@pytest.fixture
def g4_maths(school):
    """Grade 4 East takes Mathematics, taught by the teacher."""
    admin = school["admin"]
    assert _add(admin, school["g4"], school["maths"]).status_code == 201
    response = _assign(admin, school["g4"], school["maths"], school["members"]["teacher"])
    assert response.status_code == 201
    return school


# Access.


def test_reading_needs_a_login(db_app, school):
    assert db_app.test_client().get(SUBJECTS).status_code == 401


@pytest.mark.parametrize("role", ["school_admin", "principal"])
def test_admins_and_principals_see_the_subject_list(db_app, school, role):
    response = _client_for(db_app, f"{role}@example.com").get(SUBJECTS)

    assert response.status_code == 200
    assert [s["name"] for s in response.get_json()["subjects"]] == ["English", "Mathematics"]


@pytest.mark.parametrize("role", ["registrar", "teacher", "finance_officer", "guardian"])
def test_other_roles_see_no_subjects(db_app, school, role):
    client = _client_for(db_app, f"{role}@example.com")

    assert client.get(SUBJECTS).status_code == 403
    assert client.get(f"{CLASSES}/{school['g4']}/subjects").status_code == 403
    assert _events(db_app, "subjects.read") == [("denied", None)] * 2


@pytest.mark.parametrize("role", ["principal", "registrar", "teacher"])
def test_only_school_admins_change_subjects(db_app, g4_maths, role):
    s = g4_maths
    client = _client_for(db_app, f"{role}@example.com")
    teacher = s["members"]["teacher2"]
    taught = f"{CLASSES}/{s['g4']}/subjects/{s['maths']}"

    assert _subject(client, "Kiswahili").status_code == 403
    assert client.patch(f"{SUBJECTS}/{s['maths']}", json={"name": "Maths"}).status_code == 403
    assert _add(client, s["g4"], s["english"]).status_code == 403
    assert client.delete(taught).status_code == 403
    assert _assign(client, s["g4"], s["maths"], teacher).status_code == 403
    assert client.delete(f"{taught}/teachers/{s['members']['teacher']}").status_code == 403
    assert _events(db_app, "subjects.manage") == [("denied", None)] * 6


# The subject list.


def test_an_admin_adds_a_subject_with_a_tidy_name_and_code(db_app, school):
    response = _subject(school["admin"], "  Social   Studies ", " SST ")

    assert response.status_code == 201
    subject = response.get_json()["subject"]
    assert (subject["name"], subject["code"], subject["is_active"]) == (
        "Social Studies",
        "SST",
        True,
    )
    # Three in the fixture (two in School A, one in School B), and this one.
    assert _events(db_app, "subject.created") == [("success", "subject")] * 4


@pytest.mark.parametrize("code", [None, "", "   "])
def test_a_code_is_optional(school, code):
    response = _subject(school["admin"], "Life Skills", code)

    assert response.status_code == 201
    assert response.get_json()["subject"]["code"] is None


@pytest.mark.parametrize("name", ["Mathematics", "MATHEMATICS", " mathematics "])
def test_a_name_is_used_once_per_school(school, name):
    response = _subject(school["admin"], name)

    assert response.status_code == 409
    error = response.get_json()["error"]
    assert (error["code"], error["message"]) == (
        "subject_exists",
        f"This school already has {name.strip()}.",
    )


def test_a_code_is_used_once_per_school(school):
    response = _subject(school["admin"], "Music", "mat")

    assert response.status_code == 409
    error = response.get_json()["error"]
    assert (error["code"], error["message"]) == (
        "code_taken",
        "Another subject already has the code mat.",
    )


def test_another_school_may_use_the_same_name_and_code(db_app, school):
    # School B's Mathematics (MAT) was made before School A's; both exist.
    names = [s["name"] for s in school["admin"].get(SUBJECTS).get_json()["subjects"]]
    assert names.count("Mathematics") == 1


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "M" * 61},
        {"name": "Music", "code": "M" * 11},
        {"name": "Music", "is_active": False},
        {},
    ],
)
def test_impossible_subjects_are_refused(school, body):
    response = school["admin"].post(SUBJECTS, json=body)

    assert response.status_code == 422


def test_a_subject_is_renamed_and_its_code_changed_or_removed(db_app, school):
    admin, maths = school["admin"], school["maths"]

    renamed = admin.patch(f"{SUBJECTS}/{maths}", json={"name": "Maths", "code": "MATH"})
    assert renamed.status_code == 200
    assert renamed.get_json()["subject"]["name"] == "Maths"
    assert renamed.get_json()["subject"]["code"] == "MATH"

    for empty in (None, ""):
        removed = admin.patch(f"{SUBJECTS}/{maths}", json={"code": empty})
        assert removed.status_code == 200
        assert removed.get_json()["subject"]["code"] is None
    assert _events(db_app, "subject.updated") == [("success", "subject")] * 3


def test_a_subject_is_made_inactive_and_active_again_but_not_deleted(school):
    admin, maths = school["admin"], school["maths"]

    off = admin.patch(f"{SUBJECTS}/{maths}", json={"is_active": False})
    assert off.get_json()["subject"]["is_active"] is False
    listed = admin.get(SUBJECTS).get_json()["subjects"]
    assert [(s["name"], s["is_active"]) for s in listed] == [
        ("English", True),
        ("Mathematics", False),
    ]
    on = admin.patch(f"{SUBJECTS}/{maths}", json={"is_active": True})
    assert on.get_json()["subject"]["is_active"] is True
    assert admin.delete(f"{SUBJECTS}/{maths}").status_code == 405


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"name": "english"}, 409),
        ({"code": "ENG"}, 409),
        ({"name": None}, 422),
        ({"is_active": None}, 422),
        ({}, 422),
        ({"school_id": "x"}, 422),
    ],
)
def test_impossible_changes_are_refused(school, body, status):
    response = school["admin"].patch(f"{SUBJECTS}/{school['maths']}", json=body)

    assert response.status_code == status


def test_another_schools_subject_cannot_be_changed(db_app, school):
    response = school["admin"].patch(f"{SUBJECTS}/{school['subject_b']}", json={"name": "X"})

    assert response.status_code == 404
    assert _events(db_app, "subject.updated") == [("denied", "subject")]


# The subjects a class takes.


def test_an_admin_chooses_the_subjects_a_class_takes(db_app, school):
    admin = school["admin"]

    first = _add(admin, school["g4"], school["maths"])
    second = _add(admin, school["g4"], school["english"])

    assert first.status_code == second.status_code == 201
    assert second.get_json()["class"]["name"] == "Grade 4 East"
    assert _summary(second) == {"English": [], "Mathematics": []}
    assert _events(db_app, "class_subject.added") == [("success", "class")] * 2
    # Another class is not affected.
    assert _summary(admin.get(f"{CLASSES}/{school['g5']}/subjects")) == {}


def test_the_principal_sees_a_classs_subjects_and_teachers(db_app, g4_maths):
    principal = _client_for(db_app, "principal@example.com")

    response = principal.get(f"{CLASSES}/{g4_maths['g4']}/subjects")

    assert response.status_code == 200
    assert _summary(response) == {"Mathematics": ["Teacher Person"]}
    teacher = response.get_json()["subjects"][0]["teachers"][0]
    assert teacher == {
        "membership_id": g4_maths["members"]["teacher"],
        "full_name": "Teacher Person",
        "is_active": True,
    }


def test_a_class_takes_a_subject_once(g4_maths):
    response = _add(g4_maths["admin"], g4_maths["g4"], g4_maths["maths"])

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == "This class already takes Mathematics."


def test_an_inactive_subject_cannot_be_added_but_stays_where_it_is(g4_maths):
    s = g4_maths
    admin = s["admin"]
    admin.patch(f"{SUBJECTS}/{s['maths']}", json={"is_active": False})

    response = _add(admin, s["g5"], s["maths"])

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "Mathematics is inactive. Make it active on the Subjects page first."
    )
    kept = admin.get(f"{CLASSES}/{s['g4']}/subjects").get_json()["subjects"]
    assert [(c["subject"]["name"], c["subject"]["is_active"]) for c in kept] == [
        ("Mathematics", False)
    ]


def test_another_schools_class_or_subject_cannot_be_used(db_app, school):
    admin = school["admin"]

    assert _add(admin, school["g4"], school["subject_b"]).status_code == 422
    assert _add(admin, school["class_b"], school["maths"]).status_code == 404
    assert admin.get(f"{CLASSES}/{school['class_b']}/subjects").status_code == 404
    assert _events(db_app, "class_subject.added") == [("denied", "class")]
    assert _events(db_app, "class_subjects.read") == [("denied", "class")]


def test_removing_a_subject_from_a_class_removes_its_teachers_there(db_app, g4_maths):
    s = g4_maths
    admin = s["admin"]
    _assign(admin, s["g4"], s["maths"], s["members"]["teacher2"])

    response = admin.delete(f"{CLASSES}/{s['g4']}/subjects/{s['maths']}")

    assert response.status_code == 200
    assert _summary(response) == {}
    assert _events(db_app, "class_subject.removed") == [("success", "class")]
    # The subject itself is kept, and can be taken again with no teachers.
    again = _add(admin, s["g4"], s["maths"])
    assert _summary(again) == {"Mathematics": []}


def test_a_subject_the_class_does_not_take_cannot_be_removed(school):
    response = school["admin"].delete(f"{CLASSES}/{school['g4']}/subjects/{school['maths']}")

    assert response.status_code == 404
    assert response.get_json()["error"]["message"] == "This class does not take that subject."


# Who teaches a subject to a class.


def test_a_subject_can_have_several_teachers(db_app, g4_maths):
    s = g4_maths

    response = _assign(s["admin"], s["g4"], s["maths"], s["members"]["teacher2"])

    assert response.status_code == 201
    assert _summary(response) == {"Mathematics": ["Second Teacher", "Teacher Person"]}
    assert _events(db_app, "subject_teacher.added") == [("success", "class")] * 2


def test_a_teacher_is_assigned_once(g4_maths):
    s = g4_maths

    response = _assign(s["admin"], s["g4"], s["maths"], s["members"]["teacher"])

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "already_assigned"


@pytest.mark.parametrize("who", ["principal", "teacher_b", "inactive", "unknown"])
def test_only_active_teachers_of_the_school_can_teach(db_app, g4_maths, who):
    s = g4_maths
    membership = s["members"].get(who, "00000000-0000-0000-0000-000000000000")
    if who == "inactive":
        membership = s["members"]["teacher2"]
        with db_app.app_context():
            db.session.execute(
                update(Membership).where(Membership.id == membership).values(is_active=False)
            )
            db.session.commit()

    response = _assign(s["admin"], s["g4"], s["maths"], membership)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "Choose an active teacher of this school."
    )


def test_a_teacher_needs_a_subject_the_class_takes(school):
    response = _assign(
        school["admin"], school["g4"], school["english"], school["members"]["teacher"]
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["message"] == "This class does not take that subject."


def test_a_subject_teacher_is_removed(db_app, g4_maths):
    s = g4_maths
    teacher = f"{CLASSES}/{s['g4']}/subjects/{s['maths']}/teachers/{s['members']['teacher']}"

    removed = s["admin"].delete(teacher)
    again = s["admin"].delete(teacher)

    assert removed.status_code == 200
    assert _summary(removed) == {"Mathematics": []}
    assert again.status_code == 404
    assert _events(db_app, "subject_teacher.removed") == [("success", "class")]


# What a subject teacher sees.


def _my_classes(client, year):
    response = client.get(CLASSES, query_string={"academic_year_id": year})
    assert response.status_code == 200
    return {
        c["name"]: (c["is_class_teacher"], c["my_subjects"]) for c in response.get_json()["classes"]
    }


def test_a_subject_teacher_sees_the_class_and_their_subjects(db_app, g4_maths):
    s = g4_maths
    admin = s["admin"]
    _add(admin, s["g4"], s["english"])
    _assign(admin, s["g4"], s["english"], s["members"]["teacher"])
    _add(admin, s["g5"], s["english"])
    _assign(admin, s["g5"], s["english"], s["members"]["teacher2"])
    assert (
        admin.post(
            f"{CLASSES}/{s['g5']}/teachers", json={"membership_id": s["members"]["teacher"]}
        ).status_code
        == 201
    )

    teacher = _client_for(db_app, "teacher@example.com")
    second = _client_for(db_app, "teacher2@example.com")

    assert _my_classes(teacher, s["year"]) == {
        "Grade 4 East": (False, ["English", "Mathematics"]),
        "Grade 5": (True, []),
    }
    assert _my_classes(second, s["year"]) == {"Grade 5": (False, ["English"])}


def test_staff_who_see_every_class_get_no_personal_details(db_app, g4_maths):
    principal = _client_for(db_app, "principal@example.com")

    assert _my_classes(principal, g4_maths["year"]) == {
        "Grade 4 East": (False, []),
        "Grade 5": (False, []),
    }


def test_a_subject_teacher_reads_names_and_numbers_but_takes_no_register(db_app, g4_maths):
    s = g4_maths
    teacher = _client_for(db_app, "teacher@example.com")

    students = teacher.get(f"{CLASSES}/{s['g4']}/students")
    register = teacher.get(f"{CLASSES}/{s['g4']}/attendance/2027-02-01")
    other = teacher.get(f"{CLASSES}/{s['g5']}/students")

    assert students.status_code == 200
    assert [set(p) for p in students.get_json()["students"]] == [
        {"id", "admission_number", "full_name"}
    ] * 2
    assert register.status_code == 404
    assert other.status_code == 404


def test_a_teacher_loses_the_class_when_removed_or_made_inactive(db_app, g4_maths):
    s = g4_maths
    teacher = _client_for(db_app, "teacher@example.com")
    path = f"{CLASSES}/{s['g4']}/subjects/{s['maths']}/teachers/{s['members']['teacher']}"
    assert teacher.get(f"{CLASSES}/{s['g4']}/students").status_code == 200

    with db_app.app_context():
        db.session.execute(
            update(Membership)
            .where(Membership.id == s["members"]["teacher"])
            .values(is_active=False)
        )
        db.session.commit()
    assert teacher.get(f"{CLASSES}/{s['g4']}/students").status_code == 403

    with db_app.app_context():
        db.session.execute(
            update(Membership)
            .where(Membership.id == s["members"]["teacher"])
            .values(is_active=True)
        )
        db.session.commit()
    teacher = _client_for(db_app, "teacher@example.com")
    assert teacher.get(f"{CLASSES}/{s['g4']}/students").status_code == 200
    assert s["admin"].delete(path).status_code == 200
    assert _my_classes(teacher, s["year"]) == {}
    assert teacher.get(f"{CLASSES}/{s['g4']}/students").status_code == 404
