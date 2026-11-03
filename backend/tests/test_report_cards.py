"""Report cards and class teachers' comments (D7). All names and comments
are made up."""

import logging
from datetime import date

import pytest
from sqlalchemy import select, update

from app.api.v1 import academic_years as years_api
from app.extensions import db
from app.models import AuditEvent, ReportComment, User

PASSWORD = "correct horse battery"
API = "/api/v1/school"
TODAY = "2027-06-10"  # In Term 2.
YEAR = {
    "name": "2027",
    "starts_on": "2027-01-04",
    "ends_on": "2027-11-26",
    "terms": [
        {"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"},
        {"number": 2, "starts_on": "2027-05-03", "ends_on": "2027-08-06"},
    ],
}
COMMENT = "Amani reads widely and helps others. Keep it up next term."


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
    """School A, 2027 (Term 1). Grade 4 (Amani, Baraka, Chausiku) takes
    Mathematics and English; `form` is its class teacher, `maths` teaches
    its Mathematics, and `both` is a principal who also teaches its English.
    Grade 5 has Dalila. School B has its own administrator."""
    school_a = make_school(code="school-a", name="School A")
    for role in ("school_admin", "principal", "registrar"):
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    members = {
        name: str(add_member(make_user(email=f"{name}@example.com"), school_a, "teacher"))
        for name in ("form", "maths")
    }
    both = make_user(email="both@example.com")
    add_member(both, school_a, "principal")
    members["both"] = str(add_member(both, school_a, "teacher"))
    add_member(make_user(email="admin.b@example.com"), make_school(code="school-b"), "school_admin")
    with db_app.app_context():
        for email, name in (("school_admin", "Admin Person"), ("form", "Form Teacher")):
            statement = update(User).where(User.email == f"{email}@example.com")
            db.session.execute(statement.values(full_name=name))
        db.session.commit()

    admin = _client_for(db_app, "school_admin@example.com")
    year = _ok(admin.post(f"{API}/academic-years", json=YEAR), 201)["academic_year"]["id"]
    made = {"admin": admin, "subjects": {}, "students": {}}
    for key, level in (("class", "grade_4"), ("other", "grade_5")):
        body = {"academic_year_id": year, "grade": level, "stream": None}
        made[key] = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    for name in ("Mathematics", "English"):
        subject = _ok(admin.post(f"{API}/subjects", json={"name": name}), 201)["subject"]
        made["subjects"][name] = subject["id"]
        path = f"{API}/classes/{made['class']}/subjects"
        _ok(admin.post(path, json={"subject_id": subject["id"]}), 201)
    for n, name in enumerate(("Amani", "Baraka", "Chausiku", "Dalila")):
        body = {"admission_number": f"ADM-{n + 1}", "full_name": f"{name} Pupil"}
        made["students"][name] = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    ids = [made["students"][n] for n in ("Amani", "Baraka", "Chausiku")]
    _ok(admin.post(f"{API}/classes/{made['class']}/students", json={"student_ids": ids}), 201)
    body = {"student_ids": [made["students"]["Dalila"]]}
    _ok(admin.post(f"{API}/classes/{made['other']}/students", json=body), 201)
    for subject, member in (("Mathematics", "maths"), ("English", "both")):
        path = f"{API}/classes/{made['class']}/subjects/{made['subjects'][subject]}/teachers"
        _ok(admin.post(path, json={"membership_id": members[member]}), 201)
    path = f"{API}/classes/{made['class']}/teachers"
    _ok(admin.post(path, json={"membership_id": members["form"]}), 201)
    return made


def _exam(school, subject, **scores):
    path = f"{API}/classes/{school['class']}/subjects/{school['subjects'][subject]}/assessments"
    body = {"term": 1, "name": "Exam", "max_score": 100, "held_on": "2027-03-01"}
    exam = _ok(school["admin"].post(path, json=body), 201)["assessment"]
    marks = [{"student_id": school["students"][n], "score": s} for n, s in scores.items()]
    _ok(school["admin"].put(f"{API}/assessments/{exam['id']}/marks", json={"marks": marks}))
    return exam


def _cards_path(school, class_key="class"):
    return f"{API}/classes/{school[class_key]}/report-cards"


def _comment_path(school, name, class_key="class"):
    return f"{_cards_path(school, class_key)}/{school['students'][name]}/comment?term=1"


def _save(client, school, name, comment, class_key="class"):
    return client.put(_comment_path(school, name, class_key), json={"comment": comment})


def _by_name(body):
    return {s["full_name"].split()[0]: s for s in body["students"]}


