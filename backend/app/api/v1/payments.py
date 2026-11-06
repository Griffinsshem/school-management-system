"""Fee payments, receipts and cancellations (E2).

- A payment is money received against one bill: whole shillings, how it was
  paid (cash, M-Pesa, bank, cheque) and its reference, the day it was
  received (not in the future, at most a year back) and optionally who paid.
  Paying more than is owed is allowed: the bill then shows a credit.
- Each payment takes the school's next receipt number in the same
  transaction (see app/models/payments.py), so numbers have no gaps and are
  never used twice. The same M-Pesa code, bank reference or cheque number is
  never recorded twice in a school (the database refuses it too).
- A mistake is cancelled with a reason, never edited or deleted: the payment
  stays listed as cancelled, it no longer counts, and its number is not
  used again. To fix an amount, cancel and record again.
- Who may do what (decisions of 2026-11-06): school administrators and
  finance officers record (`payments.record`); only school administrators
  cancel (`payments.cancel`); principals and everyone with `fees.read` see
  payments and receipts; nobody else (403). Another school's ids are not
  found.
- Audited as `payment.recorded` and `payment.cancelled`, with ids only.
  Payments are personal financial information: logs carry ids, never names,
  amounts or references.
"""

import uuid
from datetime import date, datetime, time, timedelta

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import audit
from app.api.v1 import academic_years as years_api
from app.api.v1.fees import (
    _bill_for_change,
    _bill_json,
    _not_found,
    _student_json,
    _term_json,
    _user_names,
    payment_json,
)
from app.auth.permissions import FEES_READ, PAYMENTS_CANCEL, PAYMENTS_RECORD, permission_required
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import (
    Bill,
    BillLine,
    FeeStructure,
    Payment,
    PaymentCancellation,
    SchoolClass,
    Student,
    Term,
)
from app.models.payments import MAX_DAYS_BACK, NEXT_RECEIPT_NUMBER_SQL, PAYMENT_METHODS
from app.models.school_class import GRADES
from app.schemas import parse_json_body, parse_query
from app.schemas.payments import (
    METHOD_NAMES,
    CancelPaymentRequest,
    PaymentsDayQuery,
    RecordPaymentRequest,
)

payments_bp = Blueprint("payments", __name__, url_prefix="/school")

PAYMENT_NOT_FOUND = "Payment not found."
ALREADY_CANCELLED = "This payment has already been cancelled."
UNIQUE_VIOLATION = "23505"


def _invalid(message: str) -> ApiError:
    details = [{"field": "", "message": message}]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def _date_problem(day: date) -> str | None:
    today = years_api.school_today()
    if day > today:
        return "The date paid cannot be in the future."
    if day < today - timedelta(days=MAX_DAYS_BACK):
        return f"The date paid can be at most {MAX_DAYS_BACK} days ago."
    return None


def _reference_taken(method: str) -> ApiError:
    what = {
        "mpesa": "This M-Pesa code",
        "bank": "This bank reference",
        "cheque": "This cheque number",
    }[method]
    return ApiError(
        409,
        "duplicate_reference",
        f"{what} has already been recorded for a payment in this school."
        " Check the student's bills before recording it again.",
    )


def _payment(payment_id: uuid.UUID, action: str) -> Payment:
    payment = db.session.scalar(
        select(Payment).where(Payment.id == payment_id, Payment.school_id == current_school().id)
    )
    if payment is None:
        _not_found(action, "payment", payment_id, PAYMENT_NOT_FOUND)
    return payment


@payments_bp.post("/fees/bills/<uuid:bill_id>/payments")
@permission_required(PAYMENTS_RECORD)
def record_payment(bill_id: uuid.UUID):
    # The student's row is locked (one change to a student's bills at a time).
    bill = _bill_for_change(bill_id, "payment.recorded")
    body = parse_json_body(RecordPaymentRequest)
    problem = _date_problem(body.paid_on)
    if problem:
        db.session.rollback()
        raise _invalid(problem)

    number = db.session.execute(
        text(NEXT_RECEIPT_NUMBER_SQL), {"school_id": bill.school_id}
    ).scalar_one()
    payment = Payment(
        id=uuid.uuid4(),
        school_id=bill.school_id,
        bill_id=bill.id,
        amount_kes=body.amount_kes,
        method=body.method,
        reference=body.reference,
        paid_on=body.paid_on,
        paid_by=body.paid_by,
        receipt_number=number,
        recorded_by_user_id=g.current_user.id,
    )
    db.session.add(payment)
    try:
        db.session.flush()
    except IntegrityError as error:
        # The same reference already recorded (now, or by someone else at
        # the same moment): the database's unique index decides, ignoring
        # case. The receipt counter rolls back with it, so no number is lost.
        db.session.rollback()
        if getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION:
            raise _reference_taken(body.method) from None
        raise
    audit.record(
        "payment.recorded", school_id=bill.school_id, target_type="payment", target_id=payment.id
    )
    db.session.commit()
    current_app.logger.info("Payment recorded: payment_id=%s bill_id=%s", payment.id, bill.id)
    names = _user_names({payment.recorded_by_user_id})
    return jsonify({"payment": payment_json(payment, None, names), "bill": _bill_json(bill)}), 201


