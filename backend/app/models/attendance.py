"""Daily attendance registers and their marks (D1).

A register is one class's attendance for one day; it holds one mark per
student who was in the class when the register was taken. Saved marks stay
with the register even if the student later moves or leaves the class, so
history does not change.

Rules the database enforces itself:
- one register per class per day;
- one mark per student per register;
- a mark's status is present, absent or late; only an absence may carry a
  reason, and only from a short fixed list (no free text about children);
- the class, register, student and year all belong to the same school
  (multi-column foreign keys).

Rules that need other data (the day is inside a term, not in the future;
who may take or correct a register, and how far back) are checked by the API.

Both tables are under Row-Level Security (see the migration). Nothing here is
deleted: corrections change the marks, and the audit trail records them.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

STATUSES = ("present", "absent", "late")
REASONS = ("sick", "permission", "unknown")

_STATUS_LIST = ", ".join(f"'{s}'" for s in STATUSES)
_REASON_LIST = ", ".join(f"'{r}'" for r in REASONS)


class AttendanceRegister(db.Model):
    __tablename__ = "attendance_registers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "academic_year_id", "school_id"],
            ["classes.id", "classes.academic_year_id", "classes.school_id"],
            name="fk_attendance_registers_class_same_year_and_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("class_id", "date", name="uq_attendance_registers_class_date"),
        # Lets marks prove they belong to a register of the same school.
        UniqueConstraint("id", "school_id", name="uq_attendance_registers_id_school"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column()
    date: Mapped[date] = mapped_column(Date)
    taken_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<AttendanceRegister {self.id}>"


class AttendanceMark(db.Model):
    __tablename__ = "attendance_marks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["register_id", "school_id"],
            ["attendance_registers.id", "attendance_registers.school_id"],
            name="fk_attendance_marks_register_same_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id", "school_id"],
            ["students.id", "students.school_id"],
            name="fk_attendance_marks_student_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("register_id", "student_id", name="uq_attendance_marks_register_student"),
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="status_valid"),
        CheckConstraint(
            f"reason IS NULL OR (status = 'absent' AND reason IN ({_REASON_LIST}))",
            name="reason_only_for_absence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    register_id: Mapped[uuid.UUID] = mapped_column(index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<AttendanceMark {self.id}>"