# Reading report cards.


def test_report_cards_give_each_students_term(db_app, school):
    _exam(school, "Mathematics", Amani=80, Baraka=60)
    _exam(school, "English", Amani=70)

    body = _ok(school["admin"].get(f"{_cards_path(school)}?term=1"))

    assert body["school"] == {"name": "School A"}
    assert body["year"] == {"name": "2027"}
    assert body["class"]["name"] == "Grade 4"
    assert body["term"]["number"] == 1
    assert body["scale"]["kind"] == "cbc"
    assert body["can_comment"] is True
    assert body["show_positions"] is False and "position_out_of" not in body
    assert [s["name"] for s in body["subjects"]] == ["English", "Mathematics"]
    cards = _by_name(body)
    assert sorted(cards) == ["Amani", "Baraka", "Chausiku"]
    amani = cards["Amani"]
    maths = amani["results"][school["subjects"]["Mathematics"]]
    assert (maths["percent"], maths["grade"]) == (80, "EE2")
    assert amani["overall"]["subjects_counted"] == 2
    assert amani["overall"]["complete"] is True
    assert cards["Baraka"]["overall"]["complete"] is False
    assert cards["Chausiku"]["overall"] is None
    assert amani["attendance"] == {"present": 0, "absent": 0, "late": 0, "days_recorded": 0}
    assert amani["comment"] is None
    assert "position" not in amani


def test_report_cards_show_the_same_numbers_as_the_results_page(db_app, school):
    _exam(school, "Mathematics", Amani=80, Baraka=60, Chausiku=45)
    _exam(school, "English", Amani=70, Baraka=58)
    results = _ok(school["admin"].get(f"{API}/classes/{school['class']}/results?term=1"))
    cards = _ok(school["admin"].get(f"{_cards_path(school)}?term=1"))

    for student in results["students"]:
        card = next(c for c in cards["students"] if c["id"] == student["id"])
        assert card["results"] == student["results"]
        assert card["overall"] == student["overall"]


def test_attendance_counts_this_classs_registers_of_the_term(db_app, school):
    s = school["students"]
    registers = {
        "2027-03-08": {"Amani": "present", "Baraka": "absent", "Chausiku": "late"},
        "2027-03-09": {"Amani": "late", "Baraka": "absent", "Chausiku": "present"},
        "2027-06-08": {"Amani": "absent", "Baraka": "present", "Chausiku": "present"},  # Term 2.
    }
    for day, statuses in registers.items():
        marks = [
            {"student_id": s[name], "status": status}
            | ({"reason": "sick"} if status == "absent" else {})
            for name, status in statuses.items()
        ]
        path = f"{API}/classes/{school['class']}/attendance/{day}"
        _ok(school["admin"].put(path, json={"marks": marks}), 201)

    cards = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=1")))
    summary = _ok(school["admin"].get(f"{API}/classes/{school['class']}/attendance?term=1"))
    term2 = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=2")))

    assert cards["Amani"]["attendance"] == {
        "present": 1,
        "absent": 0,
        "late": 1,
        "days_recorded": 2,
    }
    assert cards["Baraka"]["attendance"]["absent"] == 2
    assert term2["Amani"]["attendance"] == {
        "present": 0,
        "absent": 1,
        "late": 0,
        "days_recorded": 1,
    }
    for row in summary["students"]:
        card = cards[row["student"]["full_name"].split()[0]]["attendance"]
        assert (card["present"], card["absent"], card["late"]) == (
            row["present"],
            row["absent"],
            row["late"],
        )


def test_positions_show_only_when_the_school_shows_them(db_app, school):
    _exam(school, "Mathematics", Amani=80, Baraka=60, Chausiku=60)
    _exam(school, "English", Amani=70, Baraka=60)  # Chausiku's result is incomplete.
    _ok(school["admin"].put(f"{API}/grading/positions", json={"show_class_positions": True}))

    body = _ok(school["admin"].get(f"{_cards_path(school)}?term=1"))
    cards = _by_name(body)

    assert body["show_positions"] is True
    assert body["position_out_of"] == 2
    assert [cards[n]["position"] for n in ("Amani", "Baraka", "Chausiku")] == [1, 2, None]


def test_one_students_report_card(db_app, school):
    _exam(school, "Mathematics", Amani=80)
    path = f"{_cards_path(school)}/{school['students']['Amani']}?term=1"

    body = _ok(school["admin"].get(path))

    assert "students" not in body
    assert body["student"]["full_name"] == "Amani Pupil"
    assert body["student"]["results"][school["subjects"]["Mathematics"]]["percent"] == 80
    assert body["school"]["name"] == "School A"


