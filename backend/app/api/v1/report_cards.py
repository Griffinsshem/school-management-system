"""Report cards and class teachers' comments (D7).

A report card is one student's term in one class: each subject's result,
the overall result (mean grade for Form classes), the class position when
the school shows positions, the term's attendance in the class, and the
class teacher's comment. Everything but the comment is worked out each time
from marks and registers (the same numbers as the results page); nothing
else is stored.

- Who may do what (decisions of 2026-11-02):
  * the readers of a class's results (school administrators, principals
    and the class teacher) read its report cards;
  * school administrators (`marks.record`) and the class teacher write the
    comments; principals only read;
  * everyone else gets 404, as if the class did not exist.
- A comment is plain text of up to 500 characters; saving an empty one
  clears it. Every change is audited (`report_comment.saved` /
  `report_comment.cleared`, target: the student), never with the text.
  Comments are personal data about children: they never go into logs.
"""

import uuid

from flask import Blueprint, current_app, g, jsonify
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app import audit
from app.api.v1.assessments import (
    _overview_class,
    _refuse,
    _sheet_students,
    results_data,
)
from app.api.v1.enrolments import _teaches  # Active class teacher of the class.
from app.auth.permissions import (
    MARKS_READ,
    MARKS_RECORD,
    MARKS_RECORD_OWN,
    current_permissions,
    permission_required,
)
from app.auth.schools import current_school
from app.extensions import db
from app.models import (
    AcademicYear,
    Assessment,
    AttendanceMark,
    AttendanceRegister,
    ReportComment,
    SchoolClass,
    Student,
    Term,
    User,
)
from app.models.attendance import STATUSES
from app.schemas import parse_json_body
from app.schemas.report_cards import SaveCommentRequest

report_cards_bp = Blueprint("report_cards", __name__, url_prefix="/school")

REPORT_CARDS_NOT_FOUND = "Report cards not found."
REPORT_CARD_NOT_FOUND = "Report card not found."


def _can_comment(school_class: SchoolClass) -> bool:
    permissions = current_permissions()
    return MARKS_RECORD in permissions or (
        MARKS_RECORD_OWN in permissions and _teaches(school_class)
    )


def _on_report(school_class: SchoolClass, term: Term, student_id: uuid.UUID) -> bool:
    """Whether the student has a report card in this class and term: the
    class's active students, and anyone with a mark in its term assessments
    (the same students as the results page)."""
    ids = list(
        db.session.scalars(
            select(Assessment.id).where(
                Assessment.class_id == school_class.id, Assessment.term_id == term.id
            )
        )
    )
    return any(student.id == student_id for student, _ in _sheet_students(ids, school_class.id))


def _attendance(school_class: SchoolClass, term: Term) -> dict[str, dict]:
    """Per student: days present, late and absent in this class's registers
    of the term."""
    rows = db.session.execute(
        select(AttendanceMark.student_id, AttendanceMark.status, func.count())
        .join(AttendanceRegister, AttendanceMark.register_id == AttendanceRegister.id)
        .where(
            AttendanceRegister.class_id == school_class.id,
            AttendanceRegister.date >= term.starts_on,
            AttendanceRegister.date <= term.ends_on,
        )
        .group_by(AttendanceMark.student_id, AttendanceMark.status)
    )
    counts: dict[str, dict] = {}
    for student_id, status, count in rows:
        entry = counts.setdefault(str(student_id), dict.fromkeys(STATUSES, 0))
        entry[status] += count
    return counts


def _comments(school_class: SchoolClass, term: Term) -> dict[str, dict]:
    writer = aliased(User)
    rows = db.session.execute(
        select(ReportComment, writer.full_name)
        .join(writer, ReportComment.updated_by_user_id == writer.id)
        .where(ReportComment.class_id == school_class.id, ReportComment.term_id == term.id)
    )
    return {
        str(comment.student_id): {
            "text": comment.comment,
            "updated_at": comment.updated_at.isoformat(),
            "updated_by": name,
        }
        for comment, name in rows
    }


