"""The school years and terms API (C1)."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.api.v1 import academic_years as module
from app.extensions import db
from app.models import AuditEvent

YEARS = "/api/v1/school/academic-years"
PASSWORD = "correct horse battery"
TERMS_2027 = [
    {"number": 1, "starts_on": "2027-01-04", "ends_on": "2027-04-01"},
    {"number": 2, "starts_on": "2027-04-26", "ends_on": "2027-07-30"},
    {"number": 3, "starts_on": "2027-08-23", "ends_on": "2027-10-22"},
]
YEAR_2027 = {
    "name": "2027",
    "starts_on": "2027-01-04",
    "ends_on": "2027-11-26",
    "terms": TERMS_2027,
}
STAFF = ("school_admin", "principal", "registrar", "teacher", "finance_officer")


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
    """School A with one person per role; School B with an admin and a year 2027."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    for role in (*STAFF, "guardian"):
        add_member(make_user(email=f"{role}@example.com"), school_a, role)
    add_member(make_user(email="admin.b@example.com"), school_b, "school_admin")
    response = _client_for(db_app, "admin.b@example.com").post(YEARS, json=YEAR_2027)
    assert response.status_code == 201
    return {"other_school_year": response.get_json()["academic_year"]["id"]}


@pytest.fixture
def admin(db_app, school):
    return _client_for(db_app, "school_admin@example.com")


def _create(client, body=YEAR_2027):
    return client.post(YEARS, json=body)


# Access.


def test_reading_needs_a_login(db_app, school):
    assert db_app.test_client().get(YEARS).status_code == 401


@pytest.mark.parametrize("role", STAFF)
def test_every_staff_role_can_read(db_app, school, role):
    response = _client_for(db_app, f"{role}@example.com").get(YEARS)

    assert response.status_code == 200


def test_guardians_cannot_read(db_app, school):
    response = _client_for(db_app, "guardian@example.com").get(YEARS)

    assert response.status_code == 403


@pytest.mark.parametrize("role", [r for r in STAFF if r != "school_admin"])
def test_only_school_admins_can_change(db_app, school, role):
    client = _client_for(db_app, f"{role}@example.com")

    assert _create(client).status_code == 403
    assert _events(db_app, "academics.manage") == [("denied", None)]


def test_another_schools_years_are_invisible_and_unchangeable(db_app, school, admin):
    other = school["other_school_year"]

    assert admin.get(YEARS).get_json()["academic_years"] == []
    assert admin.patch(f"{YEARS}/{other}", json={"name": "Mine"}).status_code == 404
    term = {"starts_on": "2027-01-04", "ends_on": "2027-02-01"}
    assert admin.put(f"{YEARS}/{other}/terms/1", json=term).status_code == 404
    assert _events(db_app, "academic_year.updated") == [("denied", "academic_year")]
    assert _events(db_app, "term.saved")[-1] == ("denied", "academic_year")


# Creating.


def test_an_admin_creates_a_year_with_its_terms(db_app, admin):
    body = {**YEAR_2027, "terms": list(reversed(TERMS_2027))}

    response = _create(admin, body)

    assert response.status_code == 201
    year = response.get_json()["academic_year"]
    assert (year["name"], year["starts_on"], year["ends_on"]) == (
        "2027",
        "2027-01-04",
        "2027-11-26",
    )
    assert [(t["number"], t["name"]) for t in year["terms"]] == [
        (1, "Term 1"),
        (2, "Term 2"),
        (3, "Term 3"),
    ]
    assert _events(db_app, "academic_year.created")[-1] == ("success", "academic_year")
    # Three for this school, three for School B in the fixture.
    assert _events(db_app, "term.saved").count(("success", "term")) == 6


def test_a_year_may_start_with_no_terms(admin):
    response = _create(
        admin, {"name": " 2027 ", "starts_on": "2027-01-04", "ends_on": "2027-11-26"}
    )

    assert response.status_code == 201
    assert response.get_json()["academic_year"]["name"] == "2027"
    assert response.get_json()["academic_year"]["terms"] == []


