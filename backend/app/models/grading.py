"""A school's KCSE grade boundaries (D5).

Grades are never stored: they are worked out from raw marks when shown
(app/grading.py). The CBC/KJSEA scale is fixed in code; only the KCSE
letter grades used for Form classes have boundaries a school can change,
and those are kept here, one row per grade per school. A school with no
rows uses the default boundaries.

Rules the database enforces itself:
- the grade is one of the 12 KCSE grades, used once per school;
- a boundary is a whole percentage from 0 to 100, and E starts at 0 so
  every percentage gets a grade.

That the boundaries go down from A to E spans several rows, so the API
checks it, saving all 12 together.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

# Best first, with their points (KCSE).
KCSE_GRADES: dict[str, int] = {
    "A": 12,
    "A-": 11,
    "B+": 10,
    "B": 9,
    "B-": 8,
    "C+": 7,
    "C": 6,
    "C-": 5,
    "D+": 4,
    "D": 3,
    "D-": 2,
    "E": 1,
}
_GRADE_LIST = ", ".join(f"'{grade}'" for grade in KCSE_GRADES)


class GradeBoundary(db.Model):
    __tablename__ = "grade_boundaries"
    __table_args__ = (
        UniqueConstraint("school_id", "grade", name="uq_grade_boundaries_school_grade"),
        CheckConstraint(f"grade IN ({_GRADE_LIST})", name="grade_valid"),
        CheckConstraint("min_percent BETWEEN 0 AND 100", name="min_percent_range"),
        CheckConstraint("grade <> 'E' OR min_percent = 0", name="lowest_starts_at_zero"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    grade: Mapped[str] = mapped_column(String(2))
    min_percent: Mapped[int] = mapped_column(SmallInteger)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<GradeBoundary {self.grade}>"
