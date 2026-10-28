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
CLASSES_READ = "classes.read"
CLASSES_MANAGE = "classes.manage"
# Only the classes the user is a class teacher of (see app/api/v1/classes.py).
CLASSES_READ_OWN = "classes.read_own"
ENROLMENTS_MANAGE = "enrolments.manage"
# Attendance (see app/api/v1/attendance.py): reading every class's registers,
# taking and correcting any of them, or taking and correcting those of the
# classes the user teaches (recent days only).
ATTENDANCE_READ = "attendance.read"
ATTENDANCE_RECORD = "attendance.record"
ATTENDANCE_RECORD_OWN = "attendance.record_own"
# Students' guardians (see app/api/v1/guardians.py). Teachers get neither
# (decision of 2026-10-28): contact goes through the office.
GUARDIANS_READ = "guardians.read"
GUARDIANS_MANAGE = "guardians.manage"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "school_admin": frozenset(
        {
            MEMBERS_READ,
            MEMBERS_MANAGE,
            STUDENTS_READ,
            STUDENTS_MANAGE,
            ACADEMICS_READ,
            ACADEMICS_MANAGE,
            CLASSES_READ,
            CLASSES_MANAGE,
            ENROLMENTS_MANAGE,
            ATTENDANCE_READ,
            ATTENDANCE_RECORD,
            GUARDIANS_READ,
            GUARDIANS_MANAGE,
        }
    ),
    "principal": frozenset(
        {
            MEMBERS_READ,
            STUDENTS_READ,
            ACADEMICS_READ,
            CLASSES_READ,
            ATTENDANCE_READ,
            GUARDIANS_READ,
        }
    ),
    # No student access until classes exist: a teacher should see only the
    # students they teach, not the whole school. School years and terms are
    # not personal data, so every staff role may see them. A teacher sees
    # only their own classes, and takes their registers.
    "teacher": frozenset({ACADEMICS_READ, CLASSES_READ_OWN, ATTENDANCE_RECORD_OWN}),
    "finance_officer": frozenset({ACADEMICS_READ}),
    # Registrars see every class and enrol students, but do not create classes.
    "registrar": frozenset(
        {
            STUDENTS_READ,
            STUDENTS_MANAGE,
            ACADEMICS_READ,
            CLASSES_READ,
            ENROLMENTS_MANAGE,
            GUARDIANS_READ,
            GUARDIANS_MANAGE,
        }
    ),
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


def permission_required(permission: str, *alternatives: str):
    """Require login, an active school and `permission` there (401, 403 otherwise).

    With `alternatives`, any one of the permissions is enough; the view then
    decides what each one may see. Refusals are recorded in the audit trail,
    with the first permission as the action.
    """
    accepted = frozenset((permission, *alternatives))
    unknown = accepted - ALL_PERMISSIONS
    if unknown:
        raise ValueError(f"Unknown permission: {', '.join(sorted(unknown))}")

    def decorator(view):
        @wraps(view)
        @school_required
        def wrapped(*args, **kwargs):
            if not accepted & current_permissions():
                audit.record_denied(permission, school_id=current_school().id)
                raise ApiError(403, "forbidden", "You do not have permission to do that.")
            return view(*args, **kwargs)

        return wrapped

    return decorator