def _term(number, starts_on, ends_on):
    return {"number": number, "starts_on": starts_on, "ends_on": ends_on}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"ends_on": "2027-01-03"}, "must end after it starts"),
        ({"ends_on": "2028-02-09"}, "at most 400 days"),
        ({"name": "   "}, "Must not be blank"),
        ({"name": "x" * 21}, "at most 20 characters"),
        ({"starts_on": "1999-12-31"}, "between the years 2000 and 2100"),
        ({"terms": [_term(1, "2027-01-01", "2027-04-01")]}, "Term 1 must be inside"),
        ({"terms": [_term(3, "2027-08-23", "2027-12-01")]}, "Term 3 must be inside"),
        ({"terms": [_term(1, "2027-04-01", "2027-01-04")]}, "Term 1 must end after it starts"),
        (
            {"terms": [_term(1, "2027-01-04", "2027-04-26"), _term(2, "2027-04-26", "2027-07-30")]},
            "Term 2 must start after Term 1 ends",
        ),
        (
            {"terms": [_term(1, "2027-05-03", "2027-07-30"), _term(2, "2027-01-04", "2027-04-01")]},
            "Term 2 must start after Term 1 ends",
        ),
        ({"terms": [_term(1, "2027-01-04", "2027-02-01")] * 2}, "only once"),
        ({"terms": [_term(4, "2027-01-04", "2027-02-01")]}, "less than or equal to 3"),
        ({"colour": "blue"}, "Extra inputs are not permitted"),
    ],
)
def test_impossible_years_are_explained(admin, changes, message):
    response = _create(admin, {**YEAR_2027, **changes})

    assert response.status_code == 422
    messages = " ".join(d["message"] for d in response.get_json()["error"]["details"])
    assert message in messages


def test_names_are_unique_within_the_school(admin):
    assert _create(admin).status_code == 201
    response = _create(admin, {"name": "2027", "starts_on": "2028-01-03", "ends_on": "2028-11-24"})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "year_name_taken"


@pytest.mark.parametrize(
    ("starts_on", "ends_on", "status"),
    [
        ("2027-11-26", "2028-11-24", 409),  # shares 2027's last day
        ("2026-01-05", "2027-01-04", 409),  # shares 2027's first day
        ("2027-03-01", "2027-06-01", 409),  # inside 2027
        ("2026-12-01", "2027-12-31", 409),  # around 2027
        ("2027-11-27", "2028-11-24", 201),  # the day after
        ("2026-01-05", "2027-01-03", 201),  # the day before
    ],
)
def test_years_cannot_overlap(admin, starts_on, ends_on, status):
    assert _create(admin).status_code == 201

    response = _create(admin, {"name": "Other", "starts_on": starts_on, "ends_on": ends_on})

    assert response.status_code == status
    if status == 409:
        assert response.get_json()["error"] == {
            "code": "overlapping_year",
            "message": "These dates overlap the school year 2027.",
            "request_id": response.get_json()["error"]["request_id"],
        }


# Changing.


@pytest.fixture
def year_2027(admin):
    response = _create(admin)
    assert response.status_code == 201
    return response.get_json()["academic_year"]["id"]


def test_an_admin_renames_and_moves_a_year(db_app, admin, year_2027):
    response = admin.patch(
        f"{YEARS}/{year_2027}", json={"name": "2027 school year", "ends_on": "2027-12-10"}
    )

    assert response.status_code == 200
    year = response.get_json()["academic_year"]
    assert (year["name"], year["ends_on"]) == ("2027 school year", "2027-12-10")
    assert _events(db_app, "academic_year.updated") == [("success", "academic_year")]


@pytest.mark.parametrize(
    ("body", "status", "text"),
    [
        ({"ends_on": "2027-10-01"}, 422, "Term 3 must be inside the school year."),
        ({"starts_on": "2027-11-27"}, 422, "must end after it starts"),
        ({"name": None}, 422, "Must not be null"),
        ({}, 422, "Send at least one"),
    ],
)
def test_impossible_changes_are_refused(admin, year_2027, body, status, text):
    response = admin.patch(f"{YEARS}/{year_2027}", json=body)

    assert response.status_code == status
    assert text in " ".join(d["message"] for d in response.get_json()["error"]["details"])


def test_a_change_cannot_make_years_overlap_or_share_a_name(admin, year_2027):
    other = _create(admin, {"name": "2028", "starts_on": "2028-01-03", "ends_on": "2028-11-24"})
    other_id = other.get_json()["academic_year"]["id"]

    moved = admin.patch(f"{YEARS}/{other_id}", json={"starts_on": "2027-11-26"})
    renamed = admin.patch(f"{YEARS}/{other_id}", json={"name": "2027"})

    assert (moved.status_code, moved.get_json()["error"]["code"]) == (409, "overlapping_year")
    assert (renamed.status_code, renamed.get_json()["error"]["code"]) == (409, "year_name_taken")


