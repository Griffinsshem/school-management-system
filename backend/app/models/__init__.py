"""Database models. Importing them here registers them for migrations."""

from app.models.academic_year import AcademicYear, Term
from app.models.attendance import AttendanceMark, AttendanceRegister
from app.models.audit_event import AuditEvent
from app.models.enrolment import Enrolment
from app.models.guardian import Guardian, StudentGuardian
from app.models.invitation import Invitation
from app.models.login_attempt import LoginAttempt
from app.models.membership import Membership
from app.models.school import School
from app.models.school_class import ClassTeacher, SchoolClass
from app.models.session import UserSession
from app.models.student import Student
from app.models.subject import ClassSubject, Subject, SubjectTeacher
from app.models.user import User

__all__ = [
    "AcademicYear",
    "AttendanceMark",
    "AttendanceRegister",
    "AuditEvent",
    "ClassSubject",
    "ClassTeacher",
    "Enrolment",
    "Guardian",
    "Invitation",
    "LoginAttempt",
    "Membership",
    "School",
    "SchoolClass",
    "Student",
    "StudentGuardian",
    "Subject",
    "SubjectTeacher",
    "Term",
    "User",
    "UserSession",
]
