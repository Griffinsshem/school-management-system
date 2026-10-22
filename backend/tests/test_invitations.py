import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import create_app
from app.extensions import db
from app.models import AuditEvent, Invitation, Membership, School, User
from app.school_context import set_database_school

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new password"
INVITATIONS = "/api/v1/school/invitations"
PREVIEW = "/api/v1/invitations/preview"
ACCEPT = "/api/v1/invitations/accept"


def _client_for(app, email):
    client = app.test_client()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client


def _token(response) -> str:
    url = response.get_json()["accept_url"]
    assert url.startswith("http://localhost:3000/invitations/accept#token=")
    return url.split("#token=", 1)[1]


def _events(app, action):
    with app.app_context():
        rows = db.session.execute(
            select(AuditEvent.outcome, AuditEvent.actor_user_id)
            .where(AuditEvent.action == action)
            .order_by(AuditEvent.occurred_at)
        )
        return [tuple(row) for row in rows]


def _count(app, model) -> int:
    with app.app_context():
        return db.session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def school(db_app, make_user, make_school, add_member):
    """School A with an admin, a principal and a teacher; School B with its own admin."""
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    people = {}
    for role in ("school_admin", "principal", "teacher"):
        people[role] = make_user(email=f"{role}@example.com")
        add_member(people[role], school_a, role)
    people["b_admin"] = make_user(email="b_admin@example.com")
    add_member(people["b_admin"], school_b, "school_admin")
    return school_a, school_b, people


@pytest.fixture
def admin(db_app, school):
    return _client_for(db_app, "school_admin@example.com")


def _invite(client, email="new.teacher@example.com", role="teacher"):
    response = client.post(INVITATIONS, json={"email": email, "role": role})
    assert response.status_code == 201, response.get_json()
    return response


# Access rules.

ENDPOINTS = [
    ("post", INVITATIONS, {"email": "x@example.com", "role": "teacher"}),
    ("get", INVITATIONS, None),
    ("post", f"{INVITATIONS}/{uuid.uuid4()}/revoke", None),
]


@pytest.mark.parametrize(("method", "url", "body"), ENDPOINTS)
def test_school_endpoints_need_a_login(db_app, school, method, url, body):
    assert getattr(db_app.test_client(), method)(url, json=body).status_code == 401


@pytest.mark.parametrize(("method", "url", "body"), ENDPOINTS)
def test_teachers_cannot_manage_invitations(db_app, school, method, url, body):
    client = _client_for(db_app, "teacher@example.com")

    response = getattr(client, method)(url, json=body)

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_principals_can_list_but_not_invite(db_app, school):
    client = _client_for(db_app, "principal@example.com")

    assert client.get(INVITATIONS).status_code == 200
    assert (
        client.post(INVITATIONS, json={"email": "x@example.com", "role": "teacher"}).status_code
        == 403
    )


# Creating.


def test_creating_an_invitation(db_app, school, admin):
    response = _invite(admin, email=" New.Teacher@Example.com ")
    invitation = response.get_json()["invitation"]
    token = _token(response)

    assert invitation["email"] == "new.teacher@example.com"
    assert (invitation["role"], invitation["status"]) == ("teacher", "pending")
    expires = datetime.fromisoformat(invitation["expires_at"])
    assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= timedelta(days=7)
    # Only the hash of the token is stored.
    with db_app.app_context():
        set_database_school(school[0])
        stored = db.session.scalar(select(Invitation.token_hash))
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in str(invitation)
    assert _events(db_app, "invitation.created") == [("success", school[2]["school_admin"])]


def test_a_new_invitation_replaces_the_pending_one(db_app, school, admin):
    first = _token(_invite(admin))
    second = _token(_invite(admin))

    assert admin.post(PREVIEW, json={"token": first}).status_code == 404
    assert admin.post(PREVIEW, json={"token": second}).status_code == 200
    statuses = [i["status"] for i in admin.get(INVITATIONS).get_json()["invitations"]]
    assert sorted(statuses) == ["pending", "revoked"]


