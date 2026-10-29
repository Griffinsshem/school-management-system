"""Subjects, the subjects each class takes, and who teaches them (D3).

Each school keeps its own subject list (decision of 2026-10-28): the
national curriculum changes too often for a built-in list. A subject is
renamed or made inactive, never deleted.

A class takes a subject at most once (a "class subject"), and a class
subject can have several subject teachers. Removing a subject from a class,
or a teacher from a class subject, deletes only that link.

Rules the database enforces itself:
- a subject's name, and its short code if it has one, appear once per
  school regardless of letter case; both are trimmed;
- a class takes each subject at most once, and a teacher is assigned to a
  class subject at most once;
- the class, the subject and the teacher's membership belong to the same
  school, and the membership has the role "teacher" (multi-column foreign
  keys, as for class teachers in C2).

Rules that need other data (only active subjects can be added to a class;
the teacher's membership is active) are checked by the API. All three
tables are under Row-Level Security (see the migration).
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
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.school_class import TEACHER_ROLE

MAX_SUBJECT_NAME_LENGTH = 60
MAX_SUBJECT_CODE_LENGTH = 10


class Subject(db.Model):
    __tablename__ = "subjects"
    __table_args__ = (
        # Lets class subjects prove the subject is in the same school.
        UniqueConstraint("id", "school_id", name="uq_subjects_id_school"),
        Index("uq_subjects_school_name", "school_id", func.lower(text("name")), unique=True),
        Index(
            "uq_subjects_school_code",
            "school_id",
            func.lower(text("code")),
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_trimmed"),
        CheckConstraint("code IS NULL OR (code = btrim(code) AND code <> '')", name="code_trimmed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(MAX_SUBJECT_NAME_LENGTH))
    code: Mapped[str | None] = mapped_column(String(MAX_SUBJECT_CODE_LENGTH))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Subject {self.id}>"


class ClassSubject(db.Model):
    __tablename__ = "class_subjects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_class_subjects_class_same_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_class_subjects_subject_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("class_id", "subject_id", name="uq_class_subjects_class_subject"),
        # Lets subject teachers (and later marks) prove the same school.
        UniqueConstraint("id", "school_id", name="uq_class_subjects_id_school"),
        # Lets assessments prove their subject is one this class takes (D4).
        UniqueConstraint("id", "class_id", "school_id", name="uq_class_subjects_id_class_school"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column(index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<ClassSubject {self.id}>"


class SubjectTeacher(db.Model):
    __tablename__ = "subject_teachers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_subject_id", "school_id"],
            ["class_subjects.id", "class_subjects.school_id"],
            name="fk_subject_teachers_class_subject_same_school",
            ondelete="RESTRICT",
        ),
        # Same school AND the teacher role: the membership must match all three.
        ForeignKeyConstraint(
            ["membership_id", "school_id", "role"],
            ["memberships.id", "memberships.school_id", "memberships.role"],
            name="fk_subject_teachers_teacher_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "class_subject_id", "membership_id", name="uq_subject_teachers_class_subject_membership"
        ),
        CheckConstraint(f"role = '{TEACHER_ROLE}'", name="role_is_teacher"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    class_subject_id: Mapped[uuid.UUID] = mapped_column()
    membership_id: Mapped[uuid.UUID] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(32), default=TEACHER_ROLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<SubjectTeacher {self.id}>"
