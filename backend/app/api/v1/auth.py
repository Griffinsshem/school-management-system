"""Login, logout, "who am I" and choosing the active school."""

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import select

from app.auth import rate_limit
from app.auth.passwords import (
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.auth.permissions import current_permissions
from app.auth.schools import active_memberships, current_school, only_school_id, set_active_school
from app.auth.sessions import (
    clear_session_cookie,
    end_current_session,
    login_required,
    set_session_cookie,
    start_session,
    utcnow,
)
from app.errors import ApiError
from app.extensions import db
from app.models import User
from app.models.user import normalize_email
from app.schemas import parse_json_body
from app.schemas.auth import LoginRequest, UserOut
from app.schemas.schools import MembershipOut, SchoolOut, SelectSchoolRequest

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

INVALID_CREDENTIALS = "Invalid email or password."

# Checked when the email is unknown, so that a failed login takes the same
# time whether or not the account exists (otherwise timing reveals accounts).
_DUMMY_PASSWORD_HASH = hash_password("timing-equalizer-not-a-real-password")


def _user_json(user: User) -> dict:
    return {"user": UserOut.model_validate(user).model_dump(mode="json")}


def _context_json(user: User) -> dict:
    """The user, their schools and roles, and the session's active school."""
    school = current_school()
    memberships = [
        MembershipOut(role=membership.role, school=SchoolOut.model_validate(member_school))
        for membership, member_school in active_memberships(user)
    ]
    return _user_json(user) | {
        "memberships": [membership.model_dump(mode="json") for membership in memberships],
        "active_school": (
            SchoolOut.model_validate(school).model_dump(mode="json") if school else None
        ),
        # For showing or hiding parts of the interface only: every endpoint
        # checks its own permission on the server.
        "permissions": sorted(current_permissions()),
    }


@auth_bp.post("/login")
def login():
    data = parse_json_body(LoginRequest)
    email = normalize_email(data.email)
    now = utcnow()

    retry_after = rate_limit.retry_after_seconds(email, now)
    if retry_after is not None:
        current_app.logger.warning("Login rate-limited")
        raise ApiError(
            429,
            "too_many_attempts",
            "Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.session.scalar(select(User).where(User.email == email))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(password_hash, data.password)

    if user is None or not user.is_active or not password_matches:
        rate_limit.record_failure(email, now)
        db.session.commit()
        current_app.logger.warning("Login failed")
        raise ApiError(401, "invalid_credentials", INVALID_CREDENTIALS)

    rate_limit.clear_account_failures(email)
    if needs_rehash(user.password_hash):
        try:
            user.password_hash = hash_password(data.password)
        except PasswordPolicyError:
            pass  # An old password that predates the rules keeps its old hash.
    user.last_login_at = now
    # A user who belongs to exactly one school starts in it.
    token = start_session(user, active_school_id=only_school_id(user))
    db.session.commit()

    current_app.logger.info("Login succeeded: user_id=%s", user.id)
    response = jsonify(_user_json(user))
    set_session_cookie(response, token)
    return response, 200


@auth_bp.post("/logout")
def logout():
    end_current_session()
    db.session.commit()
    response = current_app.response_class(status=204)
    clear_session_cookie(response)
    return response


@auth_bp.get("/me")
@login_required
def me():
    return jsonify(_context_json(g.current_user)), 200


@auth_bp.post("/active-school")
@login_required
def choose_active_school():
    data = parse_json_body(SelectSchoolRequest)
    school = set_active_school(g.current_user, data.school_id)
    current_app.logger.info(
        "Active school set: school_id=%s user_id=%s", school.id, g.current_user.id
    )
    return jsonify(_context_json(g.current_user)), 200
