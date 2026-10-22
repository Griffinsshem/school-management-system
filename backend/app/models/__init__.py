"""Database models. Importing them here registers them for migrations."""

from app.models.audit_event import AuditEvent
from app.models.invitation import Invitation
from app.models.login_attempt import LoginAttempt
from app.models.membership import Membership
from app.models.school import School
from app.models.session import UserSession
from app.models.student import Student
from app.models.user import User

__all__ = [
    "AuditEvent",
    "Invitation",
    "LoginAttempt",
    "Membership",
    "School",
    "Student",
    "User",
    "UserSession",
]
