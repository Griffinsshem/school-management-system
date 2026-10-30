"""Term results (D6): weighting, the overall result, class positions and the
class results endpoint."""

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
SUBJECTS = {
    "Mathematics": "mathematics",
    "English": "language",
    "Kiswahili": "language",
    "Biology": "other",
    "Chemistry": "other",
    "History": "other",
    "Geography": "other",
    "Business": "other",
}


# The rules themselves.


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ([30, 70], True),
        ([100], True),
        ([30, 40], False),
        ([30, 40, 40], False),
        ([30, None], False),
        ([None, None], False),
        ([], False),
    ],
)
def test_weights_count_only_when_all_are_set_and_make_100(weights, expected):
    assert grading.uses_weights(weights) is expected


def test_a_weighted_term_result():
    # CAT (30%) at 50%, Exam (70%) at 80%: 15 + 56 = 71%.
    sat = [(Decimal("5"), 10, 30), (Decimal("40"), 50, 70)]

    weighted = grading.term_result(sat, grading.CBC_BANDS, weighted=True)
    raw = grading.term_result(sat, grading.CBC_BANDS)

    assert (weighted["percent"], weighted["grade"], weighted["weighted"]) == (71, "ME1", True)
    # Unweighted it is 45 out of 60: 75%.
    assert (raw["percent"], raw["grade"], raw["weighted"]) == (75, "EE2", False)


def test_a_weighted_result_scales_up_what_was_sat():
    # Only the CAT (30%) was sat: it stands for the whole term.
    result = grading.term_result([(Decimal("5"), 10, 30)], grading.CBC_BANDS, weighted=True)
    assert result["percent"] == 50


def test_kcse_mean_counts_mathematics_the_best_language_and_the_best_five_others():
    results = [
        ("mathematics", 12),
        ("language", 10),  # English: not the best language, but in the best five.
        ("language", 11),  # Kiswahili: the language that counts.
        ("other", 9),
        ("other", 8),
        ("other", 7),
        ("other", 6),
        ("other", 5),  # The eighth subject: left out.
    ]

    overall = grading.overall_kcse(results)

    # 12 + 11 + 10 + 9 + 8 + 7 + 6 = 63; 63 / 7 = 9, a B.
    assert overall == {
        "total_points": 63,
        "subjects_counted": 7,
        "mean_points": 9,
        "grade": "B",
        "complete": True,
    }


def test_mathematics_counts_even_when_it_is_the_weakest():
    results = [("mathematics", 1), ("language", 12)] + [("other", 12)] * 6
    overall = grading.overall_kcse(results)
    assert (overall["total_points"], overall["complete"]) == (1 + 12 * 6, True)


@pytest.mark.parametrize(
    ("total", "grade"),
    [(84, "A"), (81, "A"), (80, "A-"), (74, "A-"), (73, "B+"), (11, "D-"), (10, "E"), (7, "E")],
)
def test_kcse_mean_grade_follows_the_points_bands(total, grade):
    # Seven subjects whose points add up to `total`.
    base, extra = divmod(total, 7)
    points = [base + 1] * extra + [base] * (7 - extra)
    results = [("mathematics", points[0]), ("language", points[1])] + [
        ("other", p) for p in points[2:]
    ]
    assert grading.overall_kcse(results)["grade"] == grade


@pytest.mark.parametrize(
    "results",
    [
        [("language", 10)] + [("other", 10)] * 6,  # No Mathematics.
        [("mathematics", 10)] + [("other", 10)] * 6,  # No language.
        [("mathematics", 10), ("language", 10)] + [("other", 10)] * 3,  # Five subjects.
    ],
)
def test_a_kcse_mean_without_the_core_or_seven_subjects_is_incomplete(results):
    overall = grading.overall_kcse(results)
    assert (overall["grade"], overall["complete"]) == ("B+", False)
    assert overall["subjects_counted"] == len(results)


