"""The attendance API: taking, correcting and summarising registers (D1)."""

from datetime import date

import pytest
from sqlalchemy import select

from app.api.v1 import academic_years as years_api
from app.api.v1 import attendance as module
from app.extensions import db
from app.models import AuditEvent, User

YEARS = "/api/v1/school/academic-years"
CLASSES = "/api/v1/school/classes"
STUDENTS = "/api/v1/school/students"
OVERVIEW = "/api/v1/school/attendance"
PASSWORD = "correct horse battery"
ROLES = ("school_admin", "principal", "registrar", "teacher", "finance_officer", "guardian")
NIL = "00000000-0000-0000-0000-000000000000"
TODAY = "2027-02-10"  # A Wednesday in Term 1.
TERMS = [
    {"number": 1, "starts_on": "2027-01-11", "ends_on": "2027-04-01"},
    {"number": 2, "starts_on": "2027-04-26", "ends_on": "2027-07-30"},
]


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


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(years_api, "school_today", lambda: date.fromisoformat(TODAY))


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A: one person per role (the teacher teaches Grade 4 East) and a
    second teacher; a year 2027 with Terms 1 and 2; Grade 4 East with Amani,
    Baraka, Chausiku and an inactive Former Pupil; Grade 5 with Dalila.
    School B: a year with a term, and a class."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    members = {}
    for role in ROLES:
        user_id = make_user(email=f"{role}@example.com")
        with db_app.app_context():
            db.session.get(User, user_id).full_name = f"{role} person"
            db.session.commit()
        members[role] = add_member(user_id, school_a, role)
    add_member(make_user(email="teacher2@example.com"), school_a, "teacher")
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    admin_b = _client_for(db_app, "admin.b@example.com")
    year_b = {"name": "2027", "starts_on": "2027-01-04", "ends_on": "2027-11-26", "terms": TERMS}
    year_b = _id(admin_b.post(YEARS, json=year_b), "academic_year")
    class_b = _id(
        admin_b.post(CLASSES, json={"academic_year_id": year_b, "grade": "grade_4"}), "class"
    )

    admin = _client_for(db_app, "school_admin@example.com")
    year = {"name": "2027", "starts_on": "2027-01-04", "ends_on": "2027-11-26", "terms": TERMS}
    year = _id(admin.post(YEARS, json=year), "academic_year")
    classes = {
        key: _id(admin.post(CLASSES, json={"academic_year_id": year, **body}), "class")
        for key, body in [("g4", {"grade": "grade_4", "stream": "East"}),
                          ("g5", {"grade": "grade_5"})]
    }  # fmt: skip
    students = {
        n: _id(admin.post(STUDENTS, json={"admission_number": f"ADM-{n}", "full_name": name}),
               "student")
        for n, name in [(1, "Amani Pupil"), (2, "Baraka Pupil"), (3, "Chausiku Pupil"),
                        (4, "Dalila Pupil"), (9, "Former Pupil")]
    }  # fmt: skip
    s = students
    for class_key, ids in [("g4", [s[1], s[2], s[3], s[9]]), ("g5", [s[4]])]:
        enrolled = admin.post(f"{CLASSES}/{classes[class_key]}/students", json={"student_ids": ids})
        assert enrolled.status_code == 201
    assert admin.post(f"{STUDENTS}/{s[9]}/deactivate").status_code == 200
    assigned = admin.post(
        f"{CLASSES}/{classes['g4']}/teachers", json={"membership_id": str(members["teacher"])}
    )
    assert assigned.status_code == 201
    return {"admin": admin, "year": year, **classes, "students": s, "class_b": class_b}


def _path(class_id, day=TODAY):
    return f"{CLASSES}/{class_id}/attendance/{day}"


def _marks(school, overrides=None, keys=(1, 2, 3)):
    """A register for Grade 4 East: everyone present unless overridden."""
    overrides = overrides or {}
    marks = []
    for n in keys:
        status, reason = overrides.get(n, ("present", None))
        marks.append({"student_id": school["students"][n], "status": status, "reason": reason})
    return {"marks": marks}


