"""Students owing fees across all terms, for fee follow-up (E4).

- One row per student who owes money on their bills added together: what
  they owe now (the same figure as the final balance of their statement,
  see app/api/v1/statements.py), how much of it is overdue, the oldest term
  with something unpaid, their last payment and the primary guardian's
  contact (decisions of 2026-11-10).
- Overdue: the balances of bills whose pay-by date has passed (Kenyan
  time), never more than what is owed now, since a credit on another bill
  lowers what the family owes. A student whose credits cover everything is
  not listed.
- The class is the one the student is enrolled in in the latest school year
  they have a class in; a student who is no longer active is marked as
  having left school but stays on the list while they owe.
- Filters: grade or class (of that latest class), overdue only, and owing at
  least an amount. Largest amount owed first.
- Only reads, with `fees.read` (school administrators, principals, finance
  officers); nobody else (403). Row-Level Security keeps each school to its
  own students. The guardian's phone is shown to the same people who see it
  on a bill. A fixed handful of queries serves any number of students. Not
  audited, like other fee reads; logs carry counts only, never names or
  amounts.
"""

import uuid
from datetime import date

from flask import Blueprint, current_app, jsonify
from sqlalchemy import func, select

from app.api.v1 import academic_years as years_api
from app.api.v1.fees import _day, _student_json, is_past_due
from app.auth.permissions import FEES_READ, permission_required
from app.auth.schools import current_school
from app.extensions import db
from app.models import (
    AcademicYear,
    Bill,
    BillLine,
    Enrolment,
    FeeStructure,
    Guardian,
    Payment,
    PaymentCancellation,
    SchoolClass,
    Student,
    StudentGuardian,
    Term,
)
from app.models.school_class import GRADES
from app.schemas import parse_query
from app.schemas.fees import ArrearsQuery

arrears_bp = Blueprint("arrears", __name__, url_prefix="/school")


def _owing(school_id: uuid.UUID, today: date) -> tuple[dict[uuid.UUID, dict], dict]:
    """Per student who owes: owed now, overdue and the oldest unpaid term;
    and each student's last payment that was not cancelled.

    Plain queries over the school's rows, added up here, rather than joins
    of grouped subqueries or long lists of ids: before PostgreSQL has
    statistics on newly issued bills it can plan those very badly (over 15 s
    instead of a fraction of a second for 1,500 students), and these stay
    fast either way."""
    bills = db.session.execute(
        select(Bill.id, Bill.student_id, Term.number, AcademicYear.name, FeeStructure.due_on)
        .join(Term, Bill.term_id == Term.id)
        .join(AcademicYear, Bill.academic_year_id == AcademicYear.id)
        .join(FeeStructure, Bill.structure_id == FeeStructure.id)
        .where(Bill.school_id == school_id)
        .order_by(Term.starts_on, Bill.id)
    ).all()
    totals = dict(
        db.session.execute(
            select(BillLine.bill_id, func.sum(BillLine.amount_kes))
            .where(BillLine.school_id == school_id)
            .group_by(BillLine.bill_id)
        ).all()
    )
    payments = db.session.execute(
        select(
            Payment.bill_id,
            Payment.amount_kes,
            Payment.paid_on,
            Payment.receipt_number,
            Payment.method,
        )
        .outerjoin(PaymentCancellation, PaymentCancellation.payment_id == Payment.id)
        .where(Payment.school_id == school_id, PaymentCancellation.id.is_(None))
    ).all()
    paid: dict[uuid.UUID, int] = {}
    for payment in payments:
        paid[payment.bill_id] = paid.get(payment.bill_id, 0) + payment.amount_kes

    students: dict[uuid.UUID, dict] = {}
    student_of: dict[uuid.UUID, uuid.UUID] = {}
    for bill_id, student_id, number, year_name, due_on in bills:
        student_of[bill_id] = student_id
        balance = int(totals.get(bill_id, 0)) - paid.get(bill_id, 0)
        sums = students.setdefault(
            student_id, {"owed_kes": 0, "past_due_kes": 0, "oldest_unpaid": None}
        )
        sums["owed_kes"] += balance
        if is_past_due(due_on, today):
            sums["past_due_kes"] += balance
        if balance > 0 and sums["oldest_unpaid"] is None:
            sums["oldest_unpaid"] = {"term": {"number": number}, "year": {"name": year_name}}
    owing = {}
    for student_id, sums in students.items():
        if sums["owed_kes"] > 0:
            past_due = sums.pop("past_due_kes")
            sums["overdue_kes"] = max(0, min(sums["owed_kes"], past_due))
            owing[student_id] = sums

    # The latest payment; on the same day, the later receipt.
    latest: dict[uuid.UUID, tuple] = {}
    for payment in payments:
        student_id = student_of[payment.bill_id]
        key = (payment.paid_on, payment.receipt_number)
        if student_id in owing and (student_id not in latest or key > latest[student_id][0]):
            latest[student_id] = (key, payment)
    last_payments = {
        student_id: {
            "paid_on": payment.paid_on.isoformat(),
            "amount_kes": payment.amount_kes,
            "method": payment.method,
        }
        for student_id, (_, payment) in latest.items()
    }
    return owing, last_payments


