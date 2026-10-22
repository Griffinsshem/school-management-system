"""Creating, revoking and accepting invitations.

Tokens are random (256 bits) and stored only as SHA-256 hashes, like session
tokens. Every way an invitation can be unusable (unknown, expired, revoked,
already used) gives the same answer, so nobody learns which tokens existed.
"""

import uuid

from flask import current_app, g
from sqlalchemy import select, update

from app import audit
from app.auth.passwords import PasswordPolicyError, hash_password
from app.auth.sessions import current_user, hash_token, new_token, utcnow
from app.errors import ApiError
from app.extensions import db
from app.models import Invitation, Membership, School, User
from app.schemas.invitations import InvitationOut
from app.school_context import set_database_school

NOT_VALID = "This invitation link is not valid. Ask the school for a new one."


def status_of(invitation: Invitation) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.expires_at <= utcnow():
        return "expired"
    return "pending"


def to_json(invitation: Invitation) -> dict:
    """An invitation as its school sees it. Never includes the token."""
    out = InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=status_of(invitation),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )
    return out.model_dump(mode="json")


def accept_url(token: str) -> str:
    # The token travels in the URL fragment (after #), which browsers never
    # send to servers, so it cannot reach any request log.
    return f"{current_app.config['FRONTEND_ORIGIN']}/invitations/accept#token={token}"


def create(school: School, email: str, role: str) -> tuple[Invitation, str]:
    """A new invitation for `email` to `role` in `school`, and its token.

    Replaces any pending invitation for the same person and role. The caller
    has set the database school and commits.
    """
    has_role = db.session.scalar(
        select(Membership.id)
        .join(User, Membership.user_id == User.id)
        .where(
            Membership.school_id == school.id,
            Membership.role == role,
            Membership.is_active.is_(True),
            User.email == email,
        )
    )
    if has_role is not None:
        raise ApiError(409, "already_member", "That person already has this role in the school.")

    now = utcnow()
    db.session.execute(
        update(Invitation)
        .where(
            Invitation.school_id == school.id,
            Invitation.email == email,
            Invitation.role == role,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = new_token()
    invitation = Invitation(
        school_id=school.id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by_user_id=g.current_user.id,
        created_at=now,
        expires_at=now + current_app.config["INVITATION_LIFETIME"],
    )
    db.session.add(invitation)
    db.session.flush()
    audit.record(
        "invitation.created",
        school_id=school.id,
        target_type="invitation",
        target_id=invitation.id,
    )
    return invitation, token


def find_usable(token: str, action: str) -> Invitation:
    """The pending, unexpired invitation for `token`, or a 404.

    Reusing a real invitation that is expired, revoked or already used is
    recorded in the audit trail. Unknown tokens are only logged: these
    endpoints need no login, and the audit trail can never be pruned, so
    recording every made-up token would let anyone fill the database.
    """
    invitation = Invitation.find_by_token_hash(hash_token(token))
    if invitation is None:
        current_app.logger.warning("Unknown invitation token")
        raise ApiError(404, "invitation_not_valid", NOT_VALID)
    if status_of(invitation) != "pending":
        audit.record_denied(action, target_type="invitation", target_id=invitation.id)
        raise ApiError(404, "invitation_not_valid", NOT_VALID)
    return invitation


def accept(
    token: str, full_name: str | None, password: str | None
) -> tuple[User, Invitation, bool]:
    """Accept the invitation for `token`. Returns (user, invitation, account_created).

    - No account with the invited email: `full_name` and `password` create one.
    - An account exists: the caller must be logged in as that account.
    Commits.
    """
    found = find_usable(token, "invitation.accepted")
    school_id = found.school_id
    set_database_school(school_id)
    # Lock the invitation so two simultaneous acceptances cannot both succeed.
    invitation = db.session.scalar(
        select(Invitation)
        .where(Invitation.id == found.id, Invitation.accepted_at.is_(None))
        .where(Invitation.revoked_at.is_(None))
        .with_for_update()
    )
    school = db.session.get(School, school_id)
    if invitation is None or school is None or not school.is_active:
        db.session.rollback()
        audit.record_denied("invitation.accepted", target_type="invitation", target_id=found.id)
        raise ApiError(404, "invitation_not_valid", NOT_VALID)

    signed_in = current_user()
    user = db.session.scalar(select(User).where(User.email == invitation.email))
    account_created = False

    if signed_in is not None and signed_in.email != invitation.email:
        db.session.rollback()
        raise ApiError(
            403, "wrong_account", "This invitation is for a different account. Log out first."
        )

    if user is None:
        if not full_name or not password:
            db.session.rollback()
            raise ApiError(
                422,
                "account_details_needed",
                "Enter your full name and choose a password to create your account.",
            )
        try:
            password_hash = hash_password(password)
        except PasswordPolicyError as error:
            db.session.rollback()
            raise ApiError(
                422,
                "invalid_request",
                "Some fields are missing or invalid.",
                details=[{"field": "password", "message": str(error)}],
            ) from None
        user = User(email=invitation.email, full_name=full_name, password_hash=password_hash)
        db.session.add(user)
        db.session.flush()
        account_created = True
    elif signed_in is None:
        db.session.rollback()
        raise ApiError(
            401, "log_in_first", "You already have an account. Log in, then open the link again."
        )
    elif not user.is_active:
        db.session.rollback()
        raise ApiError(404, "invitation_not_valid", NOT_VALID)

    membership = db.session.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.school_id == school_id,
            Membership.role == invitation.role,
        )
    )
    if membership is None:
        db.session.add(Membership(user_id=user.id, school_id=school_id, role=invitation.role))
    else:
        membership.is_active = True

    invitation.accepted_at = utcnow()
    invitation.accepted_by_user_id = user.id
    audit.record(
        "invitation.accepted",
        school_id=school_id,
        target_type="invitation",
        target_id=invitation.id,
        actor_user_id=user.id,
    )
    user_id = user.id
    db.session.commit()
    current_app.logger.info(
        "Invitation accepted: invitation_id=%s user_id=%s school_id=%s new_account=%s",
        found.id,
        user_id,
        school_id,
        account_created,
    )
    return user, invitation, account_created


def revoke(invitation_id: uuid.UUID, school: School) -> Invitation:
    """Revoke a pending invitation of `school`; a recorded 404 if it is not the school's."""
    invitation = db.session.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.school_id == school.id)
        .with_for_update()
    )
    if invitation is None:
        audit.record_denied(
            "invitation.revoked",
            school_id=school.id,
            target_type="invitation",
            target_id=invitation_id,
        )
        raise ApiError(404, "not_found", "Invitation not found.")
    if invitation.accepted_at is not None:
        db.session.rollback()
        raise ApiError(409, "invitation_accepted", "This invitation has already been accepted.")
    if invitation.revoked_at is None:
        invitation.revoked_at = utcnow()
        audit.record(
            "invitation.revoked",
            school_id=school.id,
            target_type="invitation",
            target_id=invitation.id,
        )
    db.session.commit()
    return invitation