def _save(client, school, day=TODAY, overrides=None, keys=(1, 2, 3), class_key="g4"):
    return client.put(_path(school[class_key], day), json=_marks(school, overrides, keys))


def _statuses(response):
    return [
        (m["student"]["full_name"], m["status"], m["reason"]) for m in response.get_json()["marks"]
    ]


@pytest.fixture
def teacher(db_app):
    return _client_for(db_app, "teacher@example.com")


# Reading registers.


def test_reading_needs_a_login(db_app, school):
    assert db_app.test_client().get(_path(school["g4"])).status_code == 401


@pytest.mark.parametrize("role", ["registrar", "finance_officer", "guardian"])
def test_other_roles_read_no_registers(db_app, school, role):
    client = _client_for(db_app, f"{role}@example.com")

    assert client.get(_path(school["g4"])).status_code == 403
    assert client.get(f"{CLASSES}/{school['g4']}/attendance?term=1").status_code == 403
    assert client.get(OVERVIEW).status_code == 403


@pytest.mark.parametrize("role", ["school_admin", "principal"])
def test_a_register_not_taken_lists_the_active_students_as_present(db_app, school, role):
    response = _client_for(db_app, f"{role}@example.com").get(_path(school["g5"]))

    assert response.status_code == 200
    body = response.get_json()
    assert (body["class"]["name"], body["date"], body["term_number"]) == ("Grade 5", TODAY, 1)
    assert body["taken"] is False
    assert body["taken_by"] is None
    assert _statuses(response) == [("Dalila Pupil", "present", None)]
    # Administrators may take it; principals only read.
    assert body["editable"] is (role == "school_admin")
    assert body["teacher_can_change_until"] is None


def test_former_students_are_not_in_a_new_register(school):
    names = [name for name, _, _ in _statuses(school["admin"].get(_path(school["g4"])))]

    assert names == ["Amani Pupil", "Baraka Pupil", "Chausiku Pupil"]


def test_a_teacher_reads_only_their_classes_registers_with_names_and_numbers(
    db_app, school, teacher
):
    response = teacher.get(_path(school["g4"]))

    assert response.status_code == 200
    assert response.get_json()["marks"][0]["student"] == {
        "id": school["students"][1],
        "admission_number": "ADM-1",
        "full_name": "Amani Pupil",
    }
    assert response.get_json()["editable"] is True
    assert response.get_json()["teacher_can_change_until"] == "2027-02-17"
    # Not their class: exactly like a class that does not exist.
    refused = teacher.get(_path(school["g5"]))
    assert (refused.status_code, refused.get_json()["error"]["message"]) == (
        404,
        "Class not found.",
    )
    assert _client_for(db_app, "teacher2@example.com").get(_path(school["g4"])).status_code == 404
    assert _events(db_app, "attendance.read") == [("denied", "class")] * 2


def test_another_schools_class_is_invisible(db_app, school):
    assert school["admin"].get(_path(school["class_b"])).status_code == 404
    assert _save(school["admin"], school, class_key="class_b").status_code == 404
    assert _events(db_app, "attendance.saved") == [("denied", "class")]


# Which days.


@pytest.mark.parametrize(
    ("day", "message"),
    [
        ("2027-02-11", "Attendance cannot be taken for a day that has not happened yet."),
        ("2027-01-06", "2027-01-06 is not inside a term of the school year 2027."),  # holiday
        ("2027-01-02", "2027-01-02 is not inside a term of the school year 2027."),  # before
    ],
)
def test_only_term_days_up_to_today_have_registers(school, day, message):
    admin = school["admin"]

    for response in (admin.get(_path(school["g4"], day)), _save(admin, school, day)):
        assert response.status_code == 422
        assert response.get_json()["error"]["details"][0]["message"] == message