def test_cbc_overall_is_total_and_average_points():
    assert grading.overall_cbc([7, 6, 6], 3) == {
        "total_points": 19,
        "subjects_counted": 3,
        "mean_points": 6,
        "grade": "ME1",
        "complete": True,
    }
    assert grading.overall_cbc([7, 6, 6], 4)["complete"] is False
    assert grading.overall_cbc([], 2) is None


def test_ties_share_a_position():
    assert grading.positions({"a": 60, "b": 55, "c": 55, "d": 50}) == {
        "a": 1,
        "b": 2,
        "c": 2,
        "d": 4,
    }


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
    """School A, 2027 (Term 1). Form 4 (Amani, Baraka, Chausiku) takes the
    eight SUBJECTS, with their KCSE categories; `form` is its class teacher
    and `maths` teaches its Mathematics. Grade 4 (Dalila) takes Mathematics
    and English."""
    school_a = make_school(code="school-a", name="School A")
    for role in ("school_admin", "principal", "registrar"):
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    members = {
        name: str(add_member(make_user(email=f"{name}@example.com"), school_a, "teacher"))
        for name in ("form", "maths")
    }

    admin = _client_for(db_app, "school_admin@example.com")
    year = _ok(admin.post(f"{API}/academic-years", json=YEAR), 201)["academic_year"]["id"]
    made = {"admin": admin, "subjects": {}, "students": {}}
    for key, level in (("form", "form_4"), ("cbc", "grade_4")):
        body = {"academic_year_id": year, "grade": level, "stream": None}
        made[key] = _ok(admin.post(f"{API}/classes", json=body), 201)["class"]["id"]
    for name, category in SUBJECTS.items():
        subject = _ok(admin.post(f"{API}/subjects", json={"name": name}), 201)["subject"]
        assert subject["kcse_category"] == "other"
        if category != "other":
            body = {"kcse_category": category}
            _ok(admin.patch(f"{API}/subjects/{subject['id']}", json=body))
        made["subjects"][name] = subject["id"]
    for n, name in enumerate(("Amani", "Baraka", "Chausiku", "Dalila")):
        body = {"admission_number": f"ADM-{n + 1}", "full_name": f"{name} Pupil"}
        made["students"][name] = _ok(admin.post(f"{API}/students", json=body), 201)["student"]["id"]
    for key, names, subjects in (
        ("form", ("Amani", "Baraka", "Chausiku"), list(SUBJECTS)),
        ("cbc", ("Dalila",), ["Mathematics", "English"]),
    ):
        ids = [made["students"][n] for n in names]
        _ok(admin.post(f"{API}/classes/{made[key]}/students", json={"student_ids": ids}), 201)
        for name in subjects:
            body = {"subject_id": made["subjects"][name]}
            _ok(admin.post(f"{API}/classes/{made[key]}/subjects", json=body), 201)
    path = f"{API}/classes/{made['form']}/subjects/{made['subjects']['Mathematics']}/teachers"
    _ok(admin.post(path, json={"membership_id": members["maths"]}), 201)
    path = f"{API}/classes/{made['form']}/teachers"
    _ok(admin.post(path, json={"membership_id": members["form"]}), 201)
    return made


def _assessment(school, class_key, subject, name="Exam", max_score=100, **fields):
    path = f"{API}/classes/{school[class_key]}/subjects/{school['subjects'][subject]}/assessments"
    body = {"term": 1, "name": name, "max_score": max_score, "held_on": "2027-03-01", **fields}
    return _ok(school["admin"].post(path, json=body), 201)["assessment"]


def _marks(school, assessment_id, **scores):
    marks = [
        {"student_id": school["students"][name], "did_not_sit": True}
        if score == "absent"
        else {"student_id": school["students"][name], "score": score}
        for name, score in scores.items()
    ]
    path = f"{API}/assessments/{assessment_id}/marks"
    return _ok(school["admin"].put(path, json={"marks": marks}))


def _results(client, school, class_key="form"):
    return client.get(f"{API}/classes/{school[class_key]}/results?term=1")


def _by_name(body):
    return {s["full_name"].split()[0]: s for s in body["students"]}


# Weights and categories.


