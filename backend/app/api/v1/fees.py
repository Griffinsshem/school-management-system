"""School fees: fee structures and students' bills (E1).

- A grade's fee structure for a term is a list of named items in whole
  shillings, each compulsory or optional. It can be changed until bills are
  issued from it; after that, bills are corrected one by one.
- Issuing bills gives every active student enrolled in that grade's classes
  that school year a bill for the term (once: a student has at most one bill
  per term), with a copy of each compulsory item. Students who join later
  are billed by issuing again.
- An optional item (boarding, transport) is added to a single bill.
  Adjustments (a bursary, a mistake) add a signed amount with a reason. A
  bill's total is the sum of its lines and never goes below 0. Nothing on a
  bill is ever changed or deleted (the database refuses it too).
- A bill shows the student's guardians' contacts (name, relationship,
  phone, email) for fee follow-up (decision of 2026-11-04): only for billed
  students, read-only, and without the guardian pages' search by phone.
- Who may do what (decisions of 2026-11-04): school administrators and
  finance officers (`fees.manage`) do everything; principals (`fees.read`)
  read; nobody else sees fees (403). Another school's ids are not found.
- Every change is audited (`fee_structure.saved`, `fee_bills.issued`,
  `bill.item_added`, `bill.adjusted`), with ids only.
- E2: bills, grade pages, the term overview and the student page also show
  what has been paid and what is still owed. A bill's balance is its total
  minus its payments that are not cancelled (see app/api/v1/payments.py);
  it is worked out each time, never stored, and below 0 when overpaid. Fee data is personal
  financial information: logs carry ids and counts, never names or amounts.
- E3 (decision of 2026-11-07): a bill also shows the balance of the
  student's bills from earlier terms (terms that start before its own, in any
  grade or class) and the amount due now (its own balance plus that). This
  too is worked out each time, never stored or copied onto the bill, so a
  late payment or cancellation on an old bill shows at once; a credit from
  an earlier term lowers the amount due now. Statements and printable bills
  are in app/api/v1/statements.py.
- E4 (decisions of 2026-11-10): a grade's fee structure for a term may have
  a pay-by date, set or moved by `fees.manage` even after issuing (it
  changes no amount), from 90 days before the term starts to the term's
  last day; audited as `fee_structure.due_date_changed`. A bill with a
  balance is overdue from the day after its pay-by date, in Kenyan time.
  The list of students owing is in app/api/v1/arrears.py.
"""

import uuid
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import delete, func, select

from app import audit
from app.api.v1 import academic_years as years_api
from app.api.v1.guardians import _links
from app.auth.permissions import (
    FEES_MANAGE,
    FEES_READ,
    PAYMENTS_CANCEL,
    PAYMENTS_RECORD,
    current_permissions,
    permission_required,
)
from app.auth.schools import current_school
from app.errors import ApiError
from app.extensions import db
from app.models import (
    AcademicYear,
    Bill,
    BillLine,
    Enrolment,
    FeeItem,
    FeeStructure,
    Payment,
    PaymentCancellation,
    School,
    SchoolClass,
    Student,
    Term,
    User,
)
from app.models.school_class import GRADES
from app.schemas import parse_json_body
from app.schemas.fees import (
    AddBillItemRequest,
    AdjustBillRequest,
    DueDateRequest,
    SaveStructureRequest,
)

fees_bp = Blueprint("fees", __name__, url_prefix="/school")

TERM_NOT_FOUND = "Term not found."
GRADE_NOT_FOUND = "There are no classes of this grade in this school year."
BILL_NOT_FOUND = "Bill not found."
STUDENT_NOT_FOUND = "Student not found."
STRUCTURE_ISSUED = (
    "Bills have been issued from this fee structure, so it can no longer be changed."
    " Correct single bills with adjustments instead."
)
NO_FEE_ITEMS = "Add at least one fee item and save the fee structure before issuing bills."
NO_STRUCTURE_FOR_DUE_DATE = "Save the fee structure before setting a pay-by date."
# A pay-by date may be up to this long before the term starts (many schools
# ask for fees by opening day or earlier).
DUE_DATE_EARLIEST_BEFORE_TERM = timedelta(days=90)


# Looking things up.


def _not_found(action: str, target_type: str, target_id: uuid.UUID | None, message: str):
    audit.record_denied(
        action, school_id=current_school().id, target_type=target_type, target_id=target_id
    )
    raise ApiError(404, "not_found", message)