def test_a_student_not_on_the_class_has_no_report_card_there(db_app, school):
    path = f"{_cards_path(school)}/{school['students']['Dalila']}?term=1"

    response = school["admin"].get(path)

    assert response.status_code == 404
    assert response.get_json()["error"]["message"] == "Report card not found."
    assert ("denied", "student", school["students"]["Dalila"]) in _events(
        db_app, "report_cards.read"
    )


def test_a_student_who_left_keeps_the_report_card_of_their_marks(db_app, school):
    _exam(school, "Mathematics", Amani=80, Baraka=60)
    path = f"{API}/classes/{school['class']}/students/{school['students']['Baraka']}"
    _ok(school["admin"].patch(path, json={"class_id": school["other"]}))

    marks = [
        {"student_id": school["students"][n], "status": "present"} for n in ("Baraka", "Dalila")
    ]
    path = f"{API}/classes/{school['other']}/attendance/2027-03-15"
    _ok(school["admin"].put(path, json={"marks": marks}), 201)

    cards = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=1")))

    assert cards["Baraka"]["in_class"] is False
    # Grade 5's register is not on Grade 4's report card.
    assert cards["Baraka"]["attendance"]["days_recorded"] == 0
    _ok(_save(school["admin"], school, "Baraka", "Moved to Grade 5 in March."))


@pytest.mark.parametrize(
    ("email", "can_comment"),
    [
        ("school_admin@example.com", True),
        ("form@example.com", True),
        ("principal@example.com", False),
        ("both@example.com", False),
    ],
)
def test_who_reads_report_cards(db_app, school, email, can_comment):
    body = _ok(_client_for(db_app, email).get(f"{_cards_path(school)}?term=1"))
    assert body["can_comment"] is can_comment


@pytest.mark.parametrize(
    ("email", "status"),
    [
        ("maths@example.com", 404),  # Teaches a subject, but is not the class teacher.
        ("registrar@example.com", 403),
        ("admin.b@example.com", 404),
    ],
)
def test_others_get_no_report_cards(db_app, school, email, status):
    client = _client_for(db_app, email)
    for path in (
        f"{_cards_path(school)}?term=1",
        f"{_cards_path(school)}/{school['students']['Amani']}?term=1",
    ):
        response = client.get(path)
        assert response.status_code == status
        if status == 404:
            assert response.get_json()["error"]["message"] == "Not found."


def test_a_refused_read_is_audited(db_app, school):
    _client_for(db_app, "maths@example.com").get(f"{_cards_path(school)}?term=1")
    assert _events(db_app, "report_cards.read") == [("denied", "class", school["class"])]


@pytest.mark.parametrize("query", ["", "?term=0", "?term=4", "?term=3", "?term=1&term=1"])
def test_report_cards_need_a_term_of_the_year(db_app, school, query):
    assert school["admin"].get(f"{_cards_path(school)}{query}").status_code == 422


# Comments.


def test_the_class_teacher_writes_a_comment(db_app, school):
    teacher = _client_for(db_app, "form@example.com")

    card = _ok(_save(teacher, school, "Amani", COMMENT))["student"]

    assert card["full_name"] == "Amani Pupil"
    assert card["comment"]["text"] == COMMENT
    assert card["comment"]["updated_by"] == "Form Teacher"
    assert card["comment"]["updated_at"]
    cards = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=1")))
    assert cards["Amani"]["comment"]["text"] == COMMENT
    assert cards["Baraka"]["comment"] is None
    assert _events(db_app, "report_comment.saved") == [
        ("success", "student", school["students"]["Amani"])
    ]


def test_a_comment_is_changed_and_cleared_and_each_change_audited(db_app, school):
    admin = school["admin"]
    assert _ok(_save(admin, school, "Amani", COMMENT))["student"]["comment"]["updated_by"] == (
        "Admin Person"
    )
    _ok(_save(admin, school, "Amani", COMMENT))  # The same text: nothing changes.
    assert len(_events(db_app, "report_comment.saved")) == 1

    teacher = _client_for(db_app, "form@example.com")
    changed = _ok(_save(teacher, school, "Amani", "A much improved term."))["student"]
    assert changed["comment"]["text"] == "A much improved term."
    assert changed["comment"]["updated_by"] == "Form Teacher"
    assert len(_events(db_app, "report_comment.saved")) == 2

    cleared = _ok(_save(admin, school, "Amani", ""))["student"]
    assert cleared["comment"] is None
    _ok(_save(admin, school, "Amani", ""))  # Nothing left to clear.
    assert _events(db_app, "report_comment.cleared") == [
        ("success", "student", school["students"]["Amani"])
    ]
    with db_app.app_context():
        assert db.session.scalar(select(ReportComment.id)) is None