@payments_bp.post("/fees/payments/<uuid:payment_id>/cancellation")
@permission_required(PAYMENTS_CANCEL)
def cancel_payment(payment_id: uuid.UUID):
    payment = _payment(payment_id, "payment.cancelled")
    bill = _bill_for_change(payment.bill_id, "payment.cancelled")
    body = parse_json_body(CancelPaymentRequest)
    already = db.session.scalar(
        select(PaymentCancellation.id).where(PaymentCancellation.payment_id == payment.id)
    )
    if already is not None:
        db.session.rollback()
        raise ApiError(409, "already_cancelled", ALREADY_CANCELLED)
    db.session.add(
        PaymentCancellation(
            school_id=payment.school_id,
            payment_id=payment.id,
            reason=body.reason,
            cancelled_by_user_id=g.current_user.id,
        )
    )
    db.session.flush()
    audit.record(
        "payment.cancelled",
        school_id=payment.school_id,
        target_type="payment",
        target_id=payment.id,
    )
    db.session.commit()
    current_app.logger.info("Payment cancelled: payment_id=%s bill_id=%s", payment.id, bill.id)
    return jsonify(_bill_json(bill)), 201


def _balance_after(payment: Payment) -> int:
    """The bill's balance just after this payment was recorded: the lines
    and payments of that moment, so a receipt printed again later shows the
    same figure (later adjustments, payments or cancellations do not change
    it)."""
    moment = payment.created_at
    total = db.session.scalar(
        select(func.coalesce(func.sum(BillLine.amount_kes), 0)).where(
            BillLine.bill_id == payment.bill_id, BillLine.created_at <= moment
        )
    )
    paid = db.session.scalar(
        select(func.coalesce(func.sum(Payment.amount_kes), 0))
        .outerjoin(
            PaymentCancellation,
            (PaymentCancellation.payment_id == Payment.id)
            & (PaymentCancellation.created_at <= moment),
        )
        .where(
            Payment.bill_id == payment.bill_id,
            Payment.receipt_number <= payment.receipt_number,
            PaymentCancellation.id.is_(None),
        )
    )
    return int(total) - int(paid)


@payments_bp.get("/fees/payments/<uuid:payment_id>")
@permission_required(FEES_READ)
def get_payment(payment_id: uuid.UUID):
    """Everything a receipt shows."""
    payment = _payment(payment_id, "fees.read")
    bill = db.session.get(Bill, payment.bill_id)
    student = db.session.get(Student, bill.student_id)
    school_class = db.session.get(SchoolClass, bill.class_id)
    structure = db.session.get(FeeStructure, bill.structure_id)
    term = db.session.get(Term, bill.term_id)
    cancellation = db.session.scalar(
        select(PaymentCancellation).where(PaymentCancellation.payment_id == payment.id)
    )
    names = _user_names(
        {payment.recorded_by_user_id, cancellation and cancellation.cancelled_by_user_id}
    )
    return jsonify(
        {
            "payment": payment_json(payment, cancellation, names),
            "school": {"name": current_school().name},
            "bill": {
                "id": str(bill.id),
                **_term_json(term),
                "student": _student_json(student),
                "class_name": school_class.name,
                "grade": {"code": structure.grade, "name": GRADES[structure.grade]},
            },
            "balance_after_kes": _balance_after(payment),
        }
    )


@payments_bp.get("/fees/payments")
@permission_required(FEES_READ)
def payments_on_a_day():
    """Every payment recorded on a day (Kenyan time; today by default), for
    checking the cash drawer and M-Pesa statement before banking. Cancelled
    payments are listed but not counted."""
    day = parse_query(PaymentsDayQuery).date or years_api.school_today()
    start = datetime.combine(day, time.min, tzinfo=years_api.SCHOOL_TIME_ZONE)
    end = start + timedelta(days=1)
    rows = db.session.execute(
        select(Payment, PaymentCancellation, Bill, Student, SchoolClass)
        .outerjoin(PaymentCancellation, PaymentCancellation.payment_id == Payment.id)
        .join(Bill, Payment.bill_id == Bill.id)
        .join(Student, Bill.student_id == Student.id)
        .join(SchoolClass, Bill.class_id == SchoolClass.id)
        .where(Payment.created_at >= start, Payment.created_at < end)
        .order_by(Payment.receipt_number)
    ).all()
    names = _user_names(
        {p.recorded_by_user_id for p, *_ in rows}
        | {c.cancelled_by_user_id for _, c, *_ in rows if c is not None}
    )
    totals = {method: 0 for method in PAYMENT_METHODS}
    for payment, cancellation, *_ in rows:
        if cancellation is None:
            totals[payment.method] += payment.amount_kes
    return jsonify(
        {
            "date": day.isoformat(),
            "payments": [
                {
                    **payment_json(payment, cancellation, names),
                    "bill_id": str(bill.id),
                    "student": _student_json(student),
                    "class_name": school_class.name,
                }
                for payment, cancellation, bill, student, school_class in rows
            ],
            "totals": [
                {"method": method, "name": METHOD_NAMES[method], "amount_kes": totals[method]}
                for method in PAYMENT_METHODS
            ],
            "total_kes": sum(totals.values()),
            "cancelled": sum(1 for _, cancellation, *_ in rows if cancellation is not None),
        }
    )