def _can_manage() -> bool:
    return FEES_MANAGE in current_permissions()


def _term(year_id: uuid.UUID, number: int, action: str) -> Term:
    """A term of this school, by school year and number (as elsewhere in the API)."""
    term = db.session.scalar(
        select(Term).where(
            Term.academic_year_id == year_id,
            Term.number == number,
            Term.school_id == current_school().id,
        )
    )
    if term is None:
        _not_found(action, "academic_year", year_id, TERM_NOT_FOUND)
    return term


def _grade_classes(term: Term, grade: str, action: str) -> list[SchoolClass]:
    classes = []
    if grade in GRADES:
        classes = list(
            db.session.scalars(
                select(SchoolClass).where(
                    SchoolClass.academic_year_id == term.academic_year_id,
                    SchoolClass.grade == grade,
                )
            )
        )
    if not classes:
        _not_found(action, "term", term.id, GRADE_NOT_FOUND)
    return classes


def _structure(term: Term, grade: str, *, lock: bool = False) -> FeeStructure | None:
    query = select(FeeStructure).where(FeeStructure.term_id == term.id, FeeStructure.grade == grade)
    if lock:
        query = query.with_for_update()
    return db.session.scalar(query)


def _items(structure: FeeStructure) -> list[FeeItem]:
    return list(
        db.session.scalars(
            select(FeeItem)
            .where(FeeItem.structure_id == structure.id)
            .order_by(FeeItem.position, FeeItem.name)
        )
    )


def _students_of_grade(term: Term, grade: str) -> list[tuple[Student, SchoolClass]]:
    """Active students enrolled in the grade's classes in the term's year."""
    rows = db.session.execute(
        select(Student, SchoolClass)
        .join(Enrolment, Enrolment.student_id == Student.id)
        .join(SchoolClass, Enrolment.class_id == SchoolClass.id)
        .where(
            SchoolClass.academic_year_id == term.academic_year_id,
            SchoolClass.grade == grade,
            Student.is_active.is_(True),
        )
        .order_by(Student.full_name, Student.admission_number)
    )
    return [(student, school_class) for student, school_class in rows]


def _billed_student_ids(term: Term) -> set[uuid.UUID]:
    return set(db.session.scalars(select(Bill.student_id).where(Bill.term_id == term.id)))