def _latest_classes(school_id: uuid.UUID) -> dict[uuid.UUID, tuple[SchoolClass, str]]:
    """Each student's class in the latest school year they have one in, with
    that year's name."""
    rows = db.session.execute(
        select(Enrolment.student_id, SchoolClass, AcademicYear.name)
        .join(SchoolClass, Enrolment.class_id == SchoolClass.id)
        .join(AcademicYear, Enrolment.academic_year_id == AcademicYear.id)
        .where(Enrolment.school_id == school_id)
        .order_by(AcademicYear.starts_on)
    )
    # Later years overwrite earlier ones.
    return {student_id: (school_class, year_name) for student_id, school_class, year_name in rows}


def _contacts(school_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Each student's primary guardian, or else the first by name."""
    rows = db.session.execute(
        select(StudentGuardian.student_id, StudentGuardian.relationship, Guardian)
        .join(Guardian, StudentGuardian.guardian_id == Guardian.id)
        .where(StudentGuardian.school_id == school_id)
        .order_by(StudentGuardian.is_primary.desc(), Guardian.full_name, Guardian.id)
    )
    contacts: dict[uuid.UUID, dict] = {}
    for student_id, relationship, guardian in rows:
        contacts.setdefault(
            student_id,
            {
                "full_name": guardian.full_name,
                "relationship": relationship,
                "phone": guardian.phone,
            },
        )
    return contacts


def _class_json(latest: tuple[SchoolClass, str] | None) -> dict | None:
    # The year tells apart classes of the same name in different years.
    if latest is None:
        return None
    school_class, year_name = latest
    return {
        "id": str(school_class.id),
        "name": school_class.name,
        "grade": school_class.grade,
        "year": {"name": year_name},
    }


@arrears_bp.get("/fees/arrears")
@permission_required(FEES_READ)
def students_owing():
    filters = parse_query(ArrearsQuery)
    today = years_api.school_today()
    school_id = current_school().id
    owing, payments = _owing(school_id, today)
    students, classes, contacts = {}, {}, {}
    if owing:
        students = {
            s.id: s
            for s in db.session.scalars(select(Student).where(Student.school_id == school_id))
        }
        classes = {k: v for k, v in _latest_classes(school_id).items() if k in owing}
        contacts = _contacts(school_id)

    # The classes to filter by: those of everyone owing, before filtering.
    order = list(GRADES)
    choices = sorted(
        {c.id: (c, year) for c, year in classes.values()}.values(),
        key=lambda latest: (order.index(latest[0].grade), latest[0].stream or "", latest[1]),
    )

    rows = []
    for student_id, sums in owing.items():
        latest = classes.get(student_id)
        school_class = latest[0] if latest else None
        if filters.grade and (school_class is None or school_class.grade != filters.grade):
            continue
        if filters.class_id and (school_class is None or school_class.id != filters.class_id):
            continue
        if filters.overdue and sums["overdue_kes"] == 0:
            continue
        if filters.min_kes and sums["owed_kes"] < filters.min_kes:
            continue
        student = students[student_id]
        rows.append(
            {
                "student": _student_json(student),
                "class": _class_json(latest),
                "left_school": not student.is_active,
                **sums,
                "last_payment": payments.get(student_id),
                "contact": contacts.get(student_id),
            }
        )
    rows.sort(key=lambda r: (-r["owed_kes"], r["student"]["full_name"], r["student"]["id"]))
    current_app.logger.info("Students owing listed: students=%s", len(rows))
    return jsonify(
        {
            "school": {"name": current_school().name},
            "today": _day(today),
            "filters": {
                "grades": [
                    {"code": g, "name": GRADES[g]}
                    for g in order
                    if any(c.grade == g for c, _ in choices)
                ],
                "classes": [_class_json(c) for c in choices],
            },
            "students": rows,
            "totals": {
                "students": len(rows),
                "owed_kes": sum(r["owed_kes"] for r in rows),
                "overdue_kes": sum(r["overdue_kes"] for r in rows),
            },
        }
    )
