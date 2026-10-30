"""The assessments and marks API (D4)."""

from datetime import date

import pytest
from sqlalchemy import select

from app.api.v1 import academic_years as years_api
from app.extensions import db
from app.models import AuditEvent

PASSWORD = "correct horse battery"
API = "/api/v1/school"
TODAY = "2027-03-10"  # In Term 1.
YEAR = {
    "name": "2027",
    "starts_on": "2027-01-04",
    "ends_on": "2027-11-26",
    "terms": [
        {"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"},
        {"number": 2, "starts_on": "2027-05-03", "ends_on": "2027-08-06"},
    ],
}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(years_api, "school_today", lambda: date.fromisoformat(TODAY))


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


def _ok(response, status=201):
    assert response.status_code == status, response.get_json()
    return response.get_json()


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A: one person per role and four teachers. 2027 has Terms 1 and
    2. Grade 4 East (Amani, Baraka, Chausiku) takes Mathematics, taught by
    `maths`, and English, taught by `english`; `form` is its class teacher.
    Grade 5 (Dalila) takes Mathematics with no teacher. School B: an
    administrator and a class taking a subject."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    members = {}
    for role in ("school_admin", "principal", "registrar", "finance_officer", "guardian"):
        members[role] = add_member(make_user(email=f"{role}@example.com"), school_a, role)
    for name in ("maths", "english", "form", "idle"):
        members[name] = add_member(make_user(email=f"{name}@example.com"), school_a, "teacher")
    members = {key: str(value) for key, value in members.items()}
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    def setup(client):
        year = _ok(client.post(f"{API}/academic-years", json=YEAR))["academic_year"]["id"]
        made = {}
        for key, grade, stream in (("g4", "grade_4", "East"), ("g5", "grade_5", None)):
            body = {"academic_year_id": year, "grade": grade, "stream": stream}
            made[key] = _ok(client.post(f"{API}/classes", json=body))["class"]["id"]
        for key, name in (("maths", "Mathematics"), ("english", "English")):
            made[key] = _ok(client.post(f"{API}/subjects", json={"name": name}))["subject"]["id"]
        return made

    admin_b = _client_for(db_app, "admin.b@example.com")
    b = setup(admin_b)
    _ok(admin_b.post(f"{API}/classes/{b['g4']}/subjects", json={"subject_id": b["maths"]}))

    admin = _client_for(db_app, "school_admin@example.com")
    a = setup(admin)
    students = {}
    for n, name in enumerate(("Amani Pupil", "Baraka Pupil", "Chausiku Pupil", "Dalila Pupil")):
        body = {"admission_number": f"ADM-{n + 1}", "full_name": name}
        students[name.split()[0]] = _ok(admin.post(f"{API}/students", json=body))["student"]["id"]
    g4_students = [students[n] for n in ("Amani", "Baraka", "Chausiku")]
    _ok(admin.post(f"{API}/classes/{a['g4']}/students", json={"student_ids": g4_students}))
    _ok(admin.post(f"{API}/classes/{a['g5']}/students", json={"student_ids": [students["Dalila"]]}))
    for class_key, subject_key, teacher in (
        ("g4", "maths", "maths"),
        ("g4", "english", "english"),
        ("g5", "maths", None),
    ):
        _ok(
            admin.post(
                f"{API}/classes/{a[class_key]}/subjects", json={"subject_id": a[subject_key]}
            )
        )
        if teacher:
            path = f"{API}/classes/{a[class_key]}/subjects/{a[subject_key]}/teachers"
            _ok(admin.post(path, json={"membership_id": members[teacher]}))
    _ok(admin.post(f"{API}/classes/{a['g4']}/teachers", json={"membership_id": members["form"]}))
    return {"admin": admin, "members": members, "students": students, "b": b, **a}


def _assessments(school, class_key="g4", subject_key="maths"):
    return f"{API}/classes/{school[class_key]}/subjects/{school[subject_key]}/assessments"


def _create(client, school, name="Mid-term", class_key="g4", subject_key="maths", **fields):
    body = {"term": 1, "name": name, "max_score": 50, "held_on": "2027-03-01", **fields}
    return client.post(_assessments(school, class_key, subject_key), json=body)


@pytest.fixture
def midterm(school):
    """Grade 4 East's Mathematics Mid-term (out of 50), created by its teacher."""
    return _ok(_create(school["maths_client"], school))["assessment"]["id"]


