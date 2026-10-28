"""Enrolments: which student is in which class in a school year (C3).

Rules the database enforces itself:
- a student is in at most one class per school year;
- the student, the class and the year all belong to the same school, and
  the class belongs to that year (multi-column foreign keys);
- moving a student changes the class within the same year only (the year is
  part of the class's foreign key).

Only active students can be enrolled: that is checked by the API, because a
foreign key on "is active" would stop students being deactivated.

Under Row-Level Security (see the migration). An enrolment may be removed;
the audit trail keeps the history. Later records (attendance, marks) will
point at enrolments and so stop them being removed.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Enrolment(db.Model):
    __tablename__ = "enrolments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "academic_year_id", "school_id"],
            ["classes.id", "classes.academic_year_id", "classes.school_id"],
            name="fk_enrolments_class_same_year_and_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id", "school_id"],
            ["students.id", "students.school_id"],
            name="fk_enrolments_student_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("academic_year_id", "student_id", name="uq_enrolments_year_student"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column(index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Enrolment {self.id}>"