@pytest.mark.parametrize("day", ["2027-02-30", "20270210", "today", "2027-2-10"])
def test_the_date_must_be_a_real_date(school, day):
    response = school["admin"].get(_path(school["g4"], day))

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "The date must be a real date written YYYY-MM-DD."
    )


def test_weekends_inside_a_term_are_allowed(school):
    assert _save(school["admin"], school, "2027-02-06").status_code == 201  # Saturday


# Taking a register.


def test_a_teacher_takes_their_classes_register(db_app, school, teacher):
    response = _save(teacher, school, overrides={2: ("absent", "sick"), 3: ("late", None)})

    assert response.status_code == 201
    body = response.get_json()
    assert body["taken"] is True
    assert (body["taken_by"], body["updated_by"]) == ("teacher person", "teacher person")
    assert _statuses(response) == [
        ("Amani Pupil", "present", None),
        ("Baraka Pupil", "absent", "sick"),
        ("Chausiku Pupil", "late", None),
    ]
    assert _events(db_app, "attendance.taken") == [("success", "attendance_register")]
    # Reading it back gives the same.
    assert _statuses(school["admin"].get(_path(school["g4"]))) == _statuses(response)


@pytest.mark.parametrize("role", ["principal", "registrar", "finance_officer"])
def test_other_roles_take_no_registers(db_app, school, role):
    response = _save(_client_for(db_app, f"{role}@example.com"), school)

    assert response.status_code == 403
    assert _events(db_app, "attendance.record") == [("denied", None)]


def test_a_teacher_cannot_take_another_classes_register(db_app, school, teacher):
    assert _save(teacher, school, keys=(4,), class_key="g5").status_code == 404
    assert _save(_client_for(db_app, "teacher2@example.com"), school).status_code == 404
    assert _events(db_app, "attendance.saved") == [("denied", "class")] * 2


@pytest.mark.parametrize(
    "keys",
    [(1, 2), (1, 2, 3, 4), (1, 2, 3, 9)],
    ids=["one missing", "another class's student", "former student"],
)
def test_a_new_register_covers_exactly_the_classes_students(db_app, school, keys):
    response = _save(school["admin"], school, keys=keys)

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "class_list_changed"
    assert school["admin"].get(_path(school["g4"])).get_json()["taken"] is False
    assert _events(db_app, "attendance.taken") == []


@pytest.mark.parametrize(
    ("mark", "text"),
    [
        ({"status": "absent"}, "Choose a reason for each absence"),
        ({"status": "present", "reason": "sick"}, "Only an absence can have a reason."),
        ({"status": "late", "reason": "unknown"}, "Only an absence can have a reason."),
        ({"status": "absent", "reason": "had a fever"}, "Input should be"),
        ({"status": "excused"}, "Input should be"),
        ({"status": "present", "note": "x"}, "Extra inputs"),
    ],
)
def test_marks_must_make_sense(school, mark, text):
    body = _marks(school)
    body["marks"][0] = {"student_id": school["students"][1], **mark}

    response = school["admin"].put(_path(school["g4"]), json=body)

    assert response.status_code == 422
    assert text in " ".join(d["message"] for d in response.get_json()["error"]["details"])


@pytest.mark.parametrize(
    ("body", "text"),
    [
        ({"marks": []}, "at least 1 item"),
        ({"marks": [{"student_id": NIL, "status": "present"}] * 2}, "only once"),
        ({}, "Field required"),
    ],
)
def test_impossible_registers_are_refused(school, body, text):
    response = school["admin"].put(_path(school["g4"]), json=body)

    assert response.status_code == 422
    assert text in " ".join(d["message"] for d in response.get_json()["error"]["details"])


def test_a_register_saved_twice_at_once_is_kept_once(db_app, school, teacher, monkeypatch):
    assert _save(teacher, school).status_code == 201
    # The second save looked before the first was saved.
    monkeypatch.setattr(module, "_find_register", lambda *args, **kwargs: None)

    response = _save(school["admin"], school, overrides={1: ("absent", "unknown")})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "register_already_taken"
    monkeypatch.undo()
    monkeypatch.setattr(years_api, "school_today", lambda: date.fromisoformat(TODAY))
    assert _statuses(school["admin"].get(_path(school["g4"])))[0][1] == "present"