@pytest.fixture(autouse=True)
def _clients(request, db_app):
    # Logged-in clients for the teachers, made only for tests using `school`.
    if "school" in request.fixturenames:
        school = request.getfixturevalue("school")
        for name in ("maths", "english", "form", "idle", "principal", "registrar"):
            school[f"{name}_client"] = _client_for(db_app, f"{name}@example.com")


def _marks(client, assessment, *entries):
    """Save marks: each entry is (student_id, score) or (student_id, "absent")."""
    marks = [
        {"student_id": s, "did_not_sit": True}
        if score == "absent"
        else {"student_id": s, "score": score}
        for s, score in entries
    ]
    return client.put(f"{API}/assessments/{assessment}/marks", json={"marks": marks})


def _sheet(response):
    """{"Amani Pupil": 12.5 / "absent" / None, ...} from a mark sheet."""
    return {
        s["full_name"]: "absent" if s["did_not_sit"] else s["score"]
        for s in response.get_json()["students"]
    }


# Who may see and change marks.


def test_reading_needs_a_login(db_app, school):
    assert db_app.test_client().get(_assessments(school)).status_code == 401


@pytest.mark.parametrize("role", ["registrar", "finance_officer", "guardian"])
def test_other_roles_see_no_marks(db_app, school, role):
    client = _client_for(db_app, f"{role}@example.com")

    assert client.get(_assessments(school)).status_code == 403
    assert client.get(f"{API}/classes/{school['g4']}/marks?term=1").status_code == 403
    assert _events(db_app, "marks.read") == [("denied", None)] * 2


def test_a_subject_teacher_adds_assessments_for_their_subject_only(db_app, school):
    maths, english = school["maths_client"], school["english_client"]

    created = _create(maths, school)
    refused = _create(english, school, "English try")

    assert created.status_code == 201
    assert refused.status_code == 404
    assert english.get(_assessments(school)).status_code == 404
    assert _events(db_app, "assessment.created") == [("success", "assessment"), ("denied", "class")]
    listed = _ok(maths.get(_assessments(school)), 200)
    assert listed["can_record"] is True
    assert listed["students"] == 3
    assert [a["name"] for a in listed["assessments"]] == ["Mid-term"]


def test_the_class_teacher_reads_every_subject_but_changes_nothing(db_app, school, midterm):
    form = school["form_client"]

    listed = _ok(form.get(_assessments(school)), 200)
    sheet = form.get(f"{API}/assessments/{midterm}/marks")

    assert listed["can_record"] is False
    assert sheet.status_code == 200
    assert sheet.get_json()["can_record"] is False
    assert _create(form, school, "Class teacher's").status_code == 404
    assert _marks(form, midterm, (school["students"]["Amani"], 10)).status_code == 404
    assert form.patch(f"{API}/assessments/{midterm}", json={"name": "X"}).status_code == 404
    assert form.get(f"{API}/classes/{school['g4']}/marks?term=1").status_code == 200


def test_a_teacher_of_neither_sees_nothing(db_app, school, midterm):
    idle = school["idle_client"]

    assert idle.get(_assessments(school)).status_code == 404
    assert idle.get(f"{API}/assessments/{midterm}/marks").status_code == 404
    assert idle.get(f"{API}/classes/{school['g4']}/marks?term=1").status_code == 404
    assert _events(db_app, "assessments.read") == [("denied", "class"), ("denied", "assessment")]


def test_a_subject_teacher_does_not_see_the_class_overview(school):
    response = school["maths_client"].get(f"{API}/classes/{school['g4']}/marks?term=1")

    assert response.status_code == 404


def test_a_principal_reads_everything_and_changes_nothing(db_app, school, midterm):
    principal = school["principal_client"]

    assert principal.get(_assessments(school)).get_json()["can_record"] is False
    assert principal.get(f"{API}/assessments/{midterm}/marks").status_code == 200
    assert principal.get(f"{API}/classes/{school['g4']}/marks?term=1").status_code == 200
    assert _create(principal, school, "Principal's").status_code == 403
    assert _marks(principal, midterm, (school["students"]["Amani"], 1)).status_code == 403
    assert principal.post(f"{API}/assessments/{midterm}/lock").status_code == 403