def test_inviting_someone_who_already_has_the_role_is_refused(db_app, school, admin):
    response = admin.post(INVITATIONS, json={"email": "teacher@example.com", "role": "teacher"})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "already_member"


def test_an_existing_member_can_be_invited_to_another_role(db_app, school, admin):
    _invite(admin, email="teacher@example.com", role="guardian")


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "role": "teacher"},
        {"email": "x@example.com", "role": "platform_admin"},
        {"email": "x@example.com"},
        {"email": "x@example.com", "role": "teacher", "school_id": str(uuid.uuid4())},
    ],
)
def test_invalid_invitations_are_rejected(db_app, school, admin, body):
    assert admin.post(INVITATIONS, json=body).status_code == 422


def test_the_list_shows_only_this_school_and_never_tokens(db_app, school, admin):
    _invite(admin)
    b_admin = _client_for(db_app, "b_admin@example.com")
    _invite(b_admin, email="b.teacher@example.com")

    listed = admin.get(INVITATIONS).get_json()["invitations"]

    assert [i["email"] for i in listed] == ["new.teacher@example.com"]
    assert set(listed[0]) == {"id", "email", "role", "status", "created_at", "expires_at"}


# Revoking.


def test_revoking_kills_the_link(db_app, school, admin):
    response = _invite(admin)
    invitation_id = response.get_json()["invitation"]["id"]

    revoked = admin.post(f"{INVITATIONS}/{invitation_id}/revoke")
    again = admin.post(f"{INVITATIONS}/{invitation_id}/revoke")

    assert revoked.status_code == again.status_code == 200
    assert revoked.get_json()["invitation"]["status"] == "revoked"
    assert admin.post(PREVIEW, json={"token": _token(response)}).status_code == 404
    assert len(_events(db_app, "invitation.revoked")) == 1


def test_another_schools_invitation_cannot_be_revoked(db_app, school, admin):
    b_admin = _client_for(db_app, "b_admin@example.com")
    b_response = _invite(b_admin, email="b.teacher@example.com")
    b_invitation = b_response.get_json()["invitation"]["id"]

    response = admin.post(f"{INVITATIONS}/{b_invitation}/revoke")

    assert response.status_code == 404
    assert _events(db_app, "invitation.revoked") == [("denied", school[2]["school_admin"])]
    assert b_admin.post(PREVIEW, json={"token": _token(b_response)}).status_code == 200


def test_an_accepted_invitation_cannot_be_revoked(db_app, school, admin):
    response = _invite(admin)
    db_app.test_client().post(
        ACCEPT,
        json={"token": _token(response), "full_name": "New Teacher", "password": NEW_PASSWORD},
    )

    revoked = admin.post(f"{INVITATIONS}/{response.get_json()['invitation']['id']}/revoke")

    assert revoked.status_code == 409


# Platform administrators.


def test_platform_admin_invites_a_schools_first_admin(db_app, make_user, make_school):
    make_user(email="root@example.com", is_platform_admin=True)
    school_id = make_school()
    root = _client_for(db_app, "root@example.com")

    response = root.post(
        f"/api/v1/platform/schools/{school_id}/invitations", json={"email": "head@example.com"}
    )

    assert response.status_code == 201
    assert response.get_json()["invitation"]["role"] == "school_admin"
    preview = db_app.test_client().post(PREVIEW, json={"token": _token(response)}).get_json()
    assert preview["invitation"]["school"]["code"] == "greenfield-academy"


@pytest.mark.parametrize("target", ["unknown", "inactive"])
def test_platform_invitations_need_an_active_school(db_app, make_user, make_school, target):
    make_user(email="root@example.com", is_platform_admin=True)
    school_id = make_school(is_active=False) if target == "inactive" else uuid.uuid4()

    response = _client_for(db_app, "root@example.com").post(
        f"/api/v1/platform/schools/{school_id}/invitations", json={"email": "head@example.com"}
    )

    assert response.status_code == 404


