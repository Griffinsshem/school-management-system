"""Fee statements and printable bills (E3).

- A student's statement lists every charge on their bills (fees, optional
  items, adjustments), every payment and every cancellation, across all
  terms, in date order with a running balance (decisions of 2026-11-07):
  - a bill line is dated the day it was added to the bill (Kenyan time),
    a payment the day it was paid, a cancellation the day it was made;
  - on the same day, charges come first, then payments, then cancellations;
  - a cancelled payment is listed twice: as the payment, and as its
    cancellation adding the amount back, so nothing silently disappears.
  The final running balance equals the student's bills added together.
- Printable bills for a grade's whole term: each bill with its lines, what
  is paid, its balance, the balance from earlier terms and the amount due
  now (see `_earlier` in app/api/v1/fees.py). A few queries serve the whole
  grade, not one per student.
- Both only read, with `fees.read` (school administrators, principals,
  finance officers); nobody else (403). Another school's ids are not found.
  Statements carry no guardian contacts: they go home on paper. Reads are
  not audited, like other fee reads; logs carry ids only.
"""

import uuid
from datetime import datetime

from flask import Blueprint, jsonify
from sqlalchemy import select

from app.api.v1 import academic_years as years_api
from app.api.v1.fees import (
    STUDENT_NOT_FOUND,
    _day,
    _earlier,
    _earlier_json,
    _grade_classes,
    _money,
    _not_found,
    _paid,
    _structure,
    _student_json,
    _term,
    _term_json,
    _with_earlier,
)
from app.auth.permissions import FEES_READ, permission_required
from app.auth.schools import current_school
from app.extensions import db
from app.models import (
    AcademicYear,
    Bill,
    BillLine,
    FeeItem,
    Payment,
    PaymentCancellation,
    SchoolClass,
    Student,
    Term,
)
from app.models.school_class import GRADES

statements_bp = Blueprint("statements", __name__, url_prefix="/school")

# On the same day: charges, then payments, then cancellations.
CHARGE, PAYMENT, CANCELLATION = 0, 1, 2


def _kenyan_day(moment: datetime) -> str:
    return moment.astimezone(years_api.SCHOOL_TIME_ZONE).date().isoformat()


def _signed(amount: int) -> dict:
    """What an entry adds to what is owed (debit) or takes off it (credit)."""
    if amount >= 0:
        return {"debit_kes": amount, "credit_kes": None}
    return {"debit_kes": None, "credit_kes": -amount}