def test_another_schools_classes_and_assessments_are_invisible(db_app, school, midterm):
    admin_b = _client_for(db_app, "admin.b@example.com")
    b = school["b"]
    path = f"{API}/classes/{b['g4']}/subjects/{b['maths']}/assessments"

    assert school["admin"].get(path).status_code == 404
    assert admin_b.get(f"{API}/assessments/{midterm}/marks").status_code == 404
    assert admin_b.post(f"{API}/assessments/{midterm}/lock").status_code == 404


def test_a_teacher_removed_from_the_subject_loses_it(school, midterm):
    path = f"{API}/classes/{school['g4']}/subjects/{school['maths']}/teachers"
    school["admin"].delete(f"{path}/{school['members']['maths']}")

    assert school["maths_client"].get(f"{API}/assessments/{midterm}/marks").status_code == 404


# Adding and changing assessments.


def test_an_assessment_is_added_with_a_tidy_name(db_app, school):
    response = _create(school["maths_client"], school, "  End   term ", max_score=100)

    assessment = _ok(response)["assessment"]
    assert {k: assessment[k] for k in ("term", "name", "max_score", "held_on", "is_locked")} == {
        "term": 1,
        "name": "End term",
        "max_score": 100,
        "held_on": "2027-03-01",
        "is_locked": False,
    }
    assert assessment["marks_entered"] == 0
    assert _events(db_app, "assessment.created") == [("success", "assessment")]


def test_a_name_is_used_once_per_subject_and_term(school, midterm):
    maths = school["maths_client"]

    again = _create(maths, school, "MID-TERM")
    next_term = _create(maths, school, "Mid-term", term=2, held_on="2027-03-10")

    assert again.status_code == 409
    assert again.get_json()["error"]["message"] == "This subject already has MID-TERM in this term."
    # Term 2 has not started yet (today is in Term 1), so its date is refused.
    assert next_term.status_code == 422


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"term": 3}, "Grade 4 East's school year has no Term 3."),
        ({"held_on": "2027-01-03"}, "The date must be inside Term 1 (2027-01-04 to 2027-04-01)."),
        ({"held_on": "2027-03-11"}, "The date cannot be in the future."),
    ],
)
def test_the_term_and_date_must_fit(school, fields, message):
    response = _create(school["maths_client"], school, **fields)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == message


@pytest.mark.parametrize(
    "fields",
    [{"name": "  "}, {"name": "N" * 61}, {"max_score": 0}, {"max_score": 1001}, {"term": 4}],
)
def test_impossible_assessments_are_refused(school, fields):
    assert _create(school["maths_client"], school, **fields).status_code == 422


def test_an_assessment_is_renamed_and_changed(db_app, school, midterm):
    response = school["maths_client"].patch(
        f"{API}/assessments/{midterm}",
        json={"name": "Mid term", "max_score": 40, "held_on": "2027-02-26"},
    )

    assessment = _ok(response, 200)["assessment"]
    assert (assessment["name"], assessment["max_score"], assessment["held_on"]) == (
        "Mid term",
        40,
        "2027-02-26",
    )
    assert _events(db_app, "assessment.updated") == [("success", "assessment")]


@pytest.mark.parametrize(
    ("body", "status"),
    [({}, 422), ({"name": None}, 422), ({"term": 2}, 422), ({"held_on": "2027-05-04"}, 422)],
)
def test_impossible_changes_are_refused(school, midterm, body, status):
    response = school["maths_client"].patch(f"{API}/assessments/{midterm}", json=body)

    assert response.status_code == status


def test_the_maximum_cannot_drop_below_a_mark(school, midterm):
    maths = school["maths_client"]
    _ok(_marks(maths, midterm, (school["students"]["Amani"], 45.5)), 200)

    response = maths.patch(f"{API}/assessments/{midterm}", json={"max_score": 45})

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "A mark of 45.5 has already been entered: the maximum cannot be lower than that."
    )
    assert maths.patch(f"{API}/assessments/{midterm}", json={"max_score": 46}).status_code == 200


