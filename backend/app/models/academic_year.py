"""School years and their terms.

A school records each school year (for example "2027") and up to three terms
inside it, with dates. Later features hang classes and enrolments off a year.

Rules the database enforces itself:
- a year's name is unique within its school, starts before it ends and lasts
  at most MAX_YEAR_DAYS days;
- a term is number 1, 2 or 3, at most once per year, and starts before it
  ends;
- a term always belongs to the same school as its year (a two-column foreign
  key on the year's id and school_id).

Rules that compare several rows (years do not overlap; terms lie inside their
year, in order and without overlapping) are checked by the API, which locks
the school's row while it checks and saves.

Both tables are under Row-Level Security (see the migration). Nothing here is
deleted: mistakes are corrected by editing.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

MAX_YEAR_NAME_LENGTH = 20
MAX_YEAR_DAYS = 400
TERM_NUMBERS = (1, 2, 3)


class AcademicYear(db.Model):
    __tablename__ = "academic_years"
    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_academic_years_school_name"),
        # Lets terms (and later classes) prove they belong to the same school.
        UniqueConstraint("id", "school_id", name="uq_academic_years_id_school"),
        CheckConstraint("name = btrim(name) AND name <> ''", name="name_trimmed"),
        CheckConstraint("starts_on < ends_on", name="starts_before_ends"),
        CheckConstraint(f"ends_on - starts_on <= {MAX_YEAR_DAYS}", name="at_most_400_days"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(MAX_YEAR_NAME_LENGTH))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    terms: Mapped[list["Term"]] = relationship(
        back_populates="academic_year", order_by="Term.number", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<AcademicYear {self.id}>"


class Term(db.Model):
    __tablename__ = "terms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["academic_year_id", "school_id"],
            ["academic_years.id", "academic_years.school_id"],
            name="fk_terms_academic_year_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("academic_year_id", "number", name="uq_terms_year_number"),
        CheckConstraint("number BETWEEN 1 AND 3", name="number_1_to_3"),
        CheckConstraint("starts_on < ends_on", name="starts_before_ends"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    number: Mapped[int] = mapped_column(SmallInteger)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    academic_year: Mapped[AcademicYear] = relationship(back_populates="terms")

    @property
    def name(self) -> str:
        return f"Term {self.number}"

    def __repr__(self) -> str:
        return f"<Term {self.id}>"
