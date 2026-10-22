"""Which school a request is working in.

The active school is stored in the server-side session and is re-checked on
every request: the user must still have an active membership in a school
that is still active. Nothing in the request itself can choose the school,
except POST /api/v1/auth/active-school, which runs the same check first.

Every feature that reads or changes school data gets the school from
`current_school()` (or the `school_required` decorator), never from the URL
or request body.
"""

import uuid
from functools import wraps

from flask import g
from sqlalchemy import select

from app import audit
from app.auth.sessions import current_user
from app.errors import ApiError
from app.extensions import db
from app.models import Membership, School, User, UserSession
from app.school_context import set_database_school

SCHOOL_NOT_AVAILABLE = "You do not have access to that school."


def active_memberships(user: User) -> list[tuple[Membership, School]]:
    """The user's active memberships in active schools, ordered by school name."""
    rows = db.session.execute(
        select(Membership, School)
        .join(School, Membership.school_id == School.id)
        .where(
            Membership.user_id == user.id,
            Membership.is_active.is_(True),
            School.is_active.is_(True),
        )
        .order_by(School.name, Membership.role)
    )
    return [(membership, school) for membership, school in rows]


def accessible_school(user: User, school_id: uuid.UUID) -> School | None:
    """The school, if `user` has an active membership in it and it is active."""
    return db.session.scalar(
        select(School)
        .join(Membership, Membership.school_id == School.id)
        .where(
            School.id == school_id,
            School.is_active.is_(True),
            Membership.user_id == user.id,
            Membership.is_active.is_(True),
        )
        .limit(1)
    )


def only_school_id(user: User) -> uuid.UUID | None:
    """The school ID if the user belongs to exactly one active school, else None."""
    school_ids = {school.id for _membership, school in active_memberships(user)}
    return school_ids.pop() if len(school_ids) == 1 else None


def current_school() -> School | None:
    """The active school for this request, or None.

    If the stored school is no longer accessible (membership or school
    deactivated), it is cleared from the session straight away.
    """
    if "current_school" in g:
        return g.current_school

    g.current_school = None
    user = current_user()
    if user is None:
        return None

    user_session: UserSession = g.current_session
    if user_session.active_school_id is None:
        return None

    school = accessible_school(user, user_session.active_school_id)
    if school is None:
        user_session.active_school_id = None
        db.session.commit()
        return None

    g.current_school = school
    # The transaction already in progress learns its school now; later
    # transactions in this request get it from the after_begin listener.
    set_database_school(school.id)
    return school


def set_active_school(user: User, school_id: uuid.UUID) -> School:
    """Make `school_id` this session's active school, or raise 403. Commits."""
    school = accessible_school(user, school_id)
    if school is None:
        # Recorded, because it may be someone probing other schools.
        audit.record_denied("school.selected", target_type="school", target_id=school_id)
        # The same answer whether the school does not exist, is inactive or
        # belongs to someone else, so other schools' IDs cannot be probed.
        raise ApiError(403, "school_not_available", SCHOOL_NOT_AVAILABLE)

    school_id = school.id
    g.current_session.active_school_id = school_id
    audit.record("school.selected", school_id=school_id, target_type="school", target_id=school_id)
    db.session.commit()
    g.current_school = school
    set_database_school(school_id)
    return school


def school_required(view):
    """Require a logged-in user working in an active school (401 or 403 otherwise)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            raise ApiError(401, "unauthorized", "You need to log in to do that.")
        if current_school() is None:
            raise ApiError(403, "no_active_school", "Choose a school first.")
        return view(*args, **kwargs)

    return wrapped