def test_an_assessment_is_deleted_only_without_marks(db_app, school, midterm):
    maths = school["maths_client"]
    _ok(_marks(maths, midterm, (school["students"]["Amani"], 20)), 200)

    refused = maths.delete(f"{API}/assessments/{midterm}")
    _ok(_marks(maths, midterm, (school["students"]["Amani"], None)), 200)
    deleted = maths.delete(f"{API}/assessments/{midterm}")

    assert refused.status_code == 409
    assert refused.get_json()["error"]["message"] == (
        "Mid-term has marks, so it cannot be deleted. Clear them first."
    )
    assert deleted.status_code == 200
    assert _events(db_app, "assessment.deleted") == [("success", "assessment")]
    assert maths.get(f"{API}/assessments/{midterm}/marks").status_code == 404


def test_a_subject_with_assessments_stays_on_its_class(school, midterm):
    path = f"{API}/classes/{school['g4']}/subjects/{school['maths']}"

    response = school["admin"].delete(path)

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == (
        "Mathematics has assessments in this class, so it cannot be removed."
    )


# Locking.


def test_a_locked_assessment_is_changed_only_by_administrators(db_app, school, midterm):
    maths, admin = school["maths_client"], school["admin"]
    amani = school["students"]["Amani"]
    _ok(_marks(maths, midterm, (amani, 30)), 200)

    locked = _ok(admin.post(f"{API}/assessments/{midterm}/lock"), 200)
    refused = _marks(maths, midterm, (amani, 31))
    renamed = maths.patch(f"{API}/assessments/{midterm}", json={"name": "X"})
    deleted = maths.delete(f"{API}/assessments/{midterm}")
    by_admin = _marks(admin, midterm, (amani, 32))

    assert locked["assessment"]["is_locked"] is True
    assert (refused.status_code, renamed.status_code, deleted.status_code) == (403, 403, 403)
    assert refused.get_json()["error"] == {
        "code": "assessment_locked",
        "message": "This assessment is locked. Ask a school administrator to unlock it.",
        "request_id": refused.get_json()["error"]["request_id"],
    }
    assert _sheet(by_admin)["Amani Pupil"] == 32
    assert _events(db_app, "marks.saved")[1] == ("denied", "assessment")

    _ok(admin.post(f"{API}/assessments/{midterm}/unlock"), 200)
    assert _marks(maths, midterm, (amani, 33)).status_code == 200
    assert _events(db_app, "assessment.locked") == [("success", "assessment")]
    assert _events(db_app, "assessment.unlocked") == [("success", "assessment")]


def test_teachers_cannot_lock(db_app, school, midterm):
    response = school["maths_client"].post(f"{API}/assessments/{midterm}/lock")

    assert response.status_code == 403
    assert _events(db_app, "marks.record") == [("denied", None)]


def test_locking_twice_changes_nothing(db_app, school, midterm):
    admin = school["admin"]
    admin.post(f"{API}/assessments/{midterm}/lock")

    assert admin.post(f"{API}/assessments/{midterm}/lock").status_code == 200
    assert _events(db_app, "assessment.locked") == [("success", "assessment")]


# Marks.


def test_a_teacher_enters_scores_and_absences(db_app, school, midterm):
    s = school["students"]

    response = _marks(
        school["maths_client"],
        midterm,
        (s["Amani"], 12.5),
        (s["Baraka"], 50),
        (s["Chausiku"], "absent"),
    )

    assert _sheet(response) == {"Amani Pupil": 12.5, "Baraka Pupil": 50, "Chausiku Pupil": "absent"}
    assert response.get_json()["assessment"]["marks_entered"] == 3
    assert _events(db_app, "mark.changed") == [("success", "student")] * 3
    assert _events(db_app, "marks.saved") == [("success", "assessment")]


def test_students_not_sent_keep_their_marks_and_unchanged_marks_are_not_audited(
    db_app, school, midterm
):
    maths, s = school["maths_client"], school["students"]
    _marks(maths, midterm, (s["Amani"], 10), (s["Baraka"], 20))

    again = _marks(maths, midterm, (s["Amani"], 10.0))
    changed = _marks(maths, midterm, (s["Baraka"], 21))

    assert _sheet(again) == {"Amani Pupil": 10, "Baraka Pupil": 20, "Chausiku Pupil": None}
    assert _sheet(changed)["Baraka Pupil"] == 21
    assert len(_events(db_app, "mark.changed")) == 3
    assert len(_events(db_app, "marks.saved")) == 2