# Correcting a register.


def test_a_correction_changes_only_what_changed_and_is_audited(db_app, school, teacher):
    assert _save(teacher, school).status_code == 201

    response = _save(school["admin"], school, overrides={1: ("absent", "permission")})

    assert response.status_code == 200
    body = response.get_json()
    assert (body["taken_by"], body["updated_by"]) == ("teacher person", "school_admin person")
    assert _statuses(response)[0] == ("Amani Pupil", "absent", "permission")
    assert _events(db_app, "attendance.corrected") == [("success", "attendance_register")]
    assert _events(db_app, "attendance.mark_changed") == [("success", "student")]

    # Saving the same marks again changes nothing and records nothing.
    again = _save(school["admin"], school, overrides={1: ("absent", "permission")})
    assert again.status_code == 200
    assert len(_events(db_app, "attendance.corrected")) == 1


def test_a_register_keeps_its_students_when_the_class_changes(db_app, school):
    admin, s = school["admin"], school["students"]
    assert _save(admin, school, "2027-02-09").status_code == 201
    # Amani moves to Grade 5 and Dalila joins Grade 4 East.
    moved = admin.patch(
        f"{CLASSES}/{school['g4']}/students/{s[1]}", json={"class_id": school["g5"]}
    )
    assert moved.status_code == 200
    assert admin.delete(f"{CLASSES}/{school['g5']}/students/{s[4]}").status_code == 200
    joined = admin.post(f"{CLASSES}/{school['g4']}/students", json={"student_ids": [s[4]]})
    assert joined.status_code == 201

    # The saved register still lists Amani, not Dalila.
    names = [name for name, _, _ in _statuses(admin.get(_path(school["g4"], "2027-02-09")))]
    assert names == ["Amani Pupil", "Baraka Pupil", "Chausiku Pupil"]
    # A correction keeps those students...
    kept = _save(admin, school, "2027-02-09", overrides={1: ("absent", "unknown")})
    assert kept.status_code == 200
    # ...and cannot swap in today's class list.
    swapped = _save(admin, school, "2027-02-09", keys=(2, 3, 4))
    assert swapped.status_code == 409
    assert swapped.get_json()["error"]["code"] == "register_students_differ"
    # Today's new register is for today's class.
    assert _save(admin, school, keys=(2, 3, 4)).status_code == 201


@pytest.mark.parametrize(("day", "allowed"), [("2027-02-03", True), ("2027-02-02", False)])
def test_teachers_change_only_the_last_seven_days(db_app, school, teacher, day, allowed):
    response = _save(teacher, school, day)

    if allowed:
        assert response.status_code == 201
        return
    assert response.status_code == 403
    assert response.get_json()["error"] == {
        "code": "too_late_to_change",
        "message": "Teachers can take and correct registers for today and the previous 7 days. "
        "Ask a school administrator to change older ones.",
        "request_id": response.get_json()["error"]["request_id"],
    }
    assert _events(db_app, "attendance.saved") == [("denied", "class")]
    # The teacher still reads it, but may not change it; an administrator may.
    assert teacher.get(_path(school["g4"], day)).get_json()["editable"] is False
    assert _save(school["admin"], school, day).status_code == 201
    old = teacher.get(_path(school["g4"], day)).get_json()
    assert (old["taken"], old["editable"], old["teacher_can_change_until"]) == (
        True,
        False,
        "2027-02-09",
    )
    assert _save(teacher, school, day).status_code == 403


# Term summaries.