def _totals(bill_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not bill_ids:
        return {}
    rows = db.session.execute(
        select(BillLine.bill_id, func.sum(BillLine.amount_kes))
        .where(BillLine.bill_id.in_(bill_ids))
        .group_by(BillLine.bill_id)
    )
    return {bill_id: int(total) for bill_id, total in rows}


def _paid(bill_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """What has been paid on each bill: its payments that are not cancelled."""
    if not bill_ids:
        return {}
    rows = db.session.execute(
        select(Payment.bill_id, func.sum(Payment.amount_kes))
        .outerjoin(PaymentCancellation, PaymentCancellation.payment_id == Payment.id)
        .where(Payment.bill_id.in_(bill_ids), PaymentCancellation.id.is_(None))
        .group_by(Payment.bill_id)
    )
    return {bill_id: int(paid) for bill_id, paid in rows}


def _money(total: int, paid: int) -> dict:
    """A bill's figures: balance below 0 means overpaid (a credit)."""
    return {"total_kes": total, "paid_kes": paid, "balance_kes": total - paid}


def _earlier(student_ids: list[uuid.UUID], before: date) -> dict[uuid.UUID, list[dict]]:
    """Each student's bills from terms that start before `before`, oldest
    first, with their balances (a few queries for any number of students)."""
    if not student_ids:
        return {}
    rows = db.session.execute(
        select(Bill.id, Bill.student_id, Term.number, AcademicYear.name)
        .join(Term, Bill.term_id == Term.id)
        .join(AcademicYear, Bill.academic_year_id == AcademicYear.id)
        .where(
            Bill.student_id.in_(student_ids),
            Bill.school_id == current_school().id,
            Term.starts_on < before,
        )
        .order_by(Term.starts_on)
    ).all()
    ids = [row.id for row in rows]
    totals, paid = _totals(ids), _paid(ids)
    earlier: dict[uuid.UUID, list[dict]] = {}
    for bill_id, student_id, number, year_name in rows:
        earlier.setdefault(student_id, []).append(
            {
                "id": str(bill_id),
                "term": {"number": number},
                "year": {"name": year_name},
                "balance_kes": totals.get(bill_id, 0) - paid.get(bill_id, 0),
            }
        )
    return earlier


def _earlier_json(bills: list[dict]) -> dict:
    """The balance from earlier terms (below 0 is a credit), and the earlier
    bills that are not settled, so staff can open them."""
    return {
        "balance_kes": sum(bill["balance_kes"] for bill in bills),
        "bills": [bill for bill in bills if bill["balance_kes"] != 0],
    }


def _with_earlier(money: dict, earlier: dict) -> dict:
    return {
        **money,
        "earlier": earlier,
        "due_now_kes": money["balance_kes"] + earlier["balance_kes"],
    }


def is_past_due(due_on: date | None, today: date) -> bool:
    """The pay-by date has passed (the pay-by day itself is not late)."""
    return due_on is not None and today > due_on


def is_overdue(due_on: date | None, balance_kes: int, today: date) -> bool:
    """Something is still owed after the pay-by date."""
    return balance_kes > 0 and is_past_due(due_on, today)


def _user_names(ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    return dict(db.session.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


# JSON.


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _spoken(value: date) -> str:
    """5 Jan 2027, as dates are written for people."""
    return f"{value.day} {value:%b %Y}"


def _student_json(student: Student) -> dict:
    return {
        "id": str(student.id),
        "full_name": student.full_name,
        "admission_number": student.admission_number,
    }


def _term_json(term: Term) -> dict:
    year = db.session.get(AcademicYear, term.academic_year_id)
    return {
        "term": {
            "id": str(term.id),
            "number": term.number,
            "starts_on": term.starts_on.isoformat(),
            "ends_on": term.ends_on.isoformat(),
        },
        "year": {"id": str(year.id), "name": year.name},
    }


def _structure_json(structure: FeeStructure | None) -> dict | None:
    if structure is None:
        return None
    items = _items(structure)
    names = _user_names({structure.issued_by_user_id, structure.updated_by_user_id})
    return {
        "id": str(structure.id),
        "items": [
            {
                "id": str(item.id),
                "name": item.name,
                "amount_kes": item.amount_kes,
                "is_optional": item.is_optional,
            }
            for item in items
        ],
        "compulsory_total_kes": sum(item.amount_kes for item in items if not item.is_optional),
        "due_on": _day(structure.due_on),
        "issued_at": _iso(structure.issued_at),
        "issued_by": names.get(structure.issued_by_user_id),
        "updated_at": _iso(structure.updated_at),
        "updated_by": names.get(structure.updated_by_user_id),
    }


def _grade_view(term: Term, grade: str) -> dict:
    structure = _structure(term, grade)
    bills: list[dict] = []
    if structure is not None:
        rows = db.session.execute(
            select(Bill, Student, SchoolClass)
            .join(Student, Bill.student_id == Student.id)
            .join(SchoolClass, Bill.class_id == SchoolClass.id)
            .where(Bill.structure_id == structure.id)
            .order_by(Student.full_name, Student.admission_number)
        ).all()
        ids = [bill.id for bill, _, _ in rows]
        totals, paid = _totals(ids), _paid(ids)
        bills = [
            {
                "id": str(bill.id),
                "student": _student_json(student),
                "class_name": school_class.name,
                **_money(totals.get(bill.id, 0), paid.get(bill.id, 0)),
            }
            for bill, student, school_class in rows
        ]
    billed = _billed_student_ids(term)
    not_billed = [
        {"student": _student_json(student), "class_name": school_class.name}
        for student, school_class in _students_of_grade(term, grade)
        if student.id not in billed
    ]
    return {
        **_term_json(term),
        "grade": {"code": grade, "name": GRADES[grade]},
        "can_manage": _can_manage(),
        "structure": _structure_json(structure),
        "bills": bills,
        "not_billed": not_billed,
    }


def _bill_json(bill: Bill) -> dict:
    student = db.session.get(Student, bill.student_id)
    school_class = db.session.get(SchoolClass, bill.class_id)
    structure = db.session.get(FeeStructure, bill.structure_id)
    term = db.session.get(Term, bill.term_id)
    # Oldest first; lines added together in the structure's order.
    lines = list(
        db.session.scalars(
            select(BillLine)
            .outerjoin(FeeItem, BillLine.fee_item_id == FeeItem.id)
            .where(BillLine.bill_id == bill.id)
            .order_by(BillLine.created_at, FeeItem.position.nulls_last(), BillLine.id)
        )
    )
    on_bill = {line.fee_item_id for line in lines}
    names = _user_names({bill.issued_by_user_id, *(line.created_by_user_id for line in lines)})
    money = _money(sum(line.amount_kes for line in lines), _paid([bill.id]).get(bill.id, 0))
    earlier = _earlier_json(_earlier([bill.student_id], term.starts_on).get(bill.student_id, []))
    return {
        "id": str(bill.id),
        "school": {"name": current_school().name},
        **_term_json(term),
        "student": _student_json(student),
        "class_name": school_class.name,
        "grade": {"code": structure.grade, "name": GRADES[structure.grade]},
        "issued_at": _iso(bill.issued_at),
        "issued_by": names.get(bill.issued_by_user_id),
        "due_on": _day(structure.due_on),
        "overdue": is_overdue(structure.due_on, money["balance_kes"], years_api.school_today()),
        "lines": [
            {
                "id": str(line.id),
                "kind": line.kind,
                "description": line.description,
                "amount_kes": line.amount_kes,
                "created_at": _iso(line.created_at),
                "created_by": names.get(line.created_by_user_id),
            }
            for line in lines
        ],
        **_with_earlier(money, earlier),
        "payments": _payments_json(bill),
        "optional_items": [
            {"id": str(item.id), "name": item.name, "amount_kes": item.amount_kes}
            for item in _items(structure)
            if item.is_optional and item.id not in on_bill
        ],
        # For fee follow-up: contacts only, primary guardian first.
        "guardians": [
            {
                "full_name": guardian.full_name,
                "relationship": link.relationship,
                "is_primary": link.is_primary,
                "phone": guardian.phone,
                "email": guardian.email,
            }
            for link, guardian in _links(student)
        ],
        "can_manage": _can_manage(),
        "can_record_payments": PAYMENTS_RECORD in current_permissions(),
        "can_cancel_payments": PAYMENTS_CANCEL in current_permissions(),
    }


def _payments_json(bill: Bill) -> list[dict]:
    """A bill's payments, in receipt order, cancelled ones included."""
    rows = db.session.execute(
        select(Payment, PaymentCancellation)
        .outerjoin(PaymentCancellation, PaymentCancellation.payment_id == Payment.id)
        .where(Payment.bill_id == bill.id)
        .order_by(Payment.receipt_number)
    ).all()
    names = _user_names(
        {p.recorded_by_user_id for p, _ in rows}
        | {c.cancelled_by_user_id for _, c in rows if c is not None}
    )
    return [payment_json(p, c, names) for p, c in rows]


def payment_json(
    payment: Payment, cancellation: PaymentCancellation | None, names: dict[uuid.UUID, str]
) -> dict:
    return {
        "id": str(payment.id),
        "receipt_number": payment.receipt_number,
        "amount_kes": payment.amount_kes,
        "method": payment.method,
        "reference": payment.reference,
        "paid_on": payment.paid_on.isoformat(),
        "paid_by": payment.paid_by,
        "recorded_at": _iso(payment.created_at),
        "recorded_by": names.get(payment.recorded_by_user_id),
        "cancelled": None
        if cancellation is None
        else {
            "reason": cancellation.reason,
            "cancelled_at": _iso(cancellation.created_at),
            "cancelled_by": names.get(cancellation.cancelled_by_user_id),
        },
    }


# Terms and grades.


@fees_bp.get("/fees/years/<uuid:year_id>/terms/<int:number>")
@permission_required(FEES_READ)
def term_fees(year_id: uuid.UUID, number: int):
    """Every grade with classes in the term's year: its structure, students
    and how many of them are billed."""
    term = _term(year_id, number, "fees.read")
    classes = db.session.execute(
        select(SchoolClass.grade, func.count())
        .where(SchoolClass.academic_year_id == term.academic_year_id)
        .group_by(SchoolClass.grade)
    ).all()
    students = dict(
        db.session.execute(
            select(SchoolClass.grade, func.count(Student.id))
            .join(Enrolment, Enrolment.class_id == SchoolClass.id)
            .join(Student, Enrolment.student_id == Student.id)
            .where(
                SchoolClass.academic_year_id == term.academic_year_id,
                Student.is_active.is_(True),
            )
            .group_by(SchoolClass.grade)
        ).all()
    )
    billed = dict(
        db.session.execute(
            select(FeeStructure.grade, func.count(Bill.id))
            .join(Bill, Bill.structure_id == FeeStructure.id)
            .where(FeeStructure.term_id == term.id)
            .group_by(FeeStructure.grade)
        ).all()
    )
    # Per grade: what was billed, what has been paid, and what is still owed.
    # An overpaid bill's credit does not lower another family's debt, so
    # "outstanding" adds up only the bills with something left to pay.
    bill_rows = db.session.execute(
        select(FeeStructure.grade, Bill.id)
        .join(Bill, Bill.structure_id == FeeStructure.id)
        .where(FeeStructure.term_id == term.id)
    ).all()
    bill_ids = [bill_id for _, bill_id in bill_rows]
    totals, paid = _totals(bill_ids), _paid(bill_ids)
    money: dict[str, dict[str, int]] = {}
    for grade, bill_id in bill_rows:
        sums = money.setdefault(grade, {"billed_kes": 0, "paid_kes": 0, "outstanding_kes": 0})
        total, received = totals.get(bill_id, 0), paid.get(bill_id, 0)
        sums["billed_kes"] += total
        sums["paid_kes"] += received
        sums["outstanding_kes"] += max(total - received, 0)
    structures = {
        structure.grade: structure
        for structure in db.session.scalars(
            select(FeeStructure).where(FeeStructure.term_id == term.id)
        )
    }
    order = list(GRADES)
    grades = []
    for grade, class_count in sorted(classes, key=lambda row: order.index(row[0])):
        structure = structures.get(grade)
        items = _items(structure) if structure else []
        grades.append(
            {
                "grade": grade,
                "name": GRADES[grade],
                "classes": class_count,
                "students": students.get(grade, 0),
                "billed": billed.get(grade, 0),
                **money.get(grade, {"billed_kes": 0, "paid_kes": 0, "outstanding_kes": 0}),
                "structure": None
                if structure is None
                else {
                    "items": len(items),
                    "compulsory_total_kes": sum(i.amount_kes for i in items if not i.is_optional),
                    "issued": structure.issued_at is not None,
                    "due_on": _day(structure.due_on),
                },
            }
        )
    return jsonify({**_term_json(term), "can_manage": _can_manage(), "grades": grades})


@fees_bp.get("/fees/years/<uuid:year_id>/terms/<int:number>/grades/<grade>")
@permission_required(FEES_READ)
def grade_fees(year_id: uuid.UUID, number: int, grade: str):
    term = _term(year_id, number, "fees.read")
    _grade_classes(term, grade, "fees.read")
    return jsonify(_grade_view(term, grade))


@fees_bp.put("/fees/years/<uuid:year_id>/terms/<int:number>/grades/<grade>")
@permission_required(FEES_MANAGE)
def save_structure(year_id: uuid.UUID, number: int, grade: str):
    term = _term(year_id, number, "fee_structure.saved")
    _grade_classes(term, grade, "fee_structure.saved")
    items = parse_json_body(SaveStructureRequest).items
    school_id = current_school().id

    # One save or issue at a time per school, so two first saves cannot
    # both create the structure, and a save cannot slip in beside an issue.
    db.session.execute(select(School.id).where(School.id == school_id).with_for_update())
    structure = _structure(term, grade, lock=True)
    if structure is not None and structure.issued_at is not None:
        db.session.rollback()
        raise ApiError(409, "structure_issued", STRUCTURE_ISSUED)
    if structure is None:
        structure = FeeStructure(
            school_id=school_id,
            academic_year_id=term.academic_year_id,
            term_id=term.id,
            grade=grade,
            updated_by_user_id=g.current_user.id,
        )
        db.session.add(structure)
        db.session.flush()
    else:
        structure.updated_by_user_id = g.current_user.id
        structure.updated_at = func.now()
        db.session.execute(delete(FeeItem).where(FeeItem.structure_id == structure.id))
    db.session.add_all(
        FeeItem(
            school_id=school_id,
            structure_id=structure.id,
            name=item.name,
            amount_kes=item.amount_kes,
            is_optional=item.is_optional,
            position=position,
        )
        for position, item in enumerate(items)
    )
    db.session.flush()
    audit.record(
        "fee_structure.saved",
        school_id=school_id,
        target_type="fee_structure",
        target_id=structure.id,
    )
    db.session.commit()
    current_app.logger.info(
        "Fee structure saved: structure_id=%s term_id=%s items=%s",
        structure.id,
        term.id,
        len(items),
    )
    return jsonify(_grade_view(term, grade))


@fees_bp.post("/fees/years/<uuid:year_id>/terms/<int:number>/grades/<grade>/issue")
@permission_required(FEES_MANAGE)
def issue_bills(year_id: uuid.UUID, number: int, grade: str):
    """Bill every active student of the grade not billed yet this term."""
    term = _term(year_id, number, "fee_bills.issued")
    _grade_classes(term, grade, "fee_bills.issued")
    school_id = current_school().id

    db.session.execute(select(School.id).where(School.id == school_id).with_for_update())
    structure = _structure(term, grade, lock=True)
    items = _items(structure) if structure else []
    if not items:
        db.session.rollback()
        raise ApiError(422, "no_fee_items", NO_FEE_ITEMS)

    billed = _billed_student_ids(term)
    to_bill = [(s, c) for s, c in _students_of_grade(term, grade) if s.id not in billed]
    compulsory = [item for item in items if not item.is_optional]
    for student, school_class in to_bill:
        bill = Bill(
            id=uuid.uuid4(),
            school_id=school_id,
            academic_year_id=term.academic_year_id,
            term_id=term.id,
            structure_id=structure.id,
            class_id=school_class.id,
            student_id=student.id,
            issued_by_user_id=g.current_user.id,
        )
        db.session.add(bill)
        db.session.add_all(
            BillLine(
                school_id=school_id,
                bill_id=bill.id,
                structure_id=structure.id,
                kind="fee",
                fee_item_id=item.id,
                description=item.name,
                amount_kes=item.amount_kes,
                created_by_user_id=g.current_user.id,
            )
            for item in compulsory
        )
    if to_bill:
        if structure.issued_at is None:
            structure.issued_at = func.now()
            structure.issued_by_user_id = g.current_user.id
        db.session.flush()
        audit.record(
            "fee_bills.issued",
            school_id=school_id,
            target_type="fee_structure",
            target_id=structure.id,
        )
    db.session.commit()
    if to_bill:
        current_app.logger.info(
            "Fee bills issued: structure_id=%s term_id=%s bills=%s",
            structure.id,
            term.id,
            len(to_bill),
        )
    return jsonify({"billed": len(to_bill), **_grade_view(term, grade)})


@fees_bp.put("/fees/years/<uuid:year_id>/terms/<int:number>/grades/<grade>/due-date")
@permission_required(FEES_MANAGE)
def set_due_date(year_id: uuid.UUID, number: int, grade: str):
    """Set, move or remove the pay-by date of a grade's fees for the term,
    before or after issuing."""
    action = "fee_structure.due_date_changed"
    term = _term(year_id, number, action)
    _grade_classes(term, grade, action)
    due_on = parse_json_body(DueDateRequest).due_on
    earliest = term.starts_on - DUE_DATE_EARLIEST_BEFORE_TERM
    if due_on is not None and not earliest <= due_on <= term.ends_on:
        raise ApiError(
            422,
            "due_date_out_of_range",
            f"Choose a pay-by date from {_spoken(earliest)} to {_spoken(term.ends_on)}"
            " (the term's last day).",
        )
    structure = _structure(term, grade, lock=True)
    if structure is None:
        db.session.rollback()
        raise ApiError(409, "no_fee_structure", NO_STRUCTURE_FOR_DUE_DATE)
    if structure.due_on != due_on:
        structure.due_on = due_on
        db.session.flush()
        audit.record(
            action,
            school_id=structure.school_id,
            target_type="fee_structure",
            target_id=structure.id,
        )
        db.session.commit()
        current_app.logger.info(
            "Fee pay-by date changed: structure_id=%s term_id=%s", structure.id, term.id
        )
    else:
        db.session.rollback()
    return jsonify(_grade_view(term, grade))


# Bills.


def _bill(bill_id: uuid.UUID, action: str) -> Bill:
    bill = db.session.scalar(
        select(Bill).where(Bill.id == bill_id, Bill.school_id == current_school().id)
    )
    if bill is None:
        _not_found(action, "bill", bill_id, BILL_NOT_FOUND)
    return bill


def _bill_for_change(bill_id: uuid.UUID, action: str) -> Bill:
    """The bill, with its student's row locked: one change to a student's
    bills at a time, so two adjustments cannot together pass below 0."""
    bill = _bill(bill_id, action)
    db.session.execute(select(Student.id).where(Student.id == bill.student_id).with_for_update())
    return bill


def _total(bill: Bill) -> int:
    return _totals([bill.id]).get(bill.id, 0)


@fees_bp.get("/fees/bills/<uuid:bill_id>")
@permission_required(FEES_READ)
def get_bill(bill_id: uuid.UUID):
    return jsonify(_bill_json(_bill(bill_id, "fees.read")))


@fees_bp.post("/fees/bills/<uuid:bill_id>/items")
@permission_required(FEES_MANAGE)
def add_bill_item(bill_id: uuid.UUID):
    bill = _bill_for_change(bill_id, "bill.item_added")
    fee_item_id = parse_json_body(AddBillItemRequest).fee_item_id
    item = db.session.scalar(
        select(FeeItem).where(FeeItem.id == fee_item_id, FeeItem.structure_id == bill.structure_id)
    )
    if item is None or not item.is_optional:
        db.session.rollback()
        raise ApiError(422, "not_an_optional_item", "Choose one of this bill's optional fee items.")
    already = db.session.scalar(
        select(BillLine.id).where(BillLine.bill_id == bill.id, BillLine.fee_item_id == item.id)
    )
    if already is not None:
        db.session.rollback()
        raise ApiError(409, "item_already_on_bill", "This item is already on the bill.")
    db.session.add(
        BillLine(
            school_id=bill.school_id,
            bill_id=bill.id,
            structure_id=bill.structure_id,
            kind="fee",
            fee_item_id=item.id,
            description=item.name,
            amount_kes=item.amount_kes,
            created_by_user_id=g.current_user.id,
        )
    )
    db.session.flush()
    audit.record("bill.item_added", school_id=bill.school_id, target_type="bill", target_id=bill.id)
    db.session.commit()
    current_app.logger.info("Bill item added: bill_id=%s fee_item_id=%s", bill.id, item.id)
    return jsonify(_bill_json(bill)), 201


@fees_bp.post("/fees/bills/<uuid:bill_id>/adjustments")
@permission_required(FEES_MANAGE)
def adjust_bill(bill_id: uuid.UUID):
    bill = _bill_for_change(bill_id, "bill.adjusted")
    body = parse_json_body(AdjustBillRequest)
    total = _total(bill)
    if total + body.amount_kes < 0:
        db.session.rollback()
        raise ApiError(
            422,
            "total_below_zero",
            f"A bill's total cannot go below 0. This bill's total is KES {total:,},"
            f" so it can be reduced by at most KES {total:,}.",
        )
    db.session.add(
        BillLine(
            school_id=bill.school_id,
            bill_id=bill.id,
            structure_id=bill.structure_id,
            kind="adjustment",
            fee_item_id=None,
            description=body.reason,
            amount_kes=body.amount_kes,
            created_by_user_id=g.current_user.id,
        )
    )
    db.session.flush()
    audit.record("bill.adjusted", school_id=bill.school_id, target_type="bill", target_id=bill.id)
    db.session.commit()
    current_app.logger.info("Bill adjusted: bill_id=%s", bill.id)
    return jsonify(_bill_json(bill)), 201


@fees_bp.get("/students/<uuid:student_id>/bills")
@permission_required(FEES_READ)
def student_bills(student_id: uuid.UUID):
    """A student's bills, newest term first (for the student page)."""
    student = db.session.scalar(
        select(Student).where(Student.id == student_id, Student.school_id == current_school().id)
    )
    if student is None:
        _not_found("fees.read", "student", student_id, STUDENT_NOT_FOUND)
    rows = db.session.execute(
        select(Bill, Term, AcademicYear, SchoolClass)
        .join(Term, Bill.term_id == Term.id)
        .join(AcademicYear, Bill.academic_year_id == AcademicYear.id)
        .join(SchoolClass, Bill.class_id == SchoolClass.id)
        .where(Bill.student_id == student.id)
        .order_by(Term.starts_on.desc())
    ).all()
    ids = [bill.id for bill, *_ in rows]
    totals, paid = _totals(ids), _paid(ids)
    return jsonify(
        {
            "student": _student_json(student),
            "bills": [
                {
                    "id": str(bill.id),
                    "term": {"id": str(term.id), "number": term.number},
                    "year": {"name": year.name},
                    "class_name": school_class.name,
                    **_money(totals.get(bill.id, 0), paid.get(bill.id, 0)),
                }
                for bill, term, year, school_class in rows
            ],
        }
    )
