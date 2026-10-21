import uuid

import pytest
from sqlalchemy import select

from app import create_app
from app.auth.schools import current_school, school_required
from app.extensions import db
from app.models import Membership, School, UserSession

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
ACTIVE_SCHOOL = "/api/v1/auth/active-school"
PASSWORD = "correct horse battery"


def _login(client, email="ada@example.com"):
    response = client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response


def _choose(client, school_id):
    return client.post(ACTIVE_SCHOOL, json={"school_id": str(school_id)})


def _stored_active_school(app):
    with app.app_context():
        return db.session.scalar(select(UserSession.active_school_id))


@pytest.fixture
def two_schools(db_app, make_user, make_school):
    """Ada, plus School A (where Ada teaches) and School B (where she has no role)."""
    ada = make_user()
    school_a = make_school(code="school-a", name="School A", county_code=1)
    school_b = make_school(code="school-b", name="School B", county_code=42)
    return ada, school_a, school_b


def test_me_lists_memberships_and_no_school_when_there_are_none(db_app, make_user):
    make_user()
    client = db_app.test_client()
    _login(client)

    body = client.get(ME).get_json()

    assert body["user"]["email"] == "ada@example.com"
    assert body["memberships"] == []
    assert body["active_school"] is None


def test_a_single_school_is_chosen_automatically_at_login(db_app, two_schools, add_member):
    ada, school_a, _school_b = two_schools
    add_member(ada, school_a, "teacher")
    add_member(ada, school_a, "guardian")  # Two roles, still one school.
    client = db_app.test_client()
    _login(client)

    body = client.get(ME).get_json()

    assert body["active_school"]["id"] == str(school_a)
    assert body["active_school"]["county_name"] == "Mombasa"
    assert sorted(m["role"] for m in body["memberships"]) == ["guardian", "teacher"]


def test_no_school_is_chosen_when_the_user_has_several(db_app, two_schools, add_member):
    ada, school_a, school_b = two_schools
    add_member(ada, school_a)
    add_member(ada, school_b)
    client = db_app.test_client()
    _login(client)

    body = client.get(ME).get_json()

    assert body["active_school"] is None
    assert [m["school"]["name"] for m in body["memberships"]] == ["School A", "School B"]


def test_a_member_can_switch_to_their_school(db_app, two_schools, add_member):
    ada, school_a, school_b = two_schools
    add_member(ada, school_a)
    add_member(ada, school_b)
    client = db_app.test_client()
    _login(client)

    response = _choose(client, school_b)

    assert response.status_code == 200
    assert response.get_json()["active_school"]["code"] == "school-b"
    assert _stored_active_school(db_app) == school_b
    assert client.get(ME).get_json()["active_school"]["code"] == "school-b"


def test_switching_requires_login(db_app, two_schools):
    _ada, school_a, _school_b = two_schools

    response = _choose(db_app.test_client(), school_a)

    assert response.status_code == 401


def test_every_inaccessible_school_gets_the_same_answer(db_app, two_schools, add_member):
    """School A user probing School B, a made-up ID and inactive schools learns nothing."""
    ada, school_a, school_b = two_schools
    add_member(ada, school_a)
    with db_app.app_context():
        closed = School(code="closed-school", name="Closed", county_code=5, is_active=False)
        left = School(code="left-school", name="Left", county_code=6)
        db.session.add_all([closed, left])
        db.session.flush()
        db.session.add_all(
            [
                Membership(user_id=ada, school_id=closed.id, role="teacher"),
                Membership(user_id=ada, school_id=left.id, role="teacher", is_active=False),
            ]
        )
        db.session.commit()
        closed_id, left_id = closed.id, left.id
    client = db_app.test_client()
    _login(client)

    for school_id in (school_b, uuid.uuid4(), closed_id, left_id):
        response = _choose(client, school_id)
        error = response.get_json()["error"]
        assert response.status_code == 403
        assert (error["code"], error["message"]) == (
            "school_not_available",
            "You do not have access to that school.",
        )
        assert "School B" not in response.get_data(as_text=True)

    # The refused attempts did not move the user out of School A.
    assert _stored_active_school(db_app) == school_a


def test_a_platform_admin_has_no_automatic_access_to_schools(db_app, make_user, make_school):
    make_user(email="root@example.com", is_platform_admin=True)
    school = make_school()
    client = db_app.test_client()
    _login(client, email="root@example.com")

    assert _choose(client, school).status_code == 403
    assert client.get(ME).get_json()["memberships"] == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"school_id": "not-a-uuid"},
        {"school_id": 42},
        {"school_id": str(uuid.uuid4()), "role": "school_admin"},
    ],
)
def test_invalid_switch_requests_are_rejected(db_app, make_user, body):
    make_user()
    client = db_app.test_client()
    _login(client)

    response = client.post(ACTIVE_SCHOOL, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize("deactivate", ["membership", "school"])
def test_access_ends_on_the_next_request_after_deactivation(
    db_app, two_schools, add_member, deactivate
):
    ada, school_a, _school_b = two_schools
    membership_id = add_member(ada, school_a)
    client = db_app.test_client()
    _login(client)
    assert client.get(ME).get_json()["active_school"]["id"] == str(school_a)

    with db_app.app_context():
        if deactivate == "membership":
            db.session.get(Membership, membership_id).is_active = False
        else:
            db.session.get(School, school_a).is_active = False
        db.session.commit()

    body = client.get(ME).get_json()

    assert body["active_school"] is None
    assert body["memberships"] == []
    assert _stored_active_school(db_app) is None


def test_school_required_guards_school_endpoints(db_app, two_schools, add_member):
    ada, school_a, school_b = two_schools

    @db_app.get("/test-only/current-school")
    @school_required
    def show_current_school():
        return {"code": current_school().code}

    client = db_app.test_client()
    assert client.get("/test-only/current-school").status_code == 401

    add_member(ada, school_a)
    add_member(ada, school_b)
    _login(client)
    response = client.get("/test-only/current-school")
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "no_active_school"

    _choose(client, school_b)
    assert client.get("/test-only/current-school").get_json() == {"code": "school-b"}


def test_switch_logs_ids_but_no_names(migrated_database, two_schools, add_member, capsys):
    ada, school_a, school_b = two_schools
    add_member(ada, school_a)
    add_member(ada, school_b)
    client = create_app("testing").test_client()
    _login(client)
    capsys.readouterr()

    _choose(client, school_b)
    output = capsys.readouterr().out

    assert f"Active school set: school_id={school_b}" in output
    assert "School B" not in output
    assert "ada@example.com" not in output