def test_school_admins_cannot_use_the_platform_endpoint(db_app, school, admin):
    response = admin.post(
        f"/api/v1/platform/schools/{school[0]}/invitations", json={"email": "head@example.com"}
    )

    assert response.status_code == 403


# Previewing.


def test_preview_shows_what_the_invitation_is_for(db_app, school, admin):
    token = _token(_invite(admin))

    body = db_app.test_client().post(PREVIEW, json={"token": token}).get_json()["invitation"]

    assert body["email"] == "new.teacher@example.com"
    assert body["role"] == "teacher"
    assert body["school"]["name"] == "School A"
    assert body["has_account"] is False


def test_preview_tells_an_existing_user_to_log_in(db_app, school, admin):
    token = _token(_invite(admin, email="teacher@example.com", role="guardian"))

    body = db_app.test_client().post(PREVIEW, json={"token": token}).get_json()

    assert body["invitation"]["has_account"] is True


def _make_unusable(app, school_id, token, how):
    with app.app_context():
        set_database_school(school_id)
        invitation = Invitation.find_by_token_hash(hashlib.sha256(token.encode()).hexdigest())
        invitation = db.session.get(Invitation, invitation.id)
        if how == "expired":
            invitation.created_at = datetime.now(UTC) - timedelta(days=8)
            invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif how == "revoked":
            invitation.revoked_at = datetime.now(UTC)
        db.session.commit()


@pytest.mark.parametrize("how", ["unknown", "expired", "revoked", "used"])
def test_every_unusable_link_gets_the_same_answer(db_app, school, admin, how):
    token = _token(_invite(admin))
    if how == "unknown":
        token = "made-up-token"
    elif how == "used":
        db_app.test_client().post(
            ACCEPT, json={"token": token, "full_name": "New Teacher", "password": NEW_PASSWORD}
        )
    else:
        _make_unusable(db_app, school[0], token, how)
    client = db_app.test_client()

    preview = client.post(PREVIEW, json={"token": token})
    accept = client.post(
        ACCEPT, json={"token": token, "full_name": "X Y", "password": NEW_PASSWORD}
    )

    for response in (preview, accept):
        error = response.get_json()["error"]
        assert response.status_code == 404
        assert (error["code"], error["message"]) == (
            "invitation_not_valid",
            "This invitation link is not valid. Ask the school for a new one.",
        )
    # Reuse of a real invitation is audited; made-up tokens are only logged,
    # so nobody can fill the (never pruned) audit trail with junk.
    previewed = _events(db_app, "invitation.previewed")
    assert len(previewed) == (0 if how == "unknown" else 1)


@pytest.mark.parametrize("body", [{}, {"token": ""}, {"token": "x" * 129}, {"token": "t", "x": 1}])
def test_malformed_token_requests_are_rejected(db_app, body):
    assert db_app.test_client().post(PREVIEW, json=body).status_code == 422


# Accepting with a new account.


def test_accepting_creates_the_account_and_signs_in(db_app, school, admin):
    token = _token(_invite(admin))
    client = db_app.test_client()

    response = client.post(
        ACCEPT, json={"token": token, "full_name": " New Teacher ", "password": NEW_PASSWORD}
    )

    assert response.status_code == 201
    body = response.get_json()
    assert (body["account_created"], body["role"]) == (True, "teacher")
    assert body["user"]["full_name"] == "New Teacher"
    me = client.get("/api/v1/auth/me").get_json()
    assert me["active_school"]["code"] == "school-a"
    assert [m["role"] for m in me["memberships"]] == ["teacher"]
    new_user = uuid.UUID(body["user"]["id"])
    assert _events(db_app, "invitation.accepted") == [("success", new_user)]
    # The new person can log in normally afterwards, with the password they chose.
    login = db_app.test_client().post(
        "/api/v1/auth/login", json={"email": "new.teacher@example.com", "password": NEW_PASSWORD}
    )
    assert login.status_code == 200


