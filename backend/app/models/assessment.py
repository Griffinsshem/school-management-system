"""Assessments and the marks students get in them (D4).

An assessment ("Mid-term", out of 50) belongs to one subject a class takes,
in one term of that class's school year. Its marks are raw scores, or "did
not sit"; grades are worked out from them later (D5), never stored here.

Rules the database enforces itself:
- the class, its subject, the term and the school year all belong together
  (multi-column foreign keys), so an assessment cannot point at another
  class's subject or another year's term;
- an assessment's name is used once per subject, class and term, whatever
  the letter case; its maximum score is 1 to 1000;
- a locked assessment records who locked it and when;
- a student has at most one mark per assessment, of the same school; a
  mark is a score of 0 or more with at most one decimal place, or "did not
  sit" with no score.

Rules that need other data (a score is not above the maximum; the date is
inside the term; who may change marks) are checked by the API. An
assessment can be deleted only while it has no marks (foreign key).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_ASSESSMENT_NAME_LENGTH = 60
MAX_SCORE_LIMIT = 1000


class Assessment(db.Model):
    __tablename__ = "assessments"
    __table_args__ = (
        # The subject is one this class takes.
        ForeignKeyConstraint(
            ["class_subject_id", "class_id", "school_id"],
            ["class_subjects.id", "class_subjects.class_id", "class_subjects.school_id"],
            name="fk_assessments_class_subject_same_class",
            ondelete="RESTRICT",
        ),
        # The class is in this school year.
        ForeignKeyConstraint(
            ["class_id", "academic_year_id", "school_id"],
            ["classes.id", "classes.academic_year_id", "classes.school_id"],
            name="fk_assessments_class_same_year",
            ondelete="RESTRICT",
        ),
        # The term is in the same school year.
        ForeignKeyConstraint(
            ["term_id", "academic_year_id", "school_id"],
            ["terms.id", "terms.academic_year_id", "terms.school_id"],
            name="fk_assessments_term_same_year",
            ondelete="RESTRICT",
        ),
        # Lets marks prove the assessment is in the same school.
        UniqueConstraint("id", "school_id", name="uq_assessments_id_school"),
        Index(
            "uq_assessments_subject_term_name",
            "class_subject_id",
            "term_id",
            func.lower(text("name")),
            unique=True,
        ),
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_trimmed"),
        CheckConstraint(f"max_score BETWEEN 1 AND {MAX_SCORE_LIMIT}", name="max_score_range"),
        CheckConstraint(
            "(is_locked AND locked_at IS NOT NULL AND locked_by_user_id IS NOT NULL)"
            " OR (NOT is_locked AND locked_at IS NULL AND locked_by_user_id IS NULL)",
            name="lock_recorded",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column(index=True)
    class_subject_id: Mapped[uuid.UUID] = mapped_column()
    term_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(MAX_ASSESSMENT_NAME_LENGTH))
    max_score: Mapped[int] = mapped_column(SmallInteger)
    held_on: Mapped[date] = mapped_column(Date)
    is_locked: Mapped[bool] = mapped_column(default=False, server_default=false())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Assessment {self.id}>"


class Mark(db.Model):
    __tablename__ = "marks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "school_id"],
            ["assessments.id", "assessments.school_id"],
            name="fk_marks_assessment_same_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id", "school_id"],
            ["students.id", "students.school_id"],
            name="fk_marks_student_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("assessment_id", "student_id", name="uq_marks_assessment_student"),
        CheckConstraint(
            # "score IS NOT NULL" must be said: a check on NULL passes.
            "(did_not_sit AND score IS NULL)"
            " OR (NOT did_not_sit AND score IS NOT NULL AND score >= 0)",
            name="score_or_did_not_sit",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    assessment_id: Mapped[uuid.UUID] = mapped_column()
    student_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # Exact decimals: 12.5 stays 12.5. The API refuses a second decimal
    # place before PostgreSQL would round it.
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    did_not_sit: Mapped[bool] = mapped_column(default=False, server_default=false())
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Mark {self.id}>"
