import uuid

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import AuditEvent, Membership

MEMBERS = "/api/v1/school/members"
PASSWORD = "correct horse battery"


def _deactivate_url(membership_id) -> str:
    return f"{MEMBERS}/{membership_id}/deactivate"


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _is_active(app, membership_id) -> bool:
    with app.app_context():
        return db.session.get(Membership, membership_id).is_active


def _events(app, action=None):
    with app.app_context():
        query = select(AuditEvent).order_by(AuditEvent.occurred_at)
        if action:
            query = query.where(AuditEvent.action == action)
        return [
            (event.action, event.outcome, event.actor_user_id, event.target_id)
            for event in db.session.scalars(query)
        ]


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A with an admin, a principal and a teacher; School B with its own teacher."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    people = {}
    for name, role in (
        ("admin", "school_admin"),
        ("principal", "principal"),
        ("teacher", "teacher"),
    ):
        user_id = make_user(email=f"{name}@example.com")
        people[name] = (user_id, add_member(user_id, school_a, role))
    outsider = make_user(email="outsider@example.com")
    people["outsider"] = (outsider, add_member(outsider, school_b, "teacher"))
    return school_a, school_b, people


# Access rules, checked for both endpoints.

ENDPOINTS = [
    ("get", lambda people: MEMBERS, "members.read"),
    ("post", lambda people: _deactivate_url(people["teacher"][1]), "members.manage"),
]


@pytest.mark.parametrize(("method", "url", "_permission"), ENDPOINTS)
def test_endpoints_need_a_login(db_app, school, method, url, _permission):
    _a, _b, people = school

    response = getattr(db_app.test_client(), method)(url(people))

    assert response.status_code == 401


@pytest.mark.parametrize(("method", "url", "_permission"), ENDPOINTS)
def test_endpoints_need_an_active_school(db_app, school, make_user, method, url, _permission):
    _a, _b, people = school
    make_user(email="nobody@example.com")

    response = getattr(_client_for(db_app, "nobody@example.com"), method)(url(people))

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "no_active_school"


@pytest.mark.parametrize(("method", "url", "permission"), ENDPOINTS)
def test_endpoints_refuse_and_record_the_wrong_role(db_app, school, method, url, permission):
    _a, _b, people = school
    teacher_id, _membership = people["teacher"]

    response = getattr(_client_for(db_app, "teacher@example.com"), method)(url(people))

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"
    assert _events(db_app, permission) == [(permission, "denied", teacher_id, None)]
    assert _is_active(db_app, people["teacher"][1])


def test_principal_can_list_but_not_deactivate(db_app, school):
    _a, _b, people = school
    client = _client_for(db_app, "principal@example.com")

    assert client.get(MEMBERS).status_code == 200
    assert client.post(_deactivate_url(people["teacher"][1])).status_code == 403


# Listing.


def test_members_list_shows_only_the_current_school(db_app, school):
    _a, _b, _people = school

    response = _client_for(db_app, "admin@example.com").get(MEMBERS)
    members = response.get_json()["members"]

    assert response.status_code == 200
    assert sorted(m["user"]["email"] for m in members) == [
        "admin@example.com",
        "principal@example.com",
        "teacher@example.com",
    ]
    assert {"id", "role", "is_active", "user"} == set(members[0])
    assert {"id", "full_name", "email"} == set(members[0]["user"])


# Deactivating.


def test_admin_deactivates_a_teacher_who_then_loses_access(db_app, school):
    _a, _b, people = school
    teacher_id, membership_id = people["teacher"]
    admin_id, _ = people["admin"]
    teacher_client = _client_for(db_app, "teacher@example.com")
    assert teacher_client.get("/api/v1/auth/me").get_json()["active_school"] is not None

    response = _client_for(db_app, "admin@example.com").post(_deactivate_url(membership_id))

    assert response.status_code == 200
    assert response.get_json()["member"]["is_active"] is False
    assert not _is_active(db_app, membership_id)
    assert _events(db_app, "membership.deactivated") == [
        ("membership.deactivated", "success", admin_id, membership_id)
    ]
    assert teacher_client.get("/api/v1/auth/me").get_json()["active_school"] is None


def test_deactivating_twice_is_harmless(db_app, school):
    _a, _b, people = school
    client = _client_for(db_app, "admin@example.com")

    client.post(_deactivate_url(people["teacher"][1]))
    response = client.post(_deactivate_url(people["teacher"][1]))

    assert response.status_code == 200
    assert len(_events(db_app, "membership.deactivated")) == 1


@pytest.mark.parametrize("target", ["other_school", "made_up"])
def test_memberships_outside_the_school_look_missing(db_app, school, target):
    _a, _b, people = school
    admin_id, _ = people["admin"]
    outsider_membership = people["outsider"][1]
    target_id = outsider_membership if target == "other_school" else uuid.uuid4()

    response = _client_for(db_app, "admin@example.com").post(_deactivate_url(target_id))

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"
    assert _is_active(db_app, outsider_membership)
    assert _events(db_app, "membership.deactivated") == [
        ("membership.deactivated", "denied", admin_id, target_id)
    ]


def test_a_malformed_id_is_not_found(db_app, school):
    response = _client_for(db_app, "admin@example.com").post(_deactivate_url("not-a-uuid"))

    assert response.status_code == 404


def test_the_last_school_admin_cannot_be_deactivated(db_app, school):
    _a, _b, people = school
    admin_membership = people["admin"][1]

    response = _client_for(db_app, "admin@example.com").post(_deactivate_url(admin_membership))

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "last_school_admin"
    assert _is_active(db_app, admin_membership)


def test_an_admin_can_step_down_when_another_admin_remains(db_app, school, add_member):
    school_a, _b, people = school
    principal_id, _ = people["principal"]
    add_member(principal_id, school_a, "school_admin")
    admin_client = _client_for(db_app, "admin@example.com")

    response = admin_client.post(_deactivate_url(people["admin"][1]))

    assert response.status_code == 200
    # Their own access to the school ends straight away.
    assert admin_client.get(MEMBERS).get_json()["error"]["code"] == "no_active_school"