def test_a_term_summary_counts_each_day_and_each_student(db_app, school, teacher):
    admin = school["admin"]
    assert _save(admin, school, "2027-02-08", {2: ("absent", "sick")}).status_code == 201
    assert (
        _save(
            admin, school, "2027-02-09", {2: ("absent", "unknown"), 3: ("late", None)}
        ).status_code
        == 201
    )
    assert _save(admin, school, "2027-04-26", keys=(1, 2, 3)).status_code == 422  # future
    # Amani leaves the class; her marks stay in the summary.
    assert (
        admin.delete(f"{CLASSES}/{school['g4']}/students/{school['students'][1]}").status_code
        == 200
    )

    response = teacher.get(f"{CLASSES}/{school['g4']}/attendance?term=1")

    assert response.status_code == 200
    body = response.get_json()
    assert body["term"] == {"number": 1, "starts_on": "2027-01-11", "ends_on": "2027-04-01"}
    no_reasons = {"sick": 0, "permission": 0, "unknown": 0}
    assert body["registers"] == [
        {"date": "2027-02-08", "present": 2, "absent": 1, "late": 0,
         "absent_by_reason": {**no_reasons, "sick": 1}},
        {"date": "2027-02-09", "present": 1, "absent": 1, "late": 1,
         "absent_by_reason": {**no_reasons, "unknown": 1}},
    ]  # fmt: skip
    rows = {r["student"]["full_name"]: r for r in body["students"]}
    assert list(rows) == ["Amani Pupil", "Baraka Pupil", "Chausiku Pupil"]
    assert (rows["Amani Pupil"]["in_class"], rows["Amani Pupil"]["present"]) == (False, 2)
    assert rows["Baraka Pupil"]["absent"] == 2
    assert rows["Baraka Pupil"]["absent_by_reason"] == {"sick": 1, "permission": 0, "unknown": 1}
    assert (rows["Chausiku Pupil"]["present"], rows["Chausiku Pupil"]["late"]) == (1, 1)
    assert set(rows["Chausiku Pupil"]["student"]) == {"id", "admission_number", "full_name"}

    # Term 2 has no registers yet; its students are listed with zeros.
    term_2 = teacher.get(f"{CLASSES}/{school['g4']}/attendance?term=2").get_json()
    assert term_2["registers"] == []
    assert [r["present"] for r in term_2["students"]] == [0, 0]
    # Not their class.
    assert teacher.get(f"{CLASSES}/{school['g5']}/attendance?term=1").status_code == 404


@pytest.mark.parametrize(("query", "status"), [("term=3", 404), ("term=4", 422), ("", 422)])
def test_a_summary_needs_a_term_of_the_year(school, query, status):
    response = school["admin"].get(f"{CLASSES}/{school['g4']}/attendance?{query}")

    assert response.status_code == status


# The school's overview of a day.


@pytest.mark.parametrize("role", ["school_admin", "principal"])
def test_the_overview_shows_which_classes_were_taken(db_app, school, role):
    assert _save(school["admin"], school, overrides={2: ("absent", "sick")}).status_code == 201

    response = _client_for(db_app, f"{role}@example.com").get(OVERVIEW)

    assert response.status_code == 200
    body = response.get_json()
    assert (body["date"], body["academic_year_id"], body["term_number"]) == (
        TODAY,
        school["year"],
        1,
    )
    summary = [(c["class"]["name"], c["taken"], c["present"], c["absent"]) for c in body["classes"]]
    assert summary == [("Grade 4 East", True, 2, 1), ("Grade 5", False, 0, 0)]


def test_teachers_have_no_school_overview(db_app, school, teacher):
    assert teacher.get(OVERVIEW).status_code == 403


@pytest.mark.parametrize(
    ("day", "status", "term", "classes"),
    [
        ("2027-01-06", 200, None, 2),  # holiday: the classes, none taken
        ("2026-12-01", 200, None, 0),  # no school year
        ("2027-02-11", 422, None, None),  # the future
        ("nope", 422, None, None),
    ],
)
def test_the_overview_of_another_day(school, day, status, term, classes):
    response = school["admin"].get(OVERVIEW, query_string={"date": day})

    assert response.status_code == status
    if status == 200:
        body = response.get_json()
        assert body["term_number"] == term
        assert len(body["classes"]) == classes
        assert not any(c["taken"] for c in body["classes"])