def test_a_new_account_needs_a_name_and_password(db_app, school, admin):
    token = _token(_invite(admin))
    client = db_app.test_client()
    users_before = _count(db_app, User)

    missing = client.post(ACCEPT, json={"token": token})
    weak = client.post(
        ACCEPT, json={"token": token, "full_name": "New Teacher", "password": "short"}
    )

    assert missing.status_code == 422
    assert missing.get_json()["error"]["code"] == "account_details_needed"
    assert weak.status_code == 422
    assert weak.get_json()["error"]["details"][0]["field"] == "password"
    assert "short" not in weak.get_data(as_text=True)
    assert _count(db_app, User) == users_before
    # The invitation is still usable after a failed attempt.
    assert client.post(PREVIEW, json={"token": token}).status_code == 200


def test_a_link_works_only_once(db_app, school, admin):
    token = _token(_invite(admin))
    body = {"token": token, "full_name": "New Teacher", "password": NEW_PASSWORD}

    first = db_app.test_client().post(ACCEPT, json=body)
    second = db_app.test_client().post(ACCEPT, json=body | {"full_name": "Someone Else"})

    assert first.status_code == 201
    assert second.status_code == 404
    assert _count(db_app, Membership) == 5


def test_a_deactivated_school_cannot_be_joined(db_app, school, admin):
    token = _token(_invite(admin))
    with db_app.app_context():
        db.session.get(School, school[0]).is_active = False
        db.session.commit()

    response = db_app.test_client().post(
        ACCEPT, json={"token": token, "full_name": "New Teacher", "password": NEW_PASSWORD}
    )

    assert response.status_code == 404


# Accepting with an existing account.


def test_an_existing_user_must_log_in_first(db_app, school, admin):
    token = _token(_invite(admin, email="teacher@example.com", role="guardian"))

    response = db_app.test_client().post(ACCEPT, json={"token": token})

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "log_in_first"


def test_a_logged_in_user_accepts_another_role(db_app, school, admin):
    token = _token(_invite(admin, email="teacher@example.com", role="guardian"))
    teacher = _client_for(db_app, "teacher@example.com")

    response = teacher.post(ACCEPT, json={"token": token})

    assert response.status_code == 200
    assert response.get_json()["account_created"] is False
    roles = sorted(m["role"] for m in teacher.get("/api/v1/auth/me").get_json()["memberships"])
    assert roles == ["guardian", "teacher"]


@pytest.mark.parametrize(
    "invitee", ["teacher@example.com", "brand.new@example.com"], ids=["existing", "new"]
)
def test_a_different_logged_in_user_cannot_accept(db_app, school, admin, invitee):
    token = _token(_invite(admin, email=invitee, role="guardian"))
    principal = _client_for(db_app, "principal@example.com")
    users_before = _count(db_app, User)

    response = principal.post(
        ACCEPT, json={"token": token, "full_name": "Hijacker", "password": NEW_PASSWORD}
    )

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "wrong_account"
    assert _count(db_app, User) == users_before


def test_invitation_logs_hold_no_emails_or_tokens(migrated_database, school, capsys):
    app = create_app("testing")
    admin_client = _client_for(app, "school_admin@example.com")
    capsys.readouterr()

    token = _token(_invite(admin_client))
    app.test_client().post(
        ACCEPT, json={"token": token, "full_name": "New Teacher", "password": NEW_PASSWORD}
    )
    output = capsys.readouterr().out

    assert "Invitation created: invitation_id=" in output
    assert "Invitation accepted: invitation_id=" in output
    assert "new.teacher@example.com" not in output
    assert token not in output
