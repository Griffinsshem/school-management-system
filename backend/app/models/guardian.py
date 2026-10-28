"""Guardians: students' parents and other contacts (D2).

A guardian is stored once per school and linked to each student they are
responsible for, so siblings share one record. Only the minimum is kept
(decision of 2026-10-28): full name, a Kenyan phone number, an optional email
and, per student, the relationship and whether this is the first person to
contact. No ID numbers, addresses or free-text notes.

Rules the database enforces itself:
- a phone number is stored in one standard form (+2547XXXXXXXX or
  +2541XXXXXXXX) and appears at most once per school;
- an email, if given, is trimmed and in lower case;
- a relationship is one of a short fixed list;
- a student is linked to a guardian at most once, and has at most one
  primary guardian;
- the student and the guardian belong to the same school as the link
  (multi-column foreign keys).

The limit of guardians per student, and who may see them, are checked by
the API. Both tables are under Row-Level Security (see the migration).
Guardians are corrected, never deleted; removing a guardian from a student
deletes only the link.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_GUARDIAN_NAME_LENGTH = 200
MAX_GUARDIAN_EMAIL_LENGTH = 254
MAX_GUARDIANS_PER_STUDENT = 4
# Kenyan mobile numbers (07..., 01...) in international form.
PHONE_PATTERN = r"^\+254[17][0-9]{8}$"
RELATIONSHIPS = ("mother", "father", "guardian", "grandparent", "sibling", "other_relative")

_RELATIONSHIP_LIST = ", ".join(f"'{r}'" for r in RELATIONSHIPS)


class Guardian(db.Model):
    __tablename__ = "guardians"
    __table_args__ = (
        # One record per person per school: siblings share it.
        UniqueConstraint("school_id", "phone", name="uq_guardians_school_phone"),
        # Lets links prove the guardian is in the same school.
        UniqueConstraint("id", "school_id", name="uq_guardians_id_school"),
        CheckConstraint(
            "full_name = btrim(full_name) AND full_name <> ''", name="full_name_trimmed"
        ),
        CheckConstraint(f"phone ~ '{PHONE_PATTERN}'", name="phone_kenyan_international"),
        CheckConstraint(
            "email IS NULL OR (email = lower(btrim(email)) AND email ~ '^[^@ ]+@[^@ ]+$')",
            name="email_normalised",
        ),
        Index("ix_guardians_school_name", "school_id", "full_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    full_name: Mapped[str] = mapped_column(String(MAX_GUARDIAN_NAME_LENGTH))
    phone: Mapped[str] = mapped_column(String(13))
    email: Mapped[str | None] = mapped_column(String(MAX_GUARDIAN_EMAIL_LENGTH))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Guardian {self.id}>"


class StudentGuardian(db.Model):
    __tablename__ = "student_guardians"
    __table_args__ = (
        ForeignKeyConstraint(
            ["student_id", "school_id"],
            ["students.id", "students.school_id"],
            name="fk_student_guardians_student_same_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["guardian_id", "school_id"],
            ["guardians.id", "guardians.school_id"],
            name="fk_student_guardians_guardian_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("student_id", "guardian_id", name="uq_student_guardians_student_guardian"),
        CheckConstraint(f"relationship IN ({_RELATIONSHIP_LIST})", name="relationship_valid"),
        # At most one primary guardian per student.
        Index(
            "uq_student_guardians_one_primary",
            "student_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    student_id: Mapped[uuid.UUID] = mapped_column()
    guardian_id: Mapped[uuid.UUID] = mapped_column(index=True)
    relationship: Mapped[str] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<StudentGuardian {self.id}>"
