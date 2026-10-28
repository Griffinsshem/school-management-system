"""Classes in a school year, and their class teachers (C2).

A class is a grade (and optionally a stream, such as "East") in one school
year, for example "Grade 4 East" in 2027. A class can have several class
teachers.

Kenya is moving from 8-4-4 (Forms 1 to 4) to the Competency-Based
Curriculum (Grades 1 to 12), one year group at a time, so which grades exist
depends on the year: see `grade_exists_in`.

Rules the database enforces itself:
- the grade is one of GRADES; a stream is trimmed and not empty;
- a grade and stream appear at most once per school year (a class with no
  stream counts as one, so there is only one "Grade 4" without a stream);
- a class belongs to the same school as its year, and a class teacher's
  membership to the same school as the class (two-column foreign keys);
- a class teacher's membership has the role "teacher" (the foreign key
  includes the role, and the role column here may only say "teacher").

Both tables are under Row-Level Security (see the migration). Classes are
never deleted; a class teacher assignment can be removed.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

# Every grade, in school order, with the name people use.
GRADES: dict[str, str] = {
    "pp1": "PP1",
    "pp2": "PP2",
    **{f"grade_{n}": f"Grade {n}" for n in range(1, 13)},
    **{f"form_{n}": f"Form {n}" for n in range(1, 5)},
}
MAX_STREAM_LENGTH = 20
TEACHER_ROLE = "teacher"

_GRADE_LIST = ", ".join(f"'{code}'" for code in GRADES)

# The transition, by calendar year (checked 2026-10-27, see docs):
# - Grade 7 first ran in 2023, Grade 8 in 2024, Grade 9 in 2025 (junior
#   school), Grade 10 in 2026 (senior school), Grade 11 in 2027, Grade 12 in
#   2028: Grade n (7 to 12) exists from the year 2016 + n.
# - The last Form 1 class was admitted in 2024, so Form n exists up to the
#   year 2023 + n (the last Form 4, and KCSE, is in 2027).
# PP1, PP2 and Grades 1 to 6 are always offered.
FIRST_CBC_YEAR_OFFSET = 2016
LAST_FORM_YEAR_OFFSET = 2023


def grade_exists_in(grade: str, year: int) -> bool:
    """Whether Kenyan schools have this grade in this calendar year."""
    kind, _, number = grade.partition("_")
    if kind == "grade" and int(number) >= 7:
        return year >= FIRST_CBC_YEAR_OFFSET + int(number)
    if kind == "form":
        return year <= LAST_FORM_YEAR_OFFSET + int(number)
    return grade in GRADES


def grades_in(year: int) -> list[str]:
    """The grades offered for a school year starting in this calendar year."""
    return [grade for grade in GRADES if grade_exists_in(grade, year)]


class SchoolClass(db.Model):
    # "class" is a Python keyword, hence SchoolClass.
    __tablename__ = "classes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["academic_year_id", "school_id"],
            ["academic_years.id", "academic_years.school_id"],
            name="fk_classes_academic_year_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "academic_year_id",
            "grade",
            "stream",
            name="uq_classes_year_grade_stream",
            postgresql_nulls_not_distinct=True,
        ),
        # Lets class teachers prove the same school, and enrolments the same
        # year and school.
        UniqueConstraint("id", "school_id", name="uq_classes_id_school"),
        UniqueConstraint("id", "academic_year_id", "school_id", name="uq_classes_id_year_school"),
        CheckConstraint(f"grade IN ({_GRADE_LIST})", name="grade_valid"),
        CheckConstraint(
            "stream IS NULL OR (stream = btrim(stream) AND stream <> '')", name="stream_trimmed"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column(index=True)
    grade: Mapped[str] = mapped_column(String(10))
    stream: Mapped[str | None] = mapped_column(String(MAX_STREAM_LENGTH))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    teachers: Mapped[list["ClassTeacher"]] = relationship(
        back_populates="school_class", lazy="selectin"
    )

    @property
    def name(self) -> str:
        label = GRADES[self.grade]
        return f"{label} {self.stream}" if self.stream else label

    def __repr__(self) -> str:
        return f"<SchoolClass {self.id}>"


class ClassTeacher(db.Model):
    __tablename__ = "class_teachers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["classes.id", "classes.school_id"],
            name="fk_class_teachers_class_same_school",
            ondelete="RESTRICT",
        ),
        # Same school AND the teacher role: the membership must match all three.
        ForeignKeyConstraint(
            ["membership_id", "school_id", "role"],
            ["memberships.id", "memberships.school_id", "memberships.role"],
            name="fk_class_teachers_teacher_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("class_id", "membership_id", name="uq_class_teachers_class_membership"),
        CheckConstraint(f"role = '{TEACHER_ROLE}'", name="role_is_teacher"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column()
    membership_id: Mapped[uuid.UUID] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String(32), default=TEACHER_ROLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    school_class: Mapped[SchoolClass] = relationship(back_populates="teachers")

    def __repr__(self) -> str:
        return f"<ClassTeacher {self.id}>"
