import uuid

from sqlalchemy import select

from app.extensions import db
from app.models import AuditEvent

PASSWORD = "correct horse battery"


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _events(app):
    with app.app_context():
        return [
            {
                "action": e.action,
                "outcome": e.outcome,
                "actor": e.actor_user_id,
                "school": e.school_id,
                "target": (e.target_type, e.target_id),
                "request_id": e.request_id,
            }
            for e in db.session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at))
        ]


def test_creating_a_school_is_recorded(db_app, make_user):
    admin_id = make_user(email="root@example.com", is_platform_admin=True)
    client = _client_for(db_app, "root@example.com")

    response = client.post(
        "/api/v1/platform/schools",
        json={"name": "Greenfield Academy", "code": "greenfield-academy", "county_code": 32},
    )
    school_id = uuid.UUID(response.get_json()["school"]["id"])

    [event] = _events(db_app)
    assert event["action"] == "school.created"
    assert (event["outcome"], event["actor"], event["school"]) == ("success", admin_id, school_id)
    assert event["target"] == ("school", school_id)
    assert event["request_id"] == response.headers["X-Request-ID"]


def test_a_refused_platform_request_is_recorded(db_app, make_user):
    user_id = make_user()

    _client_for(db_app, "ada@example.com").get("/api/v1/platform/schools")

    [event] = _events(db_app)
    assert (event["action"], event["outcome"], event["actor"]) == (
        "platform.access",
        "denied",
        user_id,
    )


def test_terminal_membership_changes_are_recorded_without_an_actor(db_app, make_user, make_school):
    make_user()
    school_id = make_school()

    db_app.test_cli_runner().invoke(
        args=[
            "add-membership",
            "--email",
            "ada@example.com",
            "--school-code",
            "greenfield-academy",
            "--role",
            "teacher",
        ]
    )

    [event] = _events(db_app)
    assert (event["action"], event["outcome"]) == ("membership.added", "success")
    assert (event["actor"], event["request_id"], event["school"]) == (None, None, school_id)
    assert event["target"][0] == "membership"


def test_school_switches_are_recorded_including_refusals(
    db_app, make_user, make_school, add_member
):
    user_id = make_user()
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    add_member(user_id, school_a)
    add_member(user_id, school_b)
    outsider_school = make_school(code="school-c", name="School C")
    client = _client_for(db_app, "ada@example.com")

    client.post("/api/v1/auth/active-school", json={"school_id": str(school_b)})
    client.post("/api/v1/auth/active-school", json={"school_id": str(outsider_school)})

    events = _events(db_app)
    assert [(e["action"], e["outcome"]) for e in events] == [
        ("school.selected", "success"),
        ("school.selected", "denied"),
    ]
    assert events[0]["target"] == ("school", school_b)
    assert events[0]["school"] == school_b
    # A refused switch records which school was tried, but against no school.
    assert events[1]["target"] == ("school", outsider_school)
    assert events[1]["school"] is None
    assert all(e["actor"] == user_id for e in events)
