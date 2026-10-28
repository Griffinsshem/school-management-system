"""Students: the first school-owned records.

Students are children, so only the minimum is stored for now. More fields
arrive with the features that need them.

Every row belongs to one school, and PostgreSQL Row-Level Security limits
the API's database user to the rows of the school set for the current
transaction (see app/school_context.py and the migration). Students are
deactivated, never deleted.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_ADMISSION_NUMBER_LENGTH = 30
MAX_STUDENT_NAME_LENGTH = 200


class Student(db.Model):
    __tablename__ = "students"
    __table_args__ = (
        # Admission numbers repeat across schools, never within one.
        UniqueConstraint("school_id", "admission_number", name="uq_students_school_admission"),
        # Lets enrolments prove the student is in the same school.
        UniqueConstraint("id", "school_id", name="uq_students_id_school"),
        CheckConstraint(
            "admission_number = btrim(admission_number) AND admission_number <> ''",
            name="admission_number_trimmed",
        ),
        CheckConstraint(
            "full_name = btrim(full_name) AND full_name <> ''", name="full_name_trimmed"
        ),
        Index("ix_students_school_name", "school_id", "full_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    admission_number: Mapped[str] = mapped_column(String(MAX_ADMISSION_NUMBER_LENGTH))
    full_name: Mapped[str] = mapped_column(String(MAX_STUDENT_NAME_LENGTH))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        # The ID only: a child's name or admission number must not reach logs.
        return f"<Student {self.id}>"
