"""School fees: fee structures and students' bills (E1).

A fee structure is the list of fees for one grade in one term (for example
Grade 4, Term 1 of 2027: Tuition 15,000, Activity 2,000, Boarding 30,000
optional). Issuing it gives every student of that grade a bill: a copy of
its compulsory items, so later changes elsewhere never change what a family
owes. Optional items are added to single bills; corrections (a bursary, a
mistake) are adjustments with a reason. Nothing on a bill is ever changed
or deleted: a bill's total is the sum of its lines.

Rules the database enforces itself:
- one structure per grade and term, and one bill per student and term;
- a structure's term, a bill's class, term and structure, and a line's bill
  and fee item all belong to the same school (and year, structure) as each
  other (multi-column foreign keys); a fee line's item is an item of the
  bill's own structure, and appears at most once per bill;
- amounts are whole shillings: an item 1 to 1,000,000; a fee line likewise;
  an adjustment between -1,000,000 and 1,000,000 and never 0;
- names and reasons have no whitespace at either end and are never empty;
- the API's database user cannot change or delete bills or their lines,
  nor delete structures (see the migration).

Rules that need other data (who may change fees; a structure's items are not
changed once issued, though its pay-by date may be; the pay-by date's range;
at most 30 items; a bill's total never below 0; only students
of the structure's grade are billed) are checked by the API. Fee data is
personal financial information: never log names or amounts.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.school_class import GRADES

MAX_FEE_AMOUNT = 1_000_000  # Shillings, per item, line or adjustment.
MAX_FEE_ITEM_NAME_LENGTH = 60
MAX_ADJUSTMENT_REASON_LENGTH = 200
MAX_FEE_ITEMS = 30  # Per structure (checked by the API).
LINE_KINDS = ("fee", "adjustment")

_GRADE_LIST = ", ".join(f"'{grade}'" for grade in GRADES)


def _trimmed(column: str, max_length: int) -> str:
    # Starts and ends with a visible character, so never empty or padded.
    return rf"{column} ~ '^\S' AND {column} ~ '\S$' AND char_length({column}) <= {max_length}"


class FeeStructure(db.Model):
    __tablename__ = "fee_structures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["term_id", "academic_year_id", "school_id"],
            ["terms.id", "terms.academic_year_id", "terms.school_id"],
            name="fk_fee_structures_term_same_year",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("term_id", "grade", name="uq_fee_structures_term_grade"),
        # Lets items and bills prove the same structure, term and school.
        UniqueConstraint("id", "school_id", name="uq_fee_structures_id_school"),
        UniqueConstraint(
            "id", "term_id", "academic_year_id", "school_id", name="uq_fee_structures_id_term"
        ),
        CheckConstraint(f"grade IN ({_GRADE_LIST})", name="grade_valid"),
        CheckConstraint(
            "(issued_at IS NULL) = (issued_by_user_id IS NULL)", name="issued_at_and_by_together"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    term_id: Mapped[uuid.UUID] = mapped_column()
    grade: Mapped[str] = mapped_column(String(10))
    # E4: the day by which the term's fees should be paid (optional). It
    # changes no amount, so it may be set or moved after issuing; the API
    # keeps it from 90 days before the term starts to the term's last day.
    due_on: Mapped[date | None] = mapped_column(Date)
    # Set when the first bills are issued; the API then refuses changes.
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<FeeStructure {self.id}>"


class FeeItem(db.Model):
    __tablename__ = "fee_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["structure_id", "school_id"],
            ["fee_structures.id", "fee_structures.school_id"],
            name="fk_fee_items_structure_same_school",
            ondelete="RESTRICT",
        ),
        # Lets bill lines prove their item is of their bill's structure.
        UniqueConstraint("id", "structure_id", "school_id", name="uq_fee_items_id_structure"),
        CheckConstraint(_trimmed("name", MAX_FEE_ITEM_NAME_LENGTH), name="name_trimmed_and_length"),
        CheckConstraint(f"amount_kes BETWEEN 1 AND {MAX_FEE_AMOUNT}", name="amount_in_range"),
        CheckConstraint("position >= 0", name="position_not_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    structure_id: Mapped[uuid.UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(MAX_FEE_ITEM_NAME_LENGTH))
    amount_kes: Mapped[int] = mapped_column(Integer)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    position: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<FeeItem {self.id}>"


# "Tuition" and "tuition" are the same item. (Declared on the columns: a
# plain string here would lower-case the word "name", not the column.)
Index("uq_fee_items_structure_name", FeeItem.structure_id, func.lower(FeeItem.name), unique=True)


class Bill(db.Model):
    __tablename__ = "bills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["student_id", "school_id"],
            ["students.id", "students.school_id"],
            name="fk_bills_student_same_school",
            ondelete="RESTRICT",
        ),
        # The class the student was in when billed, in the term's year.
        ForeignKeyConstraint(
            ["class_id", "academic_year_id", "school_id"],
            ["classes.id", "classes.academic_year_id", "classes.school_id"],
            name="fk_bills_class_same_year",
            ondelete="RESTRICT",
        ),
        # The structure is this term's.
        ForeignKeyConstraint(
            ["structure_id", "term_id", "academic_year_id", "school_id"],
            [
                "fee_structures.id",
                "fee_structures.term_id",
                "fee_structures.academic_year_id",
                "fee_structures.school_id",
            ],
            name="fk_bills_structure_same_term",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("student_id", "term_id", name="uq_bills_student_term"),
        # Lets lines prove the same bill, structure and school.
        UniqueConstraint("id", "structure_id", "school_id", name="uq_bills_id_structure_school"),
        # Lets payments (E2) prove the same school.
        UniqueConstraint("id", "school_id", name="uq_bills_id_school"),
        Index("ix_bills_term_structure", "term_id", "structure_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    academic_year_id: Mapped[uuid.UUID] = mapped_column()
    term_id: Mapped[uuid.UUID] = mapped_column()
    structure_id: Mapped[uuid.UUID] = mapped_column()
    class_id: Mapped[uuid.UUID] = mapped_column()
    student_id: Mapped[uuid.UUID] = mapped_column()
    issued_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Bill {self.id}>"


class BillLine(db.Model):
    __tablename__ = "bill_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bill_id", "structure_id", "school_id"],
            ["bills.id", "bills.structure_id", "bills.school_id"],
            name="fk_bill_lines_bill_same_structure",
            ondelete="RESTRICT",
        ),
        # A fee line's item is an item of the bill's own structure. (An
        # adjustment has no item, so this does not apply to it.)
        ForeignKeyConstraint(
            ["fee_item_id", "structure_id", "school_id"],
            ["fee_items.id", "fee_items.structure_id", "fee_items.school_id"],
            name="fk_bill_lines_item_same_structure",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("bill_id", "fee_item_id", name="uq_bill_lines_bill_item"),
        CheckConstraint(f"kind IN ({', '.join(repr(k) for k in LINE_KINDS)})", name="kind_valid"),
        CheckConstraint(
            "(kind = 'fee' AND fee_item_id IS NOT NULL"
            f" AND amount_kes BETWEEN 1 AND {MAX_FEE_AMOUNT})"
            " OR (kind = 'adjustment' AND fee_item_id IS NULL"
            f" AND amount_kes BETWEEN -{MAX_FEE_AMOUNT} AND {MAX_FEE_AMOUNT} AND amount_kes <> 0)",
            name="kind_item_and_amount",
        ),
        # A fee line's item name, or an adjustment's reason.
        CheckConstraint(
            _trimmed("description", MAX_ADJUSTMENT_REASON_LENGTH),
            name="description_trimmed_and_length",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    bill_id: Mapped[uuid.UUID] = mapped_column()
    structure_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(10))
    fee_item_id: Mapped[uuid.UUID | None] = mapped_column()
    description: Mapped[str] = mapped_column(String(MAX_ADJUSTMENT_REASON_LENGTH))
    amount_kes: Mapped[int] = mapped_column(Integer)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<BillLine {self.id}>"
