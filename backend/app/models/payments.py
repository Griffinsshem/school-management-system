"""Fee payments, receipts and cancellations (E2).

A payment is money received against one bill: an amount in whole shillings,
how it was paid (cash, M-Pesa, bank, cheque) with its reference, the day it
was received and, optionally, who paid. Every payment gets the school's
next receipt number. A mistake is never edited or deleted: an administrator
cancels the payment with a reason (a separate row), it stays visible as
cancelled, and its receipt number is never used again. A bill's balance is
its total minus its payments that are not cancelled; it is worked out each
time, never stored.

Rules the database enforces itself:
- a payment's bill, and a cancellation's payment, belong to the same school
  (multi-column foreign keys);
- amounts are whole shillings, 1 to 1,000,000;
- a cash payment has no reference; an M-Pesa payment has its transaction
  code (10 capital letters and digits); a bank or cheque payment has a
  reference of 1 to 40 characters, never padded;
- the same reference is never recorded twice for the same method in a
  school (ignoring case), and a receipt number is never used twice;
- a payment is cancelled at most once, always with a reason;
- the API's database user cannot change or delete payments or
  cancellations, nor delete receipt counters (see the migration).

Rules that need other data (who may record or cancel; the date paid is not
in the future nor more than a year back; receipt numbers come from the
school's counter, one after another) are checked by the API. Payments are
personal financial information: never log names, amounts or references.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db

MAX_PAYMENT_AMOUNT = 1_000_000  # Shillings, per payment.
MAX_REFERENCE_LENGTH = 40
MAX_PAID_BY_LENGTH = 100
MAX_CANCEL_REASON_LENGTH = 200
MAX_DAYS_BACK = 365  # How far back a payment's date may be (checked by the API).
PAYMENT_METHODS = ("cash", "mpesa", "bank", "cheque")
MPESA_CODE_PATTERN = "^[A-Z0-9]{10}$"


# Takes the school's next receipt number: 1 for its first payment, then one
# more each time. Run in the same transaction as the payment's INSERT: the
# counter row stays locked until that transaction ends, so a second payment
# saved at the same moment waits and gets the next number, and a payment that
# fails rolls the counter back with it (no gaps). The API's user may raise a
# counter but not delete it; setting one lower would only make the next save
# fail on the unique receipt number, never reuse a number.
NEXT_RECEIPT_NUMBER_SQL = """
    INSERT INTO receipt_counters (school_id, last_number) VALUES (:school_id, 1)
    ON CONFLICT (school_id)
        DO UPDATE SET last_number = receipt_counters.last_number + 1, updated_at = now()
    RETURNING last_number
"""


def _trimmed(column: str, max_length: int) -> str:
    # Starts and ends with a visible character, so never empty or padded.
    return rf"{column} ~ '^\S' AND {column} ~ '\S$' AND char_length({column}) <= {max_length}"


class Payment(db.Model):
    __tablename__ = "payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bill_id", "school_id"],
            ["bills.id", "bills.school_id"],
            name="fk_payments_bill_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("school_id", "receipt_number", name="uq_payments_school_receipt"),
        # Lets cancellations prove the same school.
        UniqueConstraint("id", "school_id", name="uq_payments_id_school"),
        Index("ix_payments_bill", "bill_id"),
        Index("ix_payments_school_created", "school_id", "created_at"),
        CheckConstraint(f"amount_kes BETWEEN 1 AND {MAX_PAYMENT_AMOUNT}", name="amount_in_range"),
        CheckConstraint(
            f"method IN ({', '.join(repr(m) for m in PAYMENT_METHODS)})", name="method_valid"
        ),
        CheckConstraint(
            "(method = 'cash' AND reference IS NULL)"
            " OR (method = 'mpesa' AND reference IS NOT NULL"
            f" AND reference ~ '{MPESA_CODE_PATTERN}')"
            " OR (method IN ('bank', 'cheque') AND reference IS NOT NULL"
            f" AND {_trimmed('reference', MAX_REFERENCE_LENGTH)})",
            # Each branch says "IS NOT NULL" itself: a check that comes out
            # NULL (a regex on a NULL reference) counts as passed.
            name="reference_fits_method",
        ),
        CheckConstraint(
            f"paid_by IS NULL OR ({_trimmed('paid_by', MAX_PAID_BY_LENGTH)})",
            name="paid_by_trimmed_and_length",
        ),
        CheckConstraint("receipt_number >= 1", name="receipt_number_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    bill_id: Mapped[uuid.UUID] = mapped_column()
    amount_kes: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(10))
    reference: Mapped[str | None] = mapped_column(String(MAX_REFERENCE_LENGTH))
    # The day the money was received (in Kenya); created_at is when it was recorded.
    paid_on: Mapped[date] = mapped_column(Date)
    paid_by: Mapped[str | None] = mapped_column(String(MAX_PAID_BY_LENGTH))
    receipt_number: Mapped[int] = mapped_column(Integer)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Payment {self.id}>"


# The same M-Pesa code (or bank reference, or cheque) is one payment, however
# it is typed. (Declared on the columns: a plain string would upper-case the
# word "reference", not the column; see the E1 lesson.)
Index(
    "uq_payments_school_method_reference",
    Payment.school_id,
    Payment.method,
    func.upper(Payment.reference),
    unique=True,
    postgresql_where=text("reference IS NOT NULL"),
)


class PaymentCancellation(db.Model):
    __tablename__ = "payment_cancellations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payment_id", "school_id"],
            ["payments.id", "payments.school_id"],
            name="fk_payment_cancellations_payment_same_school",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("payment_id", name="uq_payment_cancellations_payment"),
        CheckConstraint(
            _trimmed("reason", MAX_CANCEL_REASON_LENGTH), name="reason_trimmed_and_length"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column()
    payment_id: Mapped[uuid.UUID] = mapped_column()
    reason: Mapped[str] = mapped_column(String(MAX_CANCEL_REASON_LENGTH))
    cancelled_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<PaymentCancellation {self.id}>"


class ReceiptCounter(db.Model):
    """The last receipt number a school has used. Raised by one inside the
    same transaction as the payment, so a failed save uses no number and two
    payments saved at once get one number each."""

    __tablename__ = "receipt_counters"
    __table_args__ = (CheckConstraint("last_number >= 1", name="last_number_positive"),)

    school_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schools.id", ondelete="RESTRICT"), primary_key=True
    )
    last_number: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReceiptCounter {self.school_id}>"