def test_an_assessment_takes_an_optional_weight(db_app, school):
    cat = _assessment(school, "form", "Mathematics", "CAT", weight=30)
    assert cat["weight"] == 30
    path = f"{API}/assessments/{cat['id']}"

    cleared = _ok(school["admin"].patch(path, json={"weight": None}))["assessment"]
    assert cleared["weight"] is None
    for weight in (0, 101, "30", 30.5):
        response = school["admin"].patch(path, json={"weight": weight})
        assert response.status_code == 422, weight
    assert _assessment(school, "form", "English")["weight"] is None
    path = f"{API}/classes/{school['form']}/subjects/{school['subjects']['English']}/assessments"
    for weight in (0, 101, "30", 30.5, True):
        body = {"term": 1, "name": f"Try {weight}", "max_score": 10, "held_on": "2027-03-01"}
        response = school["admin"].post(path, json={**body, "weight": weight})
        assert response.status_code == 422, weight


@pytest.mark.parametrize("category", ["science", "", None, "Mathematics"])
def test_a_subject_category_is_one_of_three(db_app, school, category):
    path = f"{API}/subjects/{school['subjects']['Biology']}"
    response = school["admin"].patch(path, json={"kcse_category": category})
    assert response.status_code == 422


def test_weights_that_make_100_weight_the_term_result(db_app, school):
    cat = _assessment(school, "form", "Mathematics", "CAT", 10, weight=30)
    exam = _assessment(school, "form", "Mathematics", "Exam", 50, weight=70)
    _marks(school, cat["id"], Amani=5)
    _marks(school, exam["id"], Amani=40)

    overview = _ok(school["admin"].get(f"{API}/classes/{school['form']}/marks?term=1"))
    maths = next(s for s in overview["subjects"] if s["subject"]["name"] == "Mathematics")

    # 30% x 50% + 70% x 80% = 71%: a B+ (A- would be the raw 45/60 = 75%).
    amani = maths["term_results"][school["students"]["Amani"]]
    assert (amani["percent"], amani["grade"], amani["weighted"]) == (71, "B+", True)
    assert (maths["weighted"], maths["weight_total"]) == (True, 100)


def test_weights_short_of_100_fall_back_to_raw_totals(db_app, school):
    cat = _assessment(school, "form", "Mathematics", "CAT", 10, weight=30)
    exam = _assessment(school, "form", "Mathematics", "Exam", 50, weight=40)
    _marks(school, cat["id"], Amani=5)
    _marks(school, exam["id"], Amani=40)

    body = _ok(_results(school["admin"], school))
    maths = next(s for s in body["subjects"] if s["name"] == "Mathematics")
    amani = _by_name(body)["Amani"]["results"][school["subjects"]["Mathematics"]]

    assert (maths["weighted"], maths["weight_total"]) == (False, 70)
    assert (amani["percent"], amani["weighted"]) == (75, False)


# The overall result.


def _exam_marks(school, scores_by_subject):
    """One exam out of 100 per subject, with these marks."""
    for subject, scores in scores_by_subject.items():
        exam = _assessment(school, "form", subject)
        _marks(school, exam["id"], **scores)


def test_form_results_give_a_kcse_mean_grade(db_app, school):
    # Amani: every subject. Baraka: six subjects. Chausiku: no Mathematics.
    _exam_marks(
        school,
        {
            "Mathematics": {"Amani": 85, "Baraka": 60},
            "English": {"Amani": 72, "Baraka": 55, "Chausiku": 70},
            "Kiswahili": {"Amani": 66, "Baraka": 50, "Chausiku": 70},
            "Biology": {"Amani": 61, "Baraka": 45, "Chausiku": 70},
            "Chemistry": {"Amani": 56, "Baraka": 40, "Chausiku": 70},
            "History": {"Amani": 51, "Baraka": 35, "Chausiku": 70},
            "Geography": {"Amani": 46, "Chausiku": 70},
            "Business": {"Amani": 20, "Chausiku": "absent"},
        },
    )

    body = _ok(_results(school["admin"], school))
    students = _by_name(body)

    assert body["scale"]["kind"] == "kcse"
    assert len(body["subjects"]) == 8
    # Amani: A 12, English B+ 10, Kiswahili B 9, then the best five others:
    # Biology B- 8, Chemistry C+ 7, History C 6, Geography C- 5 (Business E
    # is left out): 12 + 10 + 9 + 8 + 7 + 6 + 5 = 57, mean 8.14, a B-.
    assert students["Amani"]["overall"] == {
        "total_points": 57,
        "subjects_counted": 7,
        "mean_points": 8,
        "grade": "B-",
        "complete": True,
    }
    baraka = students["Baraka"]["overall"]
    assert (baraka["subjects_counted"], baraka["complete"]) == (6, False)
    assert students["Chausiku"]["overall"]["complete"] is False
    # Positions are off by default: not sent at all.
    assert body["show_positions"] is False
    assert all("position" not in s for s in body["students"])