@statements_bp.get("/fees/students/<uuid:student_id>/statement")
@permission_required(FEES_READ)
def statement(student_id: uuid.UUID):
    student = db.session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == current_school().id)
    )
    if student is None:
        _not_found("fees.read", "student", student_id, STUDENT_NOT_FOUND)

    bills = db.session.execute(
        select(Bill, Term, AcademicYear, SchoolClass)
        .join(Term, Bill.term_id == Term.id)
        .join(AcademicYear, Bill.academic_year_id == AcademicYear.id)
        .join(SchoolClass, Bill.class_id == SchoolClass.id)
        .where(Bill.student_id == student.id)
        .order_by(Term.starts_on)
    ).all()
    terms = {
        bill.id: {"term": {"number": term.number}, "year": {"name": year.name}}
        for bill, term, year, _ in bills
    }
    ids = list(terms)

    # (day, kind of entry, order within the kind, entry)
    entries: list[tuple[str, int, int, dict]] = []
    lines = (
        db.session.scalars(
            select(BillLine)
            .outerjoin(FeeItem, BillLine.fee_item_id == FeeItem.id)
            .where(BillLine.bill_id.in_(ids))
            # In the order they were added; a bill's fees in the structure's order.
            .order_by(BillLine.created_at, FeeItem.position.nulls_last(), BillLine.id)
        ).all()
        if ids
        else []
    )
    for n, line in enumerate(lines):
        entry = {
            "date": _kenyan_day(line.created_at),
            "kind": line.kind,
            "description": line.description,
            "bill_id": str(line.bill_id),
            **terms[line.bill_id],
            **_signed(line.amount_kes),
            "payment": None,
        }
        entries.append((entry["date"], CHARGE, n, entry))

    payments = (
        db.session.execute(
            select(Payment, PaymentCancellation)
            .outerjoin(PaymentCancellation, PaymentCancellation.payment_id == Payment.id)
            .where(Payment.bill_id.in_(ids))
            .order_by(Payment.receipt_number)
        ).all()
        if ids
        else []
    )
    for n, (payment, cancellation) in enumerate(payments):
        about = {
            "id": str(payment.id),
            "receipt_number": payment.receipt_number,
            "method": payment.method,
            "reference": payment.reference,
        }
        entry = {
            "date": payment.paid_on.isoformat(),
            "kind": "payment",
            "description": "Payment",
            "bill_id": str(payment.bill_id),
            **terms[payment.bill_id],
            **_signed(-payment.amount_kes),
            "payment": about,
        }
        entries.append((entry["date"], PAYMENT, n, entry))
        if cancellation is not None:
            entry = {
                "date": _kenyan_day(cancellation.created_at),
                "kind": "cancellation",
                "description": cancellation.reason,
                "bill_id": str(payment.bill_id),
                **terms[payment.bill_id],
                **_signed(payment.amount_kes),
                "payment": about,
            }
            entries.append((entry["date"], CANCELLATION, n, entry))

    entries.sort(key=lambda e: e[:3])
    balance = 0
    for *_, entry in entries:
        balance += (entry["debit_kes"] or 0) - (entry["credit_kes"] or 0)
        entry["balance_kes"] = balance

    charged = sum(line.amount_kes for line in lines)
    paid = sum(p.amount_kes for p, c in payments if c is None)
    return jsonify(
        {
            "school": {"name": current_school().name},
            "student": _student_json(student),
            # The class on the student's latest bill.
            "class_name": bills[-1][3].name if bills else None,
            "printed_on": years_api.school_today().isoformat(),
            "entries": [entry for *_, entry in entries],
            "totals": {"charged_kes": charged, "paid_kes": paid, "balance_kes": charged - paid},
        }
    )


@statements_bp.get("/fees/years/<uuid:year_id>/terms/<int:number>/grades/<grade>/bills/print")
@permission_required(FEES_READ)
def grade_bills_for_printing(year_id: uuid.UUID, number: int, grade: str):
    """Every bill of a grade for a term, ready to print one per page, class
    by class."""
    term = _term(year_id, number, "fees.read")
    _grade_classes(term, grade, "fees.read")
    structure = _structure(term, grade)
    rows = []
    if structure is not None:
        rows = db.session.execute(
            select(Bill, Student, SchoolClass)
            .join(Student, Bill.student_id == Student.id)
            .join(SchoolClass, Bill.class_id == SchoolClass.id)
            .where(Bill.structure_id == structure.id)
            .order_by(SchoolClass.stream.nulls_first(), Student.full_name, Student.admission_number)
        ).all()
    ids = [bill.id for bill, _, _ in rows]
    lines: dict[uuid.UUID, list[dict]] = {}
    if ids:
        for line in db.session.scalars(
            select(BillLine)
            .outerjoin(FeeItem, BillLine.fee_item_id == FeeItem.id)
            .where(BillLine.bill_id.in_(ids))
            .order_by(BillLine.created_at, FeeItem.position.nulls_last(), BillLine.id)
        ):
            lines.setdefault(line.bill_id, []).append(
                {"kind": line.kind, "description": line.description, "amount_kes": line.amount_kes}
            )
    paid = _paid(ids)
    earlier = _earlier([bill.student_id for bill, _, _ in rows], term.starts_on)
    return jsonify(
        {
            "school": {"name": current_school().name},
            **_term_json(term),
            "grade": {"code": grade, "name": GRADES[grade]},
            # E4: printed on each bill as "Pay by".
            "due_on": _day(structure.due_on) if structure else None,
            "bills": [
                {
                    "id": str(bill.id),
                    "student": _student_json(student),
                    "class_name": school_class.name,
                    "lines": lines.get(bill.id, []),
                    **_with_earlier(
                        _money(
                            sum(line["amount_kes"] for line in lines.get(bill.id, [])),
                            paid.get(bill.id, 0),
                        ),
                        _earlier_json(earlier.get(bill.student_id, [])),
                    ),
                }
                for bill, student, school_class in rows
            ],
        }
    )
