"""Roles and permissions.

Each role grants an explicit set of permissions; nothing is granted by
default. A user's permissions in a school are the union of the permissions
of all their active roles there. Endpoints declare the permission they need
with `permission_required`, and the server checks it on every request.

New permissions are added here by the features that need them.
"""

from functools import wraps

from flask import g
from sqlalchemy import select

from app import audit
from app.auth.schools import current_school, school_required
from app.errors import ApiError
from app.extensions import db
from app.models import Membership

MEMBERS_READ = "members.read"
MEMBERS_MANAGE = "members.manage"
STUDENTS_READ = "students.read"
STUDENTS_MANAGE = "students.manage"
ACADEMICS_READ = "academics.read"
ACADEMICS_MANAGE = "academics.manage"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "school_admin": frozenset(
        {
            MEMBERS_READ,
            MEMBERS_MANAGE,
            STUDENTS_READ,
            STUDENTS_MANAGE,
            ACADEMICS_READ,
            ACADEMICS_MANAGE,
        }
    ),
    "principal": frozenset({MEMBERS_READ, STUDENTS_READ, ACADEMICS_READ}),
    # No student access until classes exist: a teacher should see only the
    # students they teach, not the whole school. School years and terms are
    # not personal data, so every staff role may see them.
    "teacher": frozenset({ACADEMICS_READ}),
    "finance_officer": frozenset({ACADEMICS_READ}),
    "registrar": frozenset({STUDENTS_READ, STUDENTS_MANAGE, ACADEMICS_READ}),
    "guardian": frozenset(),
    "student": frozenset(),
}

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*ROLE_PERMISSIONS.values())


def current_permissions() -> frozenset[str]:
    """The permissions of the logged-in user in the active school (empty if none)."""
    if "current_permissions" in g:
        return g.current_permissions

    permissions: frozenset[str] = frozenset()
    school = current_school()
    if school is not None:
        roles = db.session.scalars(
            select(Membership.role).where(
                Membership.user_id == g.current_user.id,
                Membership.school_id == school.id,
                Membership.is_active.is_(True),
            )
        )
        permissions = frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles))

    g.current_permissions = permissions
    return permissions


def permission_required(permission: str):
    """Require login, an active school and `permission` there (401, 403 otherwise).

    Refusals for a missing permission are recorded in the audit trail, with
    the missing permission as the action.
    """
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")

    def decorator(view):
        @wraps(view)
        @school_required
        def wrapped(*args, **kwargs):
            if permission not in current_permissions():
                audit.record_denied(permission, school_id=current_school().id)
                raise ApiError(403, "forbidden", "You do not have permission to do that.")
            return view(*args, **kwargs)

        return wrapped

    return decorator