def _report_cards(school_class: SchoolClass, term: Term) -> dict:
    data = results_data(school_class, term)
    attendance = _attendance(school_class, term)
    comments = _comments(school_class, term)
    for student in data["students"]:
        counts = attendance.get(student["id"], dict.fromkeys(STATUSES, 0))
        student["attendance"] = {**counts, "days_recorded": sum(counts.values())}
        student["comment"] = comments.get(student["id"])
    year = db.session.get(AcademicYear, school_class.academic_year_id)
    data["school"] = {"name": current_school().name}
    data["year"] = {"name": year.name}
    data["can_comment"] = _can_comment(school_class)
    if data["show_positions"]:
        data["position_out_of"] = sum(1 for s in data["students"] if s["position"] is not None)
    return data


def _one_card(data: dict, student_id: uuid.UUID) -> dict | None:
    """The class data with only one student's card, as `student`."""
    card = next((s for s in data.pop("students") if s["id"] == str(student_id)), None)
    if card is None:
        return None
    return {**data, "student": card}


@report_cards_bp.get("/classes/<uuid:class_id>/report-cards")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def list_report_cards(class_id: uuid.UUID):
    school_class, term = _overview_class(class_id, "report_cards.read")
    return jsonify(_report_cards(school_class, term))


@report_cards_bp.get("/classes/<uuid:class_id>/report-cards/<uuid:student_id>")
@permission_required(MARKS_READ, MARKS_RECORD, MARKS_RECORD_OWN)
def get_report_card(class_id: uuid.UUID, student_id: uuid.UUID):
    school_class, term = _overview_class(class_id, "report_cards.read")
    card = _one_card(_report_cards(school_class, term), student_id)
    if card is None:
        _refuse("report_cards.read", "student", student_id, REPORT_CARD_NOT_FOUND)
    return jsonify(card)


@report_cards_bp.put("/classes/<uuid:class_id>/report-cards/<uuid:student_id>/comment")
@permission_required(MARKS_RECORD, MARKS_RECORD_OWN)
def save_comment(class_id: uuid.UUID, student_id: uuid.UUID):
    school_class, term = _overview_class(class_id, "report_comment.saved")
    if not _can_comment(school_class):
        _refuse("report_comment.saved", "class", class_id, REPORT_CARDS_NOT_FOUND)
    text = parse_json_body(SaveCommentRequest).comment

    # One save per student at a time, so two saves cannot both insert.
    student = db.session.scalar(
        select(Student)
        .where(Student.id == student_id, Student.school_id == current_school().id)
        .with_for_update()
    )
    if student is None or not _on_report(school_class, term, student_id):
        _refuse("report_comment.saved", "student", student_id, REPORT_CARD_NOT_FOUND)

    school_id = current_school().id
    existing = db.session.scalar(
        select(ReportComment).where(
            ReportComment.class_id == school_class.id,
            ReportComment.term_id == term.id,
            ReportComment.student_id == student_id,
        )
    )
    action = None
    if not text:
        if existing is not None:
            db.session.delete(existing)
            action = "report_comment.cleared"
    elif existing is None:
        db.session.add(
            ReportComment(
                school_id=school_id,
                academic_year_id=school_class.academic_year_id,
                class_id=school_class.id,
                term_id=term.id,
                student_id=student_id,
                comment=text,
                updated_by_user_id=g.current_user.id,
            )
        )
        action = "report_comment.saved"
    elif existing.comment != text:
        existing.comment = text
        existing.updated_by_user_id = g.current_user.id
        action = "report_comment.saved"
    if action:
        db.session.flush()
        audit.record(action, school_id=school_id, target_type="student", target_id=student_id)
    card = _one_card(_report_cards(school_class, term), student_id)
    db.session.commit()

    if action:
        # IDs only: the comment is personal data about a child.
        current_app.logger.info(
            "Report card comment %s: class_id=%s term=%s student_id=%s",
            "cleared" if action == "report_comment.cleared" else "saved",
            school_class.id,
            term.number,
            student_id,
        )
    return jsonify(card)