def test_cbc_results_give_total_and_average_points(db_app, school):
    for subject, score in (("Mathematics", 80), ("English", 60)):
        exam = _assessment(school, "cbc", subject)
        _marks(school, exam["id"], Dalila=score)

    body = _ok(_results(school["admin"], school, "cbc"))

    # EE2 (7) and ME1 (6): 13 points, average 6.5, shown as 7 (EE2).
    assert body["scale"]["kind"] == "cbc"
    assert _by_name(body)["Dalila"]["overall"] == {
        "total_points": 13,
        "subjects_counted": 2,
        "mean_points": 7,
        "grade": "EE2",
        "complete": True,
    }


# Class positions.


def test_positions_appear_only_once_switched_on_and_go_to_complete_results(db_app, school):
    _exam_marks(
        school,
        {
            subject: {"Amani": 70, "Baraka": 70, "Chausiku": 90}
            for subject in SUBJECTS
            if subject != "Mathematics"
        }
        | {"Mathematics": {"Amani": 70, "Baraka": 70}},
    )
    admin = school["admin"]

    saved = _ok(admin.put(f"{API}/grading/positions", json={"show_class_positions": True}))
    body = _ok(_results(admin, school))

    assert saved["show_class_positions"] is True
    assert body["show_positions"] is True
    places = {name: s["position"] for name, s in _by_name(body).items()}
    # Amani and Baraka tie; Chausiku has the best marks but no Mathematics.
    assert places == {"Amani": 1, "Baraka": 1, "Chausiku": None}
    assert _events(db_app, "grading.updated") == [("success", "school")]

    _ok(admin.put(f"{API}/grading/positions", json={"show_class_positions": False}))
    assert all("position" not in s for s in _ok(_results(admin, school))["students"])
    assert len(_events(db_app, "grading.updated")) == 2


@pytest.mark.parametrize("who", ["principal", "form", "maths", "registrar"])
def test_only_administrators_switch_positions(db_app, school, who):
    client = _client_for(db_app, f"{who}@example.com")
    response = client.put(f"{API}/grading/positions", json={"show_class_positions": True})
    assert response.status_code == 403
    assert _ok(school["admin"].get(f"{API}/grading"))["show_class_positions"] is False


@pytest.mark.parametrize("body", [{"show_class_positions": "yes"}, {"show_class_positions": 1}, {}])
def test_the_positions_switch_takes_true_or_false(db_app, school, body):
    response = school["admin"].put(f"{API}/grading/positions", json=body)
    assert response.status_code == 422


# Who may see results.


@pytest.mark.parametrize(("who", "status"), [("principal", 200), ("form", 200)])
def test_readers_of_the_class_see_its_results(db_app, school, who, status):
    client = _client_for(db_app, f"{who}@example.com")
    assert _results(client, school).status_code == status


def test_a_subject_teacher_who_is_not_class_teacher_gets_404(db_app, school):
    client = _client_for(db_app, "maths@example.com")

    assert _results(client, school).status_code == 404
    assert _events(db_app, "results.read") == [("denied", "class")]


def test_registrars_see_no_results(db_app, school):
    client = _client_for(db_app, "registrar@example.com")
    assert _results(client, school).status_code == 403