def test_a_mark_is_cleared_by_sending_neither(school, midterm):
    maths, amani = school["maths_client"], school["students"]["Amani"]
    _marks(maths, midterm, (amani, 10))

    response = _marks(maths, midterm, (amani, None))

    assert _sheet(response)["Amani Pupil"] is None
    assert response.get_json()["assessment"]["marks_entered"] == 0


@pytest.mark.parametrize(
    "entry",
    [
        {"score": 12.55},
        {"score": -1},
        {"score": "12"},
        {"score": True},
        {"score": 10, "did_not_sit": True},
        {"score": 1e309},
    ],
)
def test_impossible_marks_are_refused(school, midterm, entry):
    body = {"marks": [{"student_id": school["students"]["Amani"], **entry}]}

    response = school["maths_client"].put(f"{API}/assessments/{midterm}/marks", json=body)

    assert response.status_code == 422


def test_a_score_above_the_maximum_names_the_students(school, midterm):
    s = school["students"]

    response = _marks(school["maths_client"], midterm, (s["Baraka"], 51), (s["Amani"], 50.5))

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "Scores above the maximum of 50: Amani Pupil, Baraka Pupil."
    )


def test_only_students_on_the_sheet_can_be_marked(school, midterm):
    response = _marks(school["maths_client"], midterm, (school["students"]["Dalila"], 10))

    assert response.status_code == 422
    assert response.get_json()["error"]["details"][0]["message"] == (
        "Some of these students are not on this mark sheet. Reload it and try again."
    )


def test_each_student_appears_once(school, midterm):
    amani = school["students"]["Amani"]

    assert _marks(school["maths_client"], midterm, (amani, 1), (amani, 2)).status_code == 422


def test_a_student_who_leaves_keeps_their_mark(school, midterm):
    admin, maths, amani = school["admin"], school["maths_client"], school["students"]["Amani"]
    _marks(maths, midterm, (amani, 40))
    admin.delete(f"{API}/classes/{school['g4']}/students/{amani}")

    sheet = maths.get(f"{API}/assessments/{midterm}/marks").get_json()

    amani_row = next(row for row in sheet["students"] if row["full_name"] == "Amani Pupil")
    assert (amani_row["in_class"], amani_row["score"]) == (False, 40)
    # The mark can still be corrected.
    assert _sheet(_marks(maths, midterm, (amani, 41)))["Amani Pupil"] == 41


# A class's marks for a term.


def test_the_class_overview_shows_every_subject(school, midterm):
    admin, s = school["admin"], school["students"]
    _marks(school["maths_client"], midterm, (s["Amani"], 25), (s["Baraka"], "absent"))
    english = _ok(_create(school["english_client"], school, "Composition", subject_key="english"))

    body = _ok(admin.get(f"{API}/classes/{school['g4']}/marks?term=1"), 200)

    assert body["term"]["number"] == 1
    assert [st["full_name"] for st in body["students"]] == [
        "Amani Pupil",
        "Baraka Pupil",
        "Chausiku Pupil",
    ]
    subjects = {item["subject"]["name"]: item["assessments"] for item in body["subjects"]}
    assert list(subjects) == ["English", "Mathematics"]
    assert subjects["English"][0]["id"] == english["assessment"]["id"]
    assert subjects["Mathematics"][0]["marks"] == {
        s["Amani"]: {
            "score": 25.0,
            "did_not_sit": False,
            # Grade 4 uses the CBC scale: 25 out of 50 is 50%, ME2 (D5).
            "result": {"percent": 50, "grade": "ME2", "points": 5},
        },
        s["Baraka"]: {"score": None, "did_not_sit": True, "result": None},
    }


@pytest.mark.parametrize(("query", "status"), [("", 422), ("?term=3", 422), ("?term=2", 200)])
def test_the_overview_needs_a_term_of_the_year(school, query, status):
    response = school["admin"].get(f"{API}/classes/{school['g4']}/marks{query}")

    assert response.status_code == status


def test_my_classes_gives_subject_ids_for_marks_links(school):
    body = school["maths_client"].get(
        f"{API}/classes", query_string={"academic_year_id": _year_id(school)}
    )

    classes = body.get_json()["classes"]
    assert [(c["name"], c["my_subjects"]) for c in classes] == [
        ("Grade 4 East", [{"id": school["maths"], "name": "Mathematics"}])
    ]


def _year_id(school):
    years = school["admin"].get(f"{API}/academic-years").get_json()["academic_years"]
    return years[0]["id"]