def test_a_comment_belongs_to_one_term(db_app, school):
    _ok(_save(school["admin"], school, "Amani", COMMENT))

    term2 = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=2")))
    path = f"{_cards_path(school)}/{school['students']['Amani']}/comment?term=2"
    second = _ok(school["admin"].put(path, json={"comment": "Term 2: steady progress."}))

    assert term2["Amani"]["comment"] is None
    assert second["student"]["comment"]["text"] == "Term 2: steady progress."
    term1 = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=1")))
    assert term1["Amani"]["comment"]["text"] == COMMENT


def test_a_comment_is_trimmed_and_keeps_its_line_breaks(db_app, school):
    sent = "  Good term.\r\nKeep reading.\tWell done.  \n"

    card = _ok(_save(school["admin"], school, "Amani", sent))["student"]

    assert card["comment"]["text"] == "Good term.\nKeep reading.\tWell done."


def test_a_comment_of_500_characters_is_kept(db_app, school):
    card = _ok(_save(school["admin"], school, "Amani", "x" * 500))["student"]
    assert len(card["comment"]["text"]) == 500


@pytest.mark.parametrize(
    ("comment", "message"),
    [
        ("x" * 501, "at most 500 characters (this one has 501)"),
        ("   ", "cannot be only spaces"),
        ("\n\t ", "cannot be only spaces"),
        ("Good\x00term", "only contain ordinary text"),
        ("Good\x07term", "only contain ordinary text"),
        ("x" * 2001, "at most 2000 characters"),
    ],
)
def test_comments_that_are_refused(db_app, school, comment, message):
    _ok(_save(school["admin"], school, "Amani", COMMENT))

    response = _save(school["admin"], school, "Amani", comment)

    assert response.status_code == 422
    assert message in str(response.get_json()["error"]["details"])
    # The comment already there is kept.
    cards = _by_name(_ok(school["admin"].get(f"{_cards_path(school)}?term=1")))
    assert cards["Amani"]["comment"]["text"] == COMMENT


@pytest.mark.parametrize(
    "body", [{}, {"comment": None}, {"comment": 12}, {"comment": "ok", "extra": 1}, []]
)
def test_the_request_must_be_a_comment(db_app, school, body):
    response = school["admin"].put(_comment_path(school, "Amani"), json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("email", "status"),
    [
        ("principal@example.com", 403),
        ("registrar@example.com", 403),
        ("maths@example.com", 404),
        ("both@example.com", 404),  # Reads as principal, but is not the class teacher.
        ("admin.b@example.com", 404),
    ],
)
def test_only_administrators_and_the_class_teacher_write_comments(db_app, school, email, status):
    response = _save(_client_for(db_app, email), school, "Amani", COMMENT)

    assert response.status_code == status
    with db_app.app_context():
        assert db.session.scalar(select(ReportComment.id)) is None
    if status == 404:
        assert _events(db_app, "report_comment.saved") == [("denied", "class", school["class"])]


def test_no_comment_for_a_student_not_on_the_class(db_app, school):
    response = _save(_client_for(db_app, "form@example.com"), school, "Dalila", COMMENT)

    assert response.status_code == 404
    assert response.get_json()["error"]["message"] == "Report card not found."
    assert _events(db_app, "report_comment.saved") == [
        ("denied", "student", school["students"]["Dalila"])
    ]


def test_no_comment_for_an_unknown_student(db_app, school):
    path = f"{_cards_path(school)}/00000000-0000-0000-0000-000000000000/comment?term=1"
    response = school["admin"].put(path, json={"comment": COMMENT})
    assert response.status_code == 404


def test_comments_never_reach_the_logs(db_app, school, caplog):
    caplog.set_level(logging.DEBUG)
    teacher = _client_for(db_app, "form@example.com")

    _ok(_save(teacher, school, "Amani", COMMENT))
    _ok(_save(teacher, school, "Amani", "Second private remark about Amani."))
    _save(teacher, school, "Amani", "x" * 501 + "SECRET-TAIL")
    _ok(_save(teacher, school, "Amani", ""))

    logged = caplog.text
    assert "Report card comment saved" in logged
    assert "Report card comment cleared" in logged
    for private in (COMMENT, "Second private remark", "SECRET-TAIL", "Amani reads"):
        assert private not in logged
