"""Invitations in the database: Row-Level Security and the narrow lookup function.

These tests talk to PostgreSQL directly as the API's user (sms_app).
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.extensions import db
from app.models import Invitation
from app.school_context import set_database_school

INSUFFICIENT_PRIVILEGE = "42501"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _in_school(connection, school_id) -> None:
    connection.execute(
        text("SELECT set_config('app.current_school_id', :value, true)"),
        {"value": str(school_id) if school_id else ""},
    )


@pytest.fixture
def invitations(db_app, make_user, make_school, make_invitation):
    """One invitation in School A and one in School B."""
    inviter = make_user(email="admin@example.com")
    school_a = make_school(code="school-a", name="School A")
    school_b = make_school(code="school-b", name="School B")
    a_id, a_token = make_invitation(school_a, inviter, email="a@example.com", token="token-a")
    b_id, b_token = make_invitation(school_b, inviter, email="b@example.com", token="token-b")
    return {"school_a": school_a, "school_b": school_b, "inviter": inviter, "a": a_id, "b": b_id}


def _emails(connection, where="") -> list[str]:
    rows = connection.execute(text(f"SELECT email FROM invitations {where}"))  # noqa: S608
    return sorted(row[0] for row in rows)


def test_each_school_sees_only_its_own_invitations(db_app, invitations):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, invitations["school_a"])
        assert _emails(connection) == ["a@example.com"]

        _in_school(connection, invitations["school_b"])
        assert _emails(connection) == ["b@example.com"]


def test_without_a_school_no_invitations_are_visible(db_app, invitations):
    with db_app.app_context(), db.engine.connect() as connection:
        assert _emails(connection) == []


def test_invitations_cannot_be_written_into_another_school(db_app, invitations):
    with db_app.app_context(), db.engine.connect() as connection:
        _in_school(connection, invitations["school_a"])
        with pytest.raises(ProgrammingError) as excinfo:
            connection.execute(
                text(
                    "INSERT INTO invitations (id, school_id, email, role, token_hash, "
                    "invited_by_user_id, expires_at) VALUES (:id, :school, 'x@example.com', "
                    "'teacher', :hash, :inviter, now() + interval '1 day')"
                ),
                {
                    "id": uuid.uuid4(),
                    "school": invitations["school_b"],
                    "hash": _hash("intruder"),
                    "inviter": invitations["inviter"],
                },
            )

    assert excinfo.value.orig.sqlstate == INSUFFICIENT_PRIVILEGE


def test_the_lookup_function_finds_exactly_one_token_without_a_school(db_app, invitations):
    with db_app.app_context(), db.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, email FROM invitation_by_token_hash(:hash)"),
            {"hash": _hash("token-b")},
        ).all()

    assert [(row.id, row.email) for row in rows] == [(invitations["b"], "b@example.com")]


@pytest.mark.parametrize(
    "probe", ["", "%", "token-b", _hash("token-b").upper(), _hash("token-b")[:-1], "' OR 1=1 --"]
)
def test_the_lookup_function_cannot_be_used_to_search(db_app, invitations, probe):
    with db_app.app_context(), db.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT * FROM invitation_by_token_hash(:hash)"), {"hash": probe}
        ).all()

    assert rows == []


def test_the_lookup_function_is_locked_down(db_app):
    with db_app.app_context(), db.engine.connect() as connection:
        definer, config, acl = connection.execute(
            text(
                "SELECT prosecdef, proconfig, proacl::text FROM pg_proc "
                "WHERE proname = 'invitation_by_token_hash'"
            )
        ).one()

    assert definer is True
    assert config == ["search_path=public, pg_temp"]
    # Only the owner and sms_app may call it; PUBLIC (an entry starting "=") may not.
    assert "sms_app=X/" in acl
    assert "{=" not in acl and ",=" not in acl


def test_the_model_uses_the_lookup_function(db_app, invitations):
    with db_app.app_context():
        found = Invitation.find_by_token_hash(_hash("token-a"))
        missing = Invitation.find_by_token_hash(_hash("no-such-token"))

        assert found.id == invitations["a"]
        assert found.email == "a@example.com"
        assert missing is None


def test_only_one_pending_invitation_per_person_role_and_school(
    db_app, invitations, make_invitation
):
    school_a, inviter = invitations["school_a"], invitations["inviter"]

    make_invitation(school_a, inviter, email="a@example.com", role="guardian", token="t2")
    with pytest.raises(IntegrityError) as excinfo:
        make_invitation(school_a, inviter, email="a@example.com", token="t3")

    assert excinfo.value.orig.sqlstate == UNIQUE_VIOLATION


def test_a_revoked_invitation_does_not_block_a_new_one(db_app, invitations, make_invitation):
    school_a, inviter = invitations["school_a"], invitations["inviter"]
    with db_app.app_context():
        set_database_school(school_a)
        db.session.get(Invitation, invitations["a"]).revoked_at = datetime.now(UTC)
        db.session.commit()

    make_invitation(school_a, inviter, email="a@example.com", token="t4")


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "Mixed@Example.com"},
        {"role": "platform_admin"},
        {"expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"revoked_at": datetime.now(UTC), "accepted_at": datetime.now(UTC)},
        {"accepted_at": datetime.now(UTC)},
    ],
)
def test_database_rejects_inconsistent_invitations(db_app, invitations, make_invitation, fields):
    values = {"email": "new@example.com"} | fields
    if "revoked_at" in fields:
        values["accepted_by_user_id"] = invitations["inviter"]

    with pytest.raises(IntegrityError) as excinfo:
        make_invitation(invitations["school_a"], invitations["inviter"], token="t5", **values)

    assert excinfo.value.orig.sqlstate == CHECK_VIOLATION


def test_expiry_is_stored_with_a_time_zone(db_app, invitations):
    with db_app.app_context():
        set_database_school(invitations["school_a"])
        expires_at = db.session.get(Invitation, invitations["a"]).expires_at

    assert expires_at.tzinfo is not None
    assert expires_at > datetime.now(UTC) + timedelta(days=6)


def test_repr_does_not_reveal_the_email():
    invitation = Invitation(email="secret@example.com")
    invitation.id = uuid.uuid4()

    assert repr(invitation) == f"<Invitation {invitation.id}>"
