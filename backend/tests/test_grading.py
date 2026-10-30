"""Grading scales and grades (D5): the rules in app/grading.py, the grading
endpoints, and the grades added to mark sheets and the marks overview."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import grading
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
    "terms": [{"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"}],
}
DEFAULT = dict(grading.DEFAULT_KCSE_BOUNDARIES)


# The rules themselves.


@pytest.mark.parametrize(
    ("score", "max_score", "expected"),
    [
        (Decimal("8"), 10, 80),
        (Decimal("179"), 200, 90),  # 89.5% rounds up.
        (Decimal("178.9"), 200, 89),  # 89.45% rounds down.
        (Decimal("12.5"), 25, 50),
        (Decimal("0"), 50, 0),
        (Decimal("50"), 50, 100),
        (Decimal("1"), 3, 33),
        (Decimal("2"), 3, 67),
    ],
)
def test_percentages_are_whole_numbers_rounded_half_up(score, max_score, expected):
    assert grading.percent(score, max_score) == expected


@pytest.mark.parametrize(
    ("whole_percent", "band"),
    [
        (100, "EE1"),
        (90, "EE1"),
        (89, "EE2"),
        (75, "EE2"),
        (74, "ME1"),
        (58, "ME1"),
        (57, "ME2"),
        (41, "ME2"),
        (40, "AE1"),
        (31, "AE1"),
        (30, "AE2"),
        (21, "AE2"),
        (20, "BE1"),
        (11, "BE1"),
        (10, "BE2"),
        (0, "BE2"),
    ],
)
def test_every_cbc_band_edge(whole_percent, band):
    assert grading.grade_for(whole_percent, grading.CBC_BANDS).grade == band


@pytest.mark.parametrize(
    ("whole_percent", "grade", "points"),
    [(100, "A", 12), (80, "A", 12), (79, "A-", 11), (50, "C", 6), (30, "D-", 2), (29, "E", 1)],
)
def test_default_kcse_edges(whole_percent, grade, points):
    band = grading.grade_for(whole_percent, grading.kcse_bands(DEFAULT))
    assert (band.grade, band.points) == (grade, points)


def test_cbc_points_run_from_8_to_1_and_kcse_from_12_to_1():
    assert [b.points for b in grading.CBC_BANDS] == list(range(8, 0, -1))
    assert [b.points for b in grading.kcse_bands(DEFAULT)] == list(range(12, 0, -1))


@pytest.mark.parametrize(
    ("level", "scale"),
    [
        ("pp1", "cbc"),
        ("grade_4", "cbc"),
        ("grade_12", "cbc"),
        ("form_1", "kcse"),
        ("form_4", "kcse"),
    ],
)
def test_form_classes_use_kcse_and_the_rest_cbc(level, scale):
    assert grading.scale_for(level) == scale


def test_a_term_result_adds_up_only_what_was_sat():
    bands = grading.CBC_BANDS
    result = grading.term_result([(Decimal("8"), 10), (Decimal("15"), 20)], bands)

    assert result == {"score": 23.0, "max_score": 30, "percent": 77, "grade": "EE2", "points": 7}
    assert grading.term_result([], bands) is None


# The API.


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
            select(AuditEvent.outcome, AuditEvent.target_type).where(AuditEvent.action == action)
        )
        return [tuple(row) for row in rows]


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A, 2027 (Term 1): Form 4 (Amani, Baraka) and Grade 4 (Chausiku)
    both take Mathematics; `teacher` teaches it in both. School B: an admin."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    for role in ("school_admin", "principal", "registrar", "finance_officer"):
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    teacher = str(add_member(make_user(email="teacher@example.com"), school_a, "teacher"))
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")

    admin = _client_for(db_app, "school_admin@example.com")
    year = _ok(admin.post(f"{API}/academic-years", json=YEAR), 201)["academic_year"]["id"]
    made = {"admin": admin}
    for key, level in (("form", "form_4"), ("cbc", "grade_4")):
        body = {"academic_year_id": year, "grade": level, "stream": None}
        made[key] = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    maths = _ok(admin.post(f"{API}/subjects", json={"name": "Mathematics"}), 201)["subject"]["id"]
    made["maths"] = maths
    students = {}
    for n, name in enumerate(("Amani", "Baraka", "Chausiku")):
        body = {"admission_number": f"ADM-{n + 1}", "full_name": f"{name} Pupil"}
        students[name] = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    made["students"] = students
    for key, names in (("form", ("Amani", "Baraka")), ("cbc", ("Chausiku",))):
        ids = [students[n] for n in names]
        _ok(admin.post(f"{API}/classes/{made[key]}/students", json={"student_ids": ids}), 201)
        _ok(admin.post(f"{API}/classes/{made[key]}/subjects", json={"subject_id": maths}), 201)
        path = f"{API}/classes/{made[key]}/subjects/{maths}/teachers"
        _ok(admin.post(path, json={"membership_id": teacher}), 201)
    made["teacher"] = _client_for(db_app, "teacher@example.com")
    return made


def _assessment(school, class_key, name, max_score):
    path = f"{API}/classes/{school[class_key]}/subjects/{school['maths']}/assessments"
    body = {"term": 1, "name": name, "max_score": max_score, "held_on": "2027-03-01"}
    return _ok(school["teacher"].post(path, json=body), 201)["assessment"]["id"]


def _save(school, assessment, **scores):
    marks = [
        {"student_id": school["students"][name], "did_not_sit": True}
        if score == "absent"
        else {"student_id": school["students"][name], "score": score}
        for name, score in scores.items()
    ]
    path = f"{API}/assessments/{assessment}/marks"
    return _ok(school["teacher"].put(path, json={"marks": marks}))


def _results(sheet):
    """{"Amani Pupil": (percent, grade, points) or None, ...} from a mark sheet."""
    return {
        s["full_name"]: (r["percent"], r["grade"], r["points"]) if (r := s["result"]) else None
        for s in sheet["students"]
    }


def _boundaries(**changes):
    return {"boundaries": {**DEFAULT, **changes}}


# Reading the scales.


def test_reading_the_scales_needs_a_login(db_app, school):
    assert db_app.test_client().get(f"{API}/grading").status_code == 401


@pytest.mark.parametrize("role", ["registrar", "finance_officer"])
def test_roles_without_marks_see_no_scales(db_app, school, role):
    client = _client_for(db_app, f"{role}@example.com")
    assert client.get(f"{API}/grading").status_code == 403


@pytest.mark.parametrize("who", ["school_admin", "principal", "teacher"])
def test_everyone_who_sees_marks_sees_the_scales(db_app, school, who):
    client = school["teacher"] if who == "teacher" else _client_for(db_app, f"{who}@example.com")

    body = _ok(client.get(f"{API}/grading"))

    assert [b["grade"] for b in body["cbc"]["bands"]] == [b.grade for b in grading.CBC_BANDS]
    assert body["kcse"]["is_default"] is True
    assert {b["grade"]: b["min_percent"] for b in body["kcse"]["bands"]} == DEFAULT
    assert body["default_kcse"] == DEFAULT


# Saving KCSE boundaries.


def test_an_administrator_saves_boundaries_and_it_is_audited(db_app, school):
    admin = school["admin"]

    saved = _ok(admin.put(f"{API}/grading/kcse", json=_boundaries(A=85)))
    again = _ok(admin.put(f"{API}/grading/kcse", json=_boundaries(A=85)))

    assert saved["kcse"]["is_default"] is False
    assert saved["kcse"]["bands"][0] == {"grade": "A", "min_percent": 85, "points": 12}
    assert again == saved
    # Saving the same values again changes nothing, so it is not recorded twice.
    assert _events(db_app, "grading.updated") == [("success", "school")]


def test_going_back_to_the_default_counts_as_default(db_app, school):
    admin = school["admin"]
    _ok(admin.put(f"{API}/grading/kcse", json=_boundaries(A=85)))

    restored = _ok(admin.put(f"{API}/grading/kcse", json=_boundaries()))

    assert restored["kcse"]["is_default"] is True
    assert len(_events(db_app, "grading.updated")) == 2


@pytest.mark.parametrize("who", ["principal", "teacher", "registrar"])
def test_only_administrators_change_boundaries(db_app, school, who):
    client = school["teacher"] if who == "teacher" else _client_for(db_app, f"{who}@example.com")

    response = client.put(f"{API}/grading/kcse", json=_boundaries(A=85))

    assert response.status_code == 403
    assert _events(db_app, "grading.manage") == [("denied", None)]
    assert _ok(school["admin"].get(f"{API}/grading"))["kcse"]["is_default"] is True


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_boundaries(A=75), "A must start higher than A- (75 is not above 75)."),
        (_boundaries(C=60), "C+ must start higher than C (55 is not above 60)."),
        (_boundaries(E=5), "E must start at 0, so that every percentage gets a grade."),
    ],
)
def test_boundaries_must_go_down_to_zero(db_app, school, body, message):
    response = school["admin"].put(f"{API}/grading/kcse", json=body)

    assert response.status_code == 422
    assert response.get_json()["error"]["details"] == [{"field": "boundaries", "message": message}]
    assert _ok(school["admin"].get(f"{API}/grading"))["kcse"]["is_default"] is True


@pytest.mark.parametrize(
    "body",
    [
        {"boundaries": {k: v for k, v in DEFAULT.items() if k != "B"}},
        _boundaries(**{"A+": 95}),
        _boundaries(A=101),
        _boundaries(A=-1),
        _boundaries(A="80"),
        _boundaries(A=80.5),
        _boundaries(A=True),
        {"boundaries": {}},
        {"boundaries": DEFAULT, "extra": 1},
        {},
    ],
)
def test_malformed_boundaries_are_refused(db_app, school, body):
    response = school["admin"].put(f"{API}/grading/kcse", json=body)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_each_school_keeps_its_own_boundaries(db_app, school):
    _ok(school["admin"].put(f"{API}/grading/kcse", json=_boundaries(A=85)))
    admin_b = _client_for(db_app, "admin.b@example.com")

    assert _ok(admin_b.get(f"{API}/grading"))["kcse"]["is_default"] is True


# Grades on mark sheets.


def test_a_form_mark_gets_a_kcse_grade_that_follows_the_boundaries(db_app, school):
    cat = _assessment(school, "form", "CAT 1", 10)
    sheet = _save(school, cat, Amani=8, Baraka="absent")

    assert sheet["scale"]["kind"] == "kcse"
    assert _results(sheet) == {"Amani Pupil": (80, "A", 12), "Baraka Pupil": None}

    _ok(school["admin"].put(f"{API}/grading/kcse", json=_boundaries(A=85)))
    regraded = _ok(school["teacher"].get(f"{API}/assessments/{cat}/marks"))
    assert _results(regraded)["Amani Pupil"] == (80, "A-", 11)
    assert regraded["scale"]["bands"][0]["min_percent"] == 85

    _ok(school["admin"].put(f"{API}/grading/kcse", json=_boundaries()))
    restored = _ok(school["teacher"].get(f"{API}/assessments/{cat}/marks"))
    assert _results(restored)["Amani Pupil"] == (80, "A", 12)


@pytest.mark.parametrize(
    ("score", "max_score", "expected"),
    [
        (7, 10, (70, "ME1", 6)),
        (179, 200, (90, "EE1", 8)),  # 89.5% shows as 90%, so EE1.
        (178.9, 200, (89, "EE2", 7)),
        (0, 10, (0, "BE2", 1)),
    ],
)
def test_a_cbc_mark_gets_a_kjsea_band(db_app, school, score, max_score, expected):
    quiz = _assessment(school, "cbc", "Quiz", max_score)

    sheet = _save(school, quiz, Chausiku=score)

    assert sheet["scale"]["kind"] == "cbc"
    assert _results(sheet)["Chausiku Pupil"] == expected


def test_a_student_without_a_mark_has_no_grade(db_app, school):
    quiz = _assessment(school, "cbc", "Quiz", 10)

    sheet = _ok(school["teacher"].get(f"{API}/assessments/{quiz}/marks"))

    assert _results(sheet) == {"Chausiku Pupil": None}


# Grades in the marks overview.


def test_the_overview_grades_each_mark_and_each_subjects_term(db_app, school):
    cat = _assessment(school, "form", "CAT 1", 10)
    exam = _assessment(school, "form", "Exam", 20)
    _save(school, cat, Amani=8, Baraka="absent")
    _save(school, exam, Amani=15, Baraka="absent")

    overview = _ok(school["admin"].get(f"{API}/classes/{school['form']}/marks?term=1"))

    amani, baraka = school["students"]["Amani"], school["students"]["Baraka"]
    maths = overview["subjects"][0]
    assert overview["scale"]["kind"] == "kcse"
    cat_marks = maths["assessments"][0]["marks"]
    assert cat_marks[amani]["result"] == {"percent": 80, "grade": "A", "points": 12}
    assert cat_marks[baraka]["result"] is None
    # 23 out of 30 is 76.7%, shown as 77%: A- by default.
    assert maths["term_results"] == {
        amani: {"score": 23.0, "max_score": 30, "percent": 77, "grade": "A-", "points": 11}
    }


def test_a_term_result_leaves_out_what_was_not_sat(db_app, school):
    cat = _assessment(school, "form", "CAT 1", 10)
    exam = _assessment(school, "form", "Exam", 20)
    _save(school, cat, Amani=8)
    _save(school, exam, Amani="absent")

    overview = _ok(school["admin"].get(f"{API}/classes/{school['form']}/marks?term=1"))

    result = overview["subjects"][0]["term_results"][school["students"]["Amani"]]
    assert (result["score"], result["max_score"], result["grade"]) == (8.0, 10, "A")