def test_an_admin_sets_and_corrects_a_term(db_app, admin):
    year_id = _create(
        admin, {"name": "2027", "starts_on": "2027-01-04", "ends_on": "2027-11-26"}
    ).get_json()["academic_year"]["id"]

    created = admin.put(
        f"{YEARS}/{year_id}/terms/2", json={"starts_on": "2027-04-26", "ends_on": "2027-07-30"}
    )
    corrected = admin.put(
        f"{YEARS}/{year_id}/terms/2", json={"starts_on": "2027-04-27", "ends_on": "2027-07-30"}
    )

    assert created.status_code == corrected.status_code == 200
    terms = corrected.get_json()["academic_year"]["terms"]
    assert [(t["number"], t["starts_on"]) for t in terms] == [(2, "2027-04-27")]
    assert _events(db_app, "term.saved").count(("success", "term")) == 3 + 2


@pytest.mark.parametrize(
    ("number", "dates", "status", "text"),
    [
        (1, ("2027-01-04", "2027-05-01"), 422, "Term 2 must start after Term 1 ends."),
        (3, ("2027-07-30", "2027-10-22"), 422, "Term 3 must start after Term 2 ends."),
        (3, ("2027-08-23", "2027-12-01"), 422, "Term 3 must be inside the school year."),
        (2, ("2027-07-30", "2027-04-26"), 422, "Term 2 must end after it starts."),
        (4, ("2027-08-23", "2027-10-22"), 404, None),
        (0, ("2027-08-23", "2027-10-22"), 404, None),
    ],
)
def test_impossible_terms_are_refused(admin, year_2027, number, dates, status, text):
    body = {"starts_on": dates[0], "ends_on": dates[1]}

    response = admin.put(f"{YEARS}/{year_2027}/terms/{number}", json=body)

    assert response.status_code == status
    if text:
        assert text in [d["message"] for d in response.get_json()["error"]["details"]]


# Today's year and term.


@pytest.mark.parametrize(
    ("today", "year", "term", "next_term"),
    [
        ("2027-02-15", "2027", 1, None),
        ("2027-04-26", "2027", 2, None),  # first day of Term 2
        ("2027-07-30", "2027", 2, None),  # last day of Term 2
        ("2027-08-01", "2027", None, (2027, 3, "2027-08-23")),  # holiday
        ("2027-12-01", None, None, (2028, 1, "2028-01-10")),  # between years
        ("2026-06-01", None, None, (2027, 1, "2027-01-04")),  # before any year
        ("2028-12-01", None, None, None),  # after every year
    ],
)
def test_todays_year_and_term(admin, year_2027, monkeypatch, today, year, term, next_term):
    year_2028 = {
        "name": "2028",
        "starts_on": "2028-01-10",
        "ends_on": "2028-11-24",
        "terms": [_term(1, "2028-01-10", "2028-04-07")],
    }
    ids = {"2027": year_2027, "2028": _create(admin, year_2028).get_json()["academic_year"]["id"]}
    monkeypatch.setattr(module, "school_today", lambda: date.fromisoformat(today))

    current = admin.get(YEARS).get_json()["current"]

    assert current["today"] == today
    assert current["academic_year_id"] == (ids[year] if year else None)
    assert current["term_number"] == term
    if next_term is None:
        assert current["next_term"] is None
    else:
        expected = {
            "academic_year_id": ids[str(next_term[0])],
            "number": next_term[1],
            "starts_on": next_term[2],
        }
        assert current["next_term"] == expected


def test_years_are_listed_newest_first(admin, year_2027):
    _create(admin, {"name": "2028", "starts_on": "2028-01-10", "ends_on": "2028-11-24"})

    names = [y["name"] for y in admin.get(YEARS).get_json()["academic_years"]]

    assert names == ["2028", "2027"]


def test_today_is_kenyan_time(monkeypatch):
    class LateEveningUtc(datetime):
        @classmethod
        def now(cls, tz=None):
            # 22:30 UTC on 3 January is already 01:30 on 4 January in Nairobi.
            return datetime(2027, 1, 3, 22, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(module, "datetime", LateEveningUtc)

    assert module.SCHOOL_TIME_ZONE.key == "Africa/Nairobi"
    assert module.school_today() == date(2027, 1, 4)
